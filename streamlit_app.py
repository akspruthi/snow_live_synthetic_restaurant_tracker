import os
import json
import hashlib
import time
import random
import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime, timezone, timedelta
from streamlit_autorefresh import st_autorefresh

st.set_page_config(
    page_title="Osteria Bella — AI Restaurant Operations Command",
    page_icon=":material/restaurant:",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Connect to Snowflake
conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))


def _get_pacific_time_str():
    try:
        row = conn.query(
            "SELECT TO_CHAR(CONVERT_TIMEZONE('America/Los_Angeles', CURRENT_TIMESTAMP()), 'HH12:MI:SS AM') AS PT",
            ttl=5
        )
        return row["PT"].iloc[0] + " PT"
    except Exception:
        return datetime.now(timezone.utc).strftime("%I:%M:%S %p") + " UTC"


# Custom luxury styling enhancements
st.markdown("""
<style>
    div[data-testid="stMetric"] {
        background-color: #171F2C;
        border: 1px solid rgba(212, 175, 55, 0.2);
        border-radius: 10px;
        padding: 12px 16px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    }
    .action-card {
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 10px;
        background: #171F2C;
        border-top: 1px solid rgba(255, 255, 255, 0.05);
        border-right: 1px solid rgba(255, 255, 255, 0.05);
        border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    }
</style>
""", unsafe_allow_html=True)

# ----------------- Top Header & Direct Filters Ribbon -----------------
title_col, live_badge_col = st.columns([3, 1])
with title_col:
    st.title("Osteria Bella")
    st.caption("Contemporary Italian & Enoteca · AI-Powered Real-Time Floor Operations")

with live_badge_col:
    st.space("small")
    now = _get_pacific_time_str()
    st.badge(f"Live · {now}", icon=":material/sensors:", color="green")

# Main Page Filter & Action Ribbon
with st.container(border=True):
    col_store, col_simulate, col_refresh = st.columns([3.5, 2.0, 1.2], vertical_alignment="bottom")

    locations_df = conn.query("SELECT LOCATION_NAME FROM RESTAURANT_STREAM_DEMO.PUBLIC.OSTERIA_LOCATIONS ORDER BY 1", ttl=60)
    all_locations = ["All Locations"] + (locations_df["LOCATION_NAME"].tolist() if not locations_df.empty else [])

    with col_store:
        selected_location = st.selectbox("Store Location Filter", all_locations, key="top_store")

    with col_simulate:
        if st.button("Simulate Floor Shifts", icon=":material/autorenew:", use_container_width=True):
            with st.spinner("Simulating table turns, floor checks, and weather shifts..."):
                try:
                    with conn.cursor() as cur:
                        cur.execute("CALL RESTAURANT_STREAM_DEMO.PUBLIC.SP_GENERATE_OSTERIA_TELEMETRY()")
                    st.toast("Floor telemetry updated with live variance!", icon=":material/check_circle:")
                    st.cache_data.clear()
                    if "_ai_cache" in st.session_state:
                        del st.session_state["_ai_cache"]
                    if "_digest_cache" in st.session_state:
                        del st.session_state["_digest_cache"]
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

    with col_refresh:
        if st.button("Refresh", icon=":material/refresh:", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

# Track location changes for loading indicator
_prev_loc = st.session_state.get("_prev_location", selected_location)
_location_changed = _prev_loc != selected_location
st.session_state["_prev_location"] = selected_location


# ----------------- Helper: Cortex AI Suggested Actions -----------------
def _ai_inputs_hash(location, occupancy, seated, capacity, weather, patio, overstay, bookings):
    raw = f"{location}|{occupancy:.0f}|{seated}|{capacity}|{weather}|{patio}|{overstay}|{bookings}"
    return hashlib.md5(raw.encode()).hexdigest()


def _call_cortex_ai(location_name, occupancy_pct, seated_count, total_capacity, weather_desc, patio_status, overstay_summary, upcoming_bookings):
    focus_pools = [
        "table turnover efficiency, seating optimization, and kitchen timing",
        "guest experience quality, VIP handling, and floor flow bottlenecks",
        "staffing allocation, section balancing, and server workload",
        "weather-driven patio strategy, walk-in conversion, and wait time management",
        "peak preparation, reservation pacing, and capacity forecasting",
    ]
    focus = random.choice(focus_pools)

    prompt = f"""You are a sharp restaurant operations analyst for Osteria Bella, an upscale Italian restaurant.
Analyze this live floor snapshot and return 2-3 actionable insights as JSON.

LIVE DATA:
- Location: {location_name}
- Floor Occupancy: {occupancy_pct:.1f}% ({seated_count} seated / {total_capacity} capacity)
- Weather & Patio: {weather_desc} ({patio_status})
- Upcoming Bookings / Waitlist: {upcoming_bookings} parties waiting
- Long-seated tables (past expected duration): {overstay_summary}

ANALYSIS FOCUS for this cycle: {focus}

RULES:
1. Reference the specific location name and table numbers from the data in every suggestion.
2. Back every suggestion with specific numbers from the data above.
3. Each suggestion must cover a DIFFERENT operational concern — never repeat the same type of advice.
4. Vary severity levels — not everything is a warning. Use OK and INFO when things are running well.
5. Be specific and operational: name tables, cite percentages, suggest concrete next steps.
6. NEVER suggest: rushing guests, comping items, discounts, or serving alcohol.
7. Use ONLY facts present in the data. Do not invent information.

Return ONLY valid JSON array (no markdown, no commentary):
[
  {{
    "title": "Short punchy title (3-6 words)",
    "severity": "CRITICAL" or "WARNING" or "INFO" or "OK",
    "location": "{location_name}",
    "table_ref": "Table number(s) or 'N/A'",
    "facts": "Key data points supporting this action",
    "action": "One specific next step for the floor manager"
  }}
]"""
    try:
        ai_df = conn.query("SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3.1-70b', ?) AS AI_OUT", params=[prompt], ttl=600)
        raw_text = str(ai_df["AI_OUT"].iloc[0]).strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        return json.loads(raw_text.strip())
    except Exception:
        return None


def get_ai_suggestions(location, occupancy, seated, capacity, weather, patio, overstay, bookings, force=False):
    current_hash = _ai_inputs_hash(location, occupancy, seated, capacity, weather, patio, overstay, bookings)
    cache = st.session_state.get("_ai_cache", None)
    now_ts = time.time()

    if not force and cache is not None:
        if cache["inputs_hash"] == current_hash:
            return cache["directives"], cache["analyzed_at"]

    directives = _call_cortex_ai(location, occupancy, seated, capacity, weather, patio, overstay, bookings)
    analyzed_at = _get_pacific_time_str()
    st.session_state["_ai_cache"] = {
        "directives": directives,
        "analyzed_at": analyzed_at,
        "inputs_hash": current_hash,
        "timestamp": now_ts,
    }
    return directives, analyzed_at


# ----------------- Section: Executive KPI Row -----------------
def render_kpi_row(location_filter):
    if _location_changed:
        with st.spinner("Loading metrics..."):
            _render_kpi_row_inner(location_filter)
    else:
        _render_kpi_row_inner(location_filter)


def _render_kpi_row_inner(location_filter):
    cap_df = conn.query("SELECT * FROM RESTAURANT_STREAM_DEMO.PUBLIC.V_OSTERIA_CAPACITY", ttl=5)
    weather_df = conn.query("SELECT * FROM RESTAURANT_STREAM_DEMO.PUBLIC.OSTERIA_WEATHER", ttl=10)

    res_where = ""
    res_params = []
    if location_filter != "All Locations":
        res_where = "WHERE LOCATION_NAME = ?"
        res_params.append(location_filter)

    res_df = conn.query(f"""
        SELECT STATUS, EST_DURATION_MINS
        FROM RESTAURANT_STREAM_DEMO.PUBLIC.OSTERIA_RESERVATIONS {res_where}
    """, params=res_params if res_params else None, ttl=5)

    filtered_cap = cap_df.copy() if not cap_df.empty else pd.DataFrame()
    if location_filter != "All Locations" and not filtered_cap.empty:
        filtered_cap = filtered_cap[filtered_cap["LOCATION_NAME"] == location_filter]

    total_seats = int(filtered_cap["MAX_SEATS"].sum()) if not filtered_cap.empty else 0
    seated_guests = int(filtered_cap["CURRENT_GUESTS_SEATED"].sum()) if not filtered_cap.empty else 0
    active_tables = int(filtered_cap["ACTIVE_TABLES_SEATED"].sum()) if not filtered_cap.empty else 0
    upcoming_res = int(filtered_cap["UPCOMING_RESERVATIONS"].sum()) if not filtered_cap.empty else 0
    waitlist_count = int(filtered_cap["WAITLIST_COUNT"].sum()) if not filtered_cap.empty else 0
    live_floor_sales = float(filtered_cap["LIVE_FLOOR_REVENUE"].sum()) if not filtered_cap.empty else 0.0

    avg_occupancy = round((seated_guests / total_seats * 100), 1) if total_seats > 0 else 0.0

    operating_hours = 6.0
    revpash = round(live_floor_sales / (total_seats * operating_hours), 2) if total_seats > 0 else 0.0
    revpash_target = 6.50
    revpash_diff = round(((revpash - revpash_target) / revpash_target * 100), 1)
    revpash_delta_str = f"{revpash_diff:+.1f}% vs Target"

    avg_turn_mins = int(res_df[res_df["STATUS"] == "SEATED"]["EST_DURATION_MINS"].mean()) if not res_df.empty and not res_df[res_df["STATUS"] == "SEATED"].empty else 65
    turn_target = 65
    turn_diff = avg_turn_mins - turn_target
    turn_delta_str = f"{turn_diff:+d}m vs 65m Target"

    filtered_weather = weather_df.copy() if not weather_df.empty else pd.DataFrame()
    if location_filter != "All Locations" and not filtered_weather.empty:
        filtered_weather = filtered_weather[filtered_weather["LOCATION_NAME"] == location_filter]

    weather_text = "68°F · Sunny"
    patio_status = "Open"
    if not filtered_weather.empty:
        avg_temp = round(filtered_weather["TEMPERATURE_F"].mean(), 1)
        cond = filtered_weather["CONDITION"].iloc[0] if len(filtered_weather) == 1 else "Clear"
        patio_open = all(filtered_weather["PATIO_OPEN"])
        patio_status = "Patio Open" if patio_open else "Patio Closed"
        weather_text = f"{avg_temp}°F · {cond}"

    with st.container(horizontal=True):
        st.metric("Live Floor Sales", f"${live_floor_sales:,.2f}", f"{active_tables} tables active", border=True)
        st.metric("Floor Occupancy", f"{seated_guests} / {total_seats} seats", f"{avg_occupancy:.1f}% occupied", border=True)
        st.metric("Avg Turn Time", f"{avg_turn_mins} min", turn_delta_str, delta_color="inverse", border=True)
        st.metric("RevPASH ($/Seat-Hr)", f"${revpash:.2f}", revpash_delta_str, border=True)
        st.metric("Bookings / Waitlist", f"{upcoming_res} / {waitlist_count}", border=True)

    st.caption(f"{weather_text} · {patio_status}")


# ----------------- Section: Suggested Actions (AI) -----------------
def render_ai_section(location_filter):
    if _location_changed:
        with st.spinner("Loading AI suggestions..."):
            _render_ai_section_inner(location_filter)
    else:
        _render_ai_section_inner(location_filter)


def _render_ai_section_inner(location_filter):
    cap_df = conn.query("SELECT * FROM RESTAURANT_STREAM_DEMO.PUBLIC.V_OSTERIA_CAPACITY", ttl=5)
    weather_df = conn.query("SELECT * FROM RESTAURANT_STREAM_DEMO.PUBLIC.OSTERIA_WEATHER", ttl=10)

    res_where = ""
    res_params = []
    if location_filter != "All Locations":
        res_where = "WHERE LOCATION_NAME = ?"
        res_params.append(location_filter)

    res_df = conn.query(f"""
        SELECT TABLE_NUMBER, GUEST_NAME, PARTY_SIZE, STATUS, EST_DURATION_MINS, CURRENT_CHECK_TOTAL
        FROM RESTAURANT_STREAM_DEMO.PUBLIC.OSTERIA_RESERVATIONS {res_where}
    """, params=res_params if res_params else None, ttl=5)

    filtered_cap = cap_df.copy() if not cap_df.empty else pd.DataFrame()
    if location_filter != "All Locations" and not filtered_cap.empty:
        filtered_cap = filtered_cap[filtered_cap["LOCATION_NAME"] == location_filter]

    total_seats = int(filtered_cap["MAX_SEATS"].sum()) if not filtered_cap.empty else 0
    seated_guests = int(filtered_cap["CURRENT_GUESTS_SEATED"].sum()) if not filtered_cap.empty else 0
    upcoming_res = int(filtered_cap["UPCOMING_RESERVATIONS"].sum()) if not filtered_cap.empty else 0
    avg_occupancy = round((seated_guests / total_seats * 100), 1) if total_seats > 0 else 0.0

    filtered_weather = weather_df.copy() if not weather_df.empty else pd.DataFrame()
    if location_filter != "All Locations" and not filtered_weather.empty:
        filtered_weather = filtered_weather[filtered_weather["LOCATION_NAME"] == location_filter]

    weather_text = "68°F · Sunny"
    patio_status = "Open"
    if not filtered_weather.empty:
        avg_temp = round(filtered_weather["TEMPERATURE_F"].mean(), 1)
        cond = filtered_weather["CONDITION"].iloc[0] if len(filtered_weather) == 1 else "Clear"
        patio_open = all(filtered_weather["PATIO_OPEN"])
        patio_status = "Patio Open" if patio_open else "Patio Closed"
        weather_text = f"{avg_temp}°F · {cond}"

    overstay_df = res_df[(res_df["STATUS"] == "SEATED") & (res_df["EST_DURATION_MINS"] >= 85)] if not res_df.empty else pd.DataFrame()
    overstay_summary = "None currently"
    if not overstay_df.empty:
        overstay_items = [f"Table {r['TABLE_NUMBER']} ({r['GUEST_NAME']}, party of {r['PARTY_SIZE']}) at {r['EST_DURATION_MINS']}m" for _, r in overstay_df.head(3).iterrows()]
        overstay_summary = "; ".join(overstay_items)

    force_reanalyze = st.session_state.pop("_ai_force_reanalyze", False)

    ai_directives, analyzed_at = get_ai_suggestions(
        location_filter, avg_occupancy, seated_guests, total_seats,
        weather_text, patio_status, overstay_summary, upcoming_res,
        force=force_reanalyze
    )

    with st.container(border=True):
        hdr_col, time_col, btn_col = st.columns([2.5, 2, 1.5], vertical_alignment="bottom")
        with hdr_col:
            st.subheader("Suggested Actions")
        with time_col:
            st.caption(f"Cortex AI · Analyzed {analyzed_at}")
        with btn_col:
            if st.button("Re-Analyze Now", icon=":material/smart_toy:", use_container_width=True):
                st.session_state["_ai_force_reanalyze"] = True
                st.rerun()

        if ai_directives is None:
            st.info("Cortex AI returned no results. Click Re-Analyze Now to retry.")
            ai_directives = []

        color_map = {
            "CRITICAL": ("#E53E3E", "#FC8181", "rgba(229,62,62,0.25)", "#FEB2B2", "Critical"),
            "WARNING": ("#DD6B20", "#FBD38D", "rgba(221,107,32,0.25)", "#FEEBC8", "Warning"),
            "INFO": ("#3182CE", "#63B3ED", "rgba(49,130,206,0.25)", "#BEE3F8", "Info"),
            "OK": ("#38A169", "#68D391", "rgba(56,161,105,0.25)", "#C6F6D5", "OK"),
            "OPPORTUNITY": ("#3182CE", "#63B3ED", "rgba(49,130,206,0.25)", "#BEE3F8", "Info"),
            "SUCCESS": ("#38A169", "#68D391", "rgba(56,161,105,0.25)", "#C6F6D5", "OK"),
        }

        col_actions, col_quick = st.columns([3, 2])

        with col_actions:
            for item in ai_directives:
                sev = item.get("severity", "WARNING").upper()
                border_col, title_col_c, badge_bg, badge_fg, badge_label = color_map.get(sev, color_map["WARNING"])
                loc_ref = item.get("location", "")
                table_ref = item.get("table_ref", "")
                facts = item.get("facts", "")
                meta_parts = []
                if loc_ref:
                    meta_parts.append(loc_ref)
                if table_ref and table_ref != "N/A":
                    meta_parts.append(f"Table {table_ref}")
                meta_line = " · ".join(meta_parts)

                st.markdown(f"""
                <div class="action-card" style="border-left: 4px solid {border_col};">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 3px;">
                        <strong style="color: {title_col_c}; font-size: 1em;">{item.get('title', 'Action Item')}</strong>
                        <span style="font-size: 0.75em; background: {badge_bg}; color: {badge_fg}; padding: 2px 8px; border-radius: 4px; font-weight: bold;">{badge_label}</span>
                    </div>
                    {"<div style='font-size:0.8em;color:#94A3B8;margin-bottom:3px;'>" + meta_line + "</div>" if meta_line else ""}
                    {"<div style='font-size:0.82em;color:#CBD5E0;margin-bottom:4px;'>" + facts + "</div>" if facts else ""}
                    <div style="font-size: 0.88em; color: #F1F5F9; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 5px;">
                        <strong>Action:</strong> {item.get('action', '')}
                    </div>
                </div>
                """, unsafe_allow_html=True)

        with col_quick:
            st.markdown("**Walk-In Wait Estimates**")
            wait_2top = 0 if avg_occupancy < 50 else (15 if avg_occupancy < 80 else 30)
            wait_4top = 5 if avg_occupancy < 50 else (25 if avg_occupancy < 80 else 50)
            wait_6top = 15 if avg_occupancy < 50 else (40 if avg_occupancy < 80 else 75)

            with st.container(horizontal=True):
                st.metric("2-Top", f"{wait_2top} min" if wait_2top > 0 else "Immediate", border=True)
                st.metric("4-Top", f"{wait_4top} min" if wait_4top > 0 else "Immediate", border=True)
                st.metric("6+ Party", f"{wait_6top} min", border=True)

            st.space("small")
            st.markdown("**Quick Actions**")
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                if st.button("Flag for Manager", use_container_width=True, icon=":material/flag:"):
                    st.toast("Manager review flagged for current floor state.", icon=":material/check:")
            with col_b2:
                if st.button("Hold Bar Seating", use_container_width=True, icon=":material/lock:"):
                    st.toast("Host stand updated: Bar counter restricted to waitlist guests.", icon=":material/check:")

            # --- Demo Scenario ---
            st.space("small")
            st.markdown("**Demo Scenario**")
            st.caption("Step through: pay → cleanup → available → seat next")
            demo_loc = location_filter if location_filter != "All Locations" else None

            if demo_loc is None:
                st.info("Select a single location to run the demo scenario.", icon=":material/info:")
            else:
                if st.button("Advance Demo Step", use_container_width=True, icon=":material/play_arrow:", type="primary"):
                    with st.spinner("Advancing demo..."):
                        try:
                            with conn.cursor() as cur:
                                safe_loc = demo_loc.replace("'", "''")
                                cur.execute(f"CALL RESTAURANT_STREAM_DEMO.PUBLIC.SP_OSTERIA_DEMO_STEP('{safe_loc}')")
                                msg = cur.fetchone()[0]
                            if "STEP 1" in msg:
                                st.toast(msg, icon=":material/receipt_long:")
                            elif "STEP 2" in msg:
                                st.toast(msg, icon=":material/cleaning_services:")
                            elif "STEP 3" in msg:
                                st.toast(msg, icon=":material/event_available:")
                            elif "STEP 4" in msg:
                                st.toast(msg, icon=":material/airline_seat_recline_normal:")
                            else:
                                st.toast(msg, icon=":material/info:")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Demo step error: {e}")


# ----------------- Section: Sales Analysis & YoY Performance -----------------
def render_sales_section(location_filter):
    with st.container(border=True):
        col_stitle, col_sfilter = st.columns([3, 2], vertical_alignment="center")
        with col_stitle:
            st.subheader("Sales Pacing & YoY Performance")
        with col_sfilter:
            time_period = st.segmented_control(
                "Time Window",
                ["Today (Hourly)", "Last 7 Days (YoY)", "Last 30 Days (YoY)", "Last 90 Days (YoY)"],
                default="Last 7 Days (YoY)",
                label_visibility="collapsed"
            )

        sales_where_clauses = []
        sales_params = []
        if location_filter != "All Locations":
            sales_where_clauses.append("LOCATION_NAME = ?")
            sales_params.append(location_filter)

        if time_period == "Today (Hourly)":
            sales_where_clauses.append("SALE_DATE = CURRENT_DATE()")
            group_col = "HOUR_OF_DAY"
            group_label = "Hour of Day (24h)"
        elif time_period == "Last 7 Days (YoY)":
            sales_where_clauses.append("SALE_DATE >= DATEADD('day', -7, CURRENT_DATE())")
            group_col = "SALE_DATE"
            group_label = "Date"
        elif time_period == "Last 30 Days (YoY)":
            sales_where_clauses.append("SALE_DATE >= DATEADD('day', -30, CURRENT_DATE())")
            group_col = "SALE_DATE"
            group_label = "Date"
        else:
            sales_where_clauses.append("SALE_DATE >= DATEADD('day', -90, CURRENT_DATE())")
            group_col = "SALE_DATE"
            group_label = "Date"

        sales_where_sql = ("WHERE " + " AND ".join(sales_where_clauses)) if sales_where_clauses else ""

        history_sql = f"""
            SELECT
                {group_col} AS TIME_BUCKET,
                SUM(NET_SALES) AS CURRENT_SALES,
                SUM(PRIOR_YEAR_SALES) AS PRIOR_YEAR_SALES,
                SUM(COVERS) AS CURRENT_COVERS,
                SUM(PRIOR_YEAR_COVERS) AS PRIOR_COVERS
            FROM RESTAURANT_STREAM_DEMO.PUBLIC.OSTERIA_SALES_HISTORY
            {sales_where_sql}
            GROUP BY {group_col}
            ORDER BY {group_col} ASC
        """
        sales_history_df = conn.query(history_sql, params=sales_params if sales_params else None, ttl=30)

        cat_sql = f"""
            SELECT
                CATEGORY,
                SUM(NET_SALES) AS TOTAL_CATEGORY_SALES
            FROM RESTAURANT_STREAM_DEMO.PUBLIC.OSTERIA_SALES_HISTORY
            {sales_where_sql}
            GROUP BY CATEGORY
            ORDER BY TOTAL_CATEGORY_SALES DESC
        """
        cat_df = conn.query(cat_sql, params=sales_params if sales_params else None, ttl=30)

        yoy_growth_window = 0.0
        yoy_growth_str = "+0.0% YoY"
        if not sales_history_df.empty:
            tot_curr = float(sales_history_df["CURRENT_SALES"].sum())
            tot_prior = float(sales_history_df["PRIOR_YEAR_SALES"].sum())
            if tot_prior > 0:
                yoy_growth_window = round(((tot_curr - tot_prior) / tot_prior * 100), 1)
                yoy_growth_str = f"{yoy_growth_window:+.1f}% YoY"

        col_trend, col_cat = st.columns([3, 2])

        with col_trend:
            if not sales_history_df.empty:
                tot_curr = float(sales_history_df["CURRENT_SALES"].sum())
                tot_prior = float(sales_history_df["PRIOR_YEAR_SALES"].sum())

                growth_badge = f":green-badge[{yoy_growth_str}]" if yoy_growth_window >= 0 else f":red-badge[{yoy_growth_str}]"
                st.markdown(f"**Net Revenue vs. Prior Year** — {growth_badge} (${tot_curr:,.0f} vs ${tot_prior:,.0f})")

                melted = sales_history_df.melt(
                    id_vars=["TIME_BUCKET"],
                    value_vars=["CURRENT_SALES", "PRIOR_YEAR_SALES"],
                    var_name="PERIOD",
                    value_name="SALES"
                )
                melted["PERIOD"] = melted["PERIOD"].map({"CURRENT_SALES": "Current Period", "PRIOR_YEAR_SALES": "Prior Year (YoY)"})
                melted["TIME_BUCKET_STR"] = melted["TIME_BUCKET"].astype(str)

                line_colors = ["#D4AF37", "#64748B"] if yoy_growth_window >= 0 else ["#E53E3E", "#64748B"]

                yoy_chart = alt.Chart(melted).mark_line(point=True, strokeWidth=2.5).encode(
                    x=alt.X("TIME_BUCKET_STR:O", title=group_label),
                    y=alt.Y("SALES:Q", title="Net Sales ($)"),
                    color=alt.Color("PERIOD:N", scale=alt.Scale(domain=["Current Period", "Prior Year (YoY)"], range=line_colors)),
                    tooltip=[alt.Tooltip("TIME_BUCKET_STR:O", title=group_label), "PERIOD", alt.Tooltip("SALES:Q", format="$,.2f")]
                ).properties(height=260)

                st.altair_chart(yoy_chart, use_container_width=True)
            else:
                st.info("No sales history records for selected filter.")

        with col_cat:
            st.markdown("**Sales Mix by Menu Category**")
            if not cat_df.empty:
                cat_chart = alt.Chart(cat_df).mark_bar(cornerRadius=4).encode(
                    x=alt.X("TOTAL_CATEGORY_SALES:Q", title="Sales ($)"),
                    y=alt.Y("CATEGORY:N", title=None, sort="-x"),
                    color=alt.Color("CATEGORY:N", legend=None, scale=alt.Scale(scheme="goldorange")),
                    tooltip=["CATEGORY", alt.Tooltip("TOTAL_CATEGORY_SALES:Q", format="$,.2f")]
                ).properties(height=260)
                st.altair_chart(cat_chart, use_container_width=True)
            else:
                st.info("No category data.")


# ----------------- Section: Daily Digest -----------------
def render_daily_digest(location_filter):
    with st.container(border=True):
        st.subheader("Daily Digest")

        loc_where = ""
        loc_params = []
        if location_filter != "All Locations":
            loc_where = "AND s.LOCATION_NAME = ?"
            loc_params.append(location_filter)

        digest_df = conn.query(f"""
            SELECT
                s.LOCATION_NAME,
                SUM(s.NET_SALES) AS TODAY_SALES,
                SUM(s.PRIOR_YEAR_SALES) AS PY_SALES,
                SUM(s.COVERS) AS TODAY_COVERS,
                SUM(s.PRIOR_YEAR_COVERS) AS PY_COVERS,
                COUNT(DISTINCT s.SALE_ID) AS COMPLETED_CHECKS
            FROM RESTAURANT_STREAM_DEMO.PUBLIC.OSTERIA_SALES_HISTORY s
            WHERE s.SALE_DATE = CURRENT_DATE() {loc_where}
            GROUP BY s.LOCATION_NAME
            ORDER BY TODAY_SALES DESC
        """, params=loc_params if loc_params else None, ttl=15)

        if digest_df.empty:
            st.info("No completed checks recorded today yet. Run Simulate Floor Shifts to generate activity.")
            return

        total_sales = float(digest_df["TODAY_SALES"].sum())
        total_py = float(digest_df["PY_SALES"].sum())
        total_covers = int(digest_df["TODAY_COVERS"].sum())
        total_checks = int(digest_df["COMPLETED_CHECKS"].sum())
        top_loc = digest_df.iloc[0]["LOCATION_NAME"]
        top_loc_sales = float(digest_df.iloc[0]["TODAY_SALES"])
        yoy_pct = round(((total_sales - total_py) / total_py * 100), 1) if total_py > 0 else 0.0

        # Get live floor pressure (waitlist + upcoming) for the 4th card
        cap_where = ""
        cap_params = []
        if location_filter != "All Locations":
            cap_where = "WHERE LOCATION_NAME = ?"
            cap_params.append(location_filter)
        floor_df = conn.query(f"""
            SELECT COALESCE(SUM(WAITLIST_COUNT),0) AS WL, COALESCE(SUM(UPCOMING_RESERVATIONS),0) AS UPCOMING
            FROM RESTAURANT_STREAM_DEMO.PUBLIC.V_OSTERIA_CAPACITY {cap_where}
        """, params=cap_params if cap_params else None, ttl=5)
        waitlist_now = int(floor_df["WL"].iloc[0]) if not floor_df.empty else 0
        upcoming_now = int(floor_df["UPCOMING"].iloc[0]) if not floor_df.empty else 0

        avg_check = round(total_sales / total_checks, 2) if total_checks > 0 else 0

        col_d1, col_d2, col_d3, col_d4 = st.columns(4)
        with col_d1:
            st.metric("Today's Completed Sales", f"${total_sales:,.2f}", f"{yoy_pct:+.1f}% vs PY", border=True)
        with col_d2:
            st.metric("Covers Served", f"{total_covers}", f"{total_checks} checks closed", border=True)
        with col_d3:
            st.metric("Avg Check", f"${avg_check:,.2f}", border=True)
        with col_d4:
            st.metric("Floor Pressure", f"{waitlist_now} waiting", f"{upcoming_now} upcoming", border=True)

        # AI narrative digest
        digest_cache = st.session_state.get("_digest_cache", None)
        digest_key = f"{total_sales:.0f}|{total_covers}|{total_checks}"

        if digest_cache and digest_cache.get("key") == digest_key:
            narrative = digest_cache["narrative"]
        else:
            loc_lines = "\n".join([
                f"  - {r['LOCATION_NAME']}: ${float(r['TODAY_SALES']):,.0f} sales, {int(r['TODAY_COVERS'])} covers, {int(r['COMPLETED_CHECKS'])} checks"
                for _, r in digest_df.iterrows()
            ])
            digest_prompt = f"""Write a 2-3 sentence executive digest for today's restaurant operations.
Be specific with numbers. Mention the top performer and any notable patterns.

TODAY'S DATA:
- Total completed sales: ${total_sales:,.2f} ({yoy_pct:+.1f}% vs prior year)
- Total covers served: {total_covers} across {total_checks} closed checks
- Average check: ${avg_check:,.2f}
- By location:
{loc_lines}

Write in a confident, concise tone. No bullet points — just flowing prose. Do not invent data."""

            try:
                ai_df = conn.query(
                    "SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3.1-70b', ?) AS AI_OUT",
                    params=[digest_prompt], ttl=300
                )
                narrative = str(ai_df["AI_OUT"].iloc[0]).strip()
            except Exception:
                narrative = None

            st.session_state["_digest_cache"] = {"key": digest_key, "narrative": narrative}

        if narrative:
            st.markdown(f"""<div style="background:#171F2C; border-left:3px solid #D4AF37; padding:12px 16px; border-radius:6px; font-size:0.92em; color:#E2E8F0; line-height:1.6;">
{narrative}
</div>""", unsafe_allow_html=True)


# ----------------- Section: Floor Capacity & Seating -----------------
def render_capacity_and_stream(location_filter):
    cap_df = conn.query("SELECT * FROM RESTAURANT_STREAM_DEMO.PUBLIC.V_OSTERIA_CAPACITY", ttl=5)

    res_where = ""
    res_params = []
    if location_filter != "All Locations":
        res_where = "WHERE LOCATION_NAME = ?"
        res_params.append(location_filter)

    res_query = f"""
        SELECT
            RESERVATION_ID, LOCATION_NAME, GUEST_NAME, PARTY_SIZE, TABLE_NUMBER,
            STATUS, SEATING_AREA, RESERVATION_TIME, SEATED_AT, EST_DURATION_MINS,
            VIP_TIER, DIETARY_NOTES, CURRENT_CHECK_TOTAL
        FROM RESTAURANT_STREAM_DEMO.PUBLIC.OSTERIA_RESERVATIONS
        {res_where}
        ORDER BY
            CASE STATUS WHEN 'SEATED' THEN 1 WHEN 'WAITLIST' THEN 2 ELSE 3 END,
            RESERVATION_TIME DESC
    """
    res_df = conn.query(res_query, params=res_params if res_params else None, ttl=5)

    filtered_cap = cap_df.copy() if not cap_df.empty else pd.DataFrame()
    if location_filter != "All Locations" and not filtered_cap.empty:
        filtered_cap = filtered_cap[filtered_cap["LOCATION_NAME"] == location_filter]

    with st.container(border=True):
        st.subheader("Location Capacity & Table Turnover")

        if not filtered_cap.empty:
            cap_chart_df = filtered_cap.copy()

            cap_chart_df["CALC_OCCUPANCY_PCT"] = cap_chart_df.apply(
                lambda r: round((float(r["CURRENT_GUESTS_SEATED"]) / float(r["MAX_SEATS"]) * 100.0), 1) if float(r["MAX_SEATS"]) > 0 else 0.0,
                axis=1
            )
            cap_chart_df["LABEL_TEXT"] = cap_chart_df.apply(
                lambda r: f" {int(r['CURRENT_GUESTS_SEATED'])}/{int(r['MAX_SEATS'])} ({r['CALC_OCCUPANCY_PCT']:.0f}%)", axis=1
            )

            def calc_color(val):
                if val >= 80: return "#E53E3E"
                if val >= 50: return "#DD6B20"
                return "#38A169"
            cap_chart_df["HEX_COLOR"] = cap_chart_df["CALC_OCCUPANCY_PCT"].apply(calc_color)

            col_bars, col_table = st.columns([3, 2])

            with col_bars:
                bar_chart = alt.Chart(cap_chart_df).mark_bar(cornerRadius=4).encode(
                    x=alt.X(
                        "CALC_OCCUPANCY_PCT:Q",
                        title="Occupancy %",
                        scale=alt.Scale(domain=[0, 100]),
                        axis=alt.Axis(values=[0, 20, 40, 60, 80, 100], format="d")
                    ),
                    y=alt.Y("LOCATION_NAME:N", title=None, sort="-x"),
                    color=alt.Color("HEX_COLOR:N", scale=None, legend=None),
                    tooltip=[
                        alt.Tooltip("LOCATION_NAME:N", title="Store"),
                        alt.Tooltip("CURRENT_GUESTS_SEATED:Q", title="Seated"),
                        alt.Tooltip("MAX_SEATS:Q", title="Capacity"),
                        alt.Tooltip("CALC_OCCUPANCY_PCT:Q", title="Occupancy %", format=".1f"),
                        alt.Tooltip("UPCOMING_RESERVATIONS:Q", title="Bookings")
                    ]
                )

                text_labels = alt.Chart(cap_chart_df).mark_text(
                    align="left", baseline="middle", dx=6,
                    color="#F1F5F9", fontSize=11, fontWeight="bold"
                ).encode(
                    x=alt.X("CALC_OCCUPANCY_PCT:Q"),
                    y=alt.Y("LOCATION_NAME:N", sort="-x"),
                    text="LABEL_TEXT:N"
                )

                st.altair_chart((bar_chart + text_labels).properties(height=220), use_container_width=True)

            with col_table:
                display_cap = filtered_cap[[
                    "LOCATION_NAME", "CURRENT_GUESTS_SEATED", "MAX_SEATS", "UPCOMING_RESERVATIONS", "WAITLIST_COUNT"
                ]].copy()
                display_cap["OCCUPANCY_PCT_DISPLAY"] = cap_chart_df["CALC_OCCUPANCY_PCT"].apply(lambda v: f"{v:.1f}%")
                st.dataframe(
                    display_cap,
                    column_config={
                        "LOCATION_NAME": "Location",
                        "CURRENT_GUESTS_SEATED": st.column_config.NumberColumn("Seated", format="%d"),
                        "MAX_SEATS": st.column_config.NumberColumn("Capacity", format="%d"),
                        "OCCUPANCY_PCT_DISPLAY": "Occ %",
                        "UPCOMING_RESERVATIONS": st.column_config.NumberColumn("Bookings", format="%d"),
                        "WAITLIST_COUNT": st.column_config.NumberColumn("Waitlist", format="%d"),
                    },
                    use_container_width=True,
                    hide_index=True
                )

    with st.container(border=True):
        st.subheader("Live Guest Flow & Seating Stream")

        if not res_df.empty:
            disp_res = res_df[[
                "STATUS", "LOCATION_NAME", "GUEST_NAME", "PARTY_SIZE", "TABLE_NUMBER",
                "SEATING_AREA", "VIP_TIER", "CURRENT_CHECK_TOTAL", "DIETARY_NOTES"
            ]].copy()

            st.dataframe(
                disp_res,
                column_config={
                    "STATUS": st.column_config.TextColumn("Status"),
                    "LOCATION_NAME": "Location",
                    "GUEST_NAME": "Guest",
                    "PARTY_SIZE": st.column_config.NumberColumn("Party", format="%d"),
                    "TABLE_NUMBER": "Table",
                    "SEATING_AREA": "Section",
                    "VIP_TIER": "Tier",
                    "CURRENT_CHECK_TOTAL": st.column_config.NumberColumn("Tab", format="$%.2f"),
                    "DIETARY_NOTES": "Notes"
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No active reservations for selected filters.")

# ----------------- Execution Layout -----------------
render_daily_digest(selected_location)
st.space("small")
render_kpi_row(selected_location)
render_ai_section(selected_location)
st.space("small")
render_sales_section(selected_location)
st.space("small")
render_capacity_and_stream(selected_location)

st_autorefresh(interval=30_000, limit=None, key="dashboard_autorefresh")
