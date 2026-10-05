import os
import json
import time
import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
from zoneinfo import ZoneInfo
from streamlit_autorefresh import st_autorefresh

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

st.set_page_config(
    page_title="Osteria Bella — AI Restaurant Operations Command",
    page_icon=":material/restaurant:",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Connect to Snowflake
conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))

# Custom luxury styling enhancements
st.markdown("""
<style>
    /* Metric Card Styling */
    div[data-testid="stMetric"] {
        background-color: #171F2C;
        border: 1px solid rgba(212, 175, 55, 0.2);
        border-radius: 10px;
        padding: 12px 16px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    }

    /* Action Cards */
    .action-card {
        border-radius: 8px;
        padding: 14px 18px;
        margin-bottom: 12px;
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
    st.caption("Contemporary Italian & Enoteca · AI-Powered Real-Time Floor Operations & Capacity Command")

with live_badge_col:
    st.space("small")
    now = datetime.now(PACIFIC_TZ).strftime("%I:%M:%S %p PT")
    st.badge(f"Live · {now}", icon=":material/sensors:", color="green")

# Main Page Filter & Action Ribbon
with st.container(border=True):
    col_store, col_simulate, col_refresh = st.columns([3.5, 2.0, 1.2], vertical_alignment="bottom")

    locations_df = conn.query("SELECT LOCATION_NAME FROM RESTAURANT_STREAM_DEMO.PUBLIC.OSTERIA_LOCATIONS ORDER BY 1", ttl=60)
    all_locations = ["All Locations"] + (locations_df["LOCATION_NAME"].tolist() if not locations_df.empty else [])
    
    with col_store:
        selected_location = st.selectbox("📍 Store Location Filter", all_locations, key="top_store")

    with col_simulate:
        if st.button("Simulate Floor Shifts", icon=":material/autorenew:", use_container_width=True):
            with st.spinner("Simulating table turns, floor checks, and weather shifts..."):
                try:
                    with conn.cursor() as cur:
                        cur.execute("CALL RESTAURANT_STREAM_DEMO.PUBLIC.SP_GENERATE_OSTERIA_TELEMETRY()")
                    st.toast("Floor telemetry updated with live variance!", icon=":material/check_circle:")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

    with col_refresh:
        if st.button("Refresh", icon=":material/refresh:", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

st.space("small")

# ----------------- Helper: Cortex AI Action Items Generator (Live LLM Call) -----------------
@st.cache_data(ttl=30)
def generate_ai_operational_directives(location_name, occupancy_pct, seated_count, total_capacity, weather_desc, patio_status, overstay_summary, upcoming_bookings):
    prompt = f"""You are the AI General Manager for Osteria Bella (Contemporary Italian restaurant).
Analyze this live floor telemetry snapshot:
- Location: {location_name}
- Floor Occupancy: {occupancy_pct:.1f}% ({seated_count} seated / {total_capacity} total seats)
- Weather & Patio: {weather_desc} ({patio_status})
- Upcoming Bookings / Waitlist: {upcoming_bookings} parties
- Key Overstay Bottlenecks: {overstay_summary}

Generate a JSON list of 2 to 3 concise, tactical operational action items for the floor manager or chef right now.
Return ONLY valid JSON (no markdown ticks, no commentary) formatted as:
[
  {{
    "title": "Short title",
    "severity": "CRITICAL" or "WARNING" or "OPPORTUNITY" or "SUCCESS",
    "category": "FLOOR" or "WEATHER" or "KITCHEN",
    "description": "Specific context with numbers/parties",
    "action": "Concrete directive for the manager"
  }}
]"""
    try:
        ai_df = conn.query("SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3.1-70b', ?) AS AI_OUT", params=[prompt], ttl=45)
        raw_text = str(ai_df["AI_OUT"].iloc[0]).strip()
        if raw_text.startswith("```json"): raw_text = raw_text[7:]
        if raw_text.startswith("```"): raw_text = raw_text[3:]
        if raw_text.endswith("```"): raw_text = raw_text[:-3]
        return json.loads(raw_text.strip())
    except Exception as e:
        return None

# ----------------- Section 1: Executive KPI Row & Live Floor Telemetry -----------------
def render_kpi_row(location_filter):
    cap_query = "SELECT * FROM RESTAURANT_STREAM_DEMO.PUBLIC.V_OSTERIA_CAPACITY"
    cap_df = conn.query(cap_query, ttl=5)

    weather_query = "SELECT * FROM RESTAURANT_STREAM_DEMO.PUBLIC.OSTERIA_WEATHER"
    weather_df = conn.query(weather_query, ttl=10)

    res_where = ""
    res_params = []
    if location_filter != "All Locations":
        res_where = "WHERE LOCATION_NAME = ?"
        res_params.append(location_filter)

    res_query = f"""
        SELECT 
            STATUS, EST_DURATION_MINS
        FROM RESTAURANT_STREAM_DEMO.PUBLIC.OSTERIA_RESERVATIONS
        {res_where}
    """
    res_df = conn.query(res_query, params=res_params if res_params else None, ttl=5)

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
        patio_status = "Patio Open" if patio_open else "⚠️ Patio Closed"
        weather_text = f"{avg_temp}°F · {cond}"

    with st.container(horizontal=True):
        st.metric("Live Floor Sales", f"${live_floor_sales:,.2f}", f"{active_tables} tables active", border=True)
        st.metric("Floor Occupancy", f"{seated_guests} / {total_seats} seats", f"{avg_occupancy:.1f}% occupied", border=True)
        st.metric("Avg Table Turn Time", f"{avg_turn_mins} mins", turn_delta_str, delta_color="inverse", border=True)
        st.metric("RevPASH ($/Seat-Hr)", f"${revpash:.2f}", revpash_delta_str, border=True)
        st.metric("Bookings / Waitlist", f"{upcoming_res} / {waitlist_count}", border=True)
        st.metric("Weather & Patio", weather_text, patio_status, delta_color="normal" if "Open" in patio_status else "inverse", border=True)

# ----------------- Section 2: AI Directives (Simple Direct Cortex AI Call) -----------------
def render_ai_section(location_filter):
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
        overstay_items = [f"Table {r['TABLE_NUMBER']} ({r['GUEST_NAME']}, party of {r['PARTY_SIZE']}) at {r['EST_DURATION_MINS']}m (tab ${r['CURRENT_CHECK_TOTAL']:.0f})" for _, r in overstay_df.head(2).iterrows()]
        overstay_summary = "; ".join(overstay_items)

    with st.container(border=True):
        ai_header_col, ai_action_col = st.columns([3, 2], vertical_alignment="bottom")
        with ai_header_col:
            st.subheader("🤖 Operator Directives & Action Items")
        with ai_action_col:
            if st.button("Re-Analyze Now", icon=":material/smart_toy:", use_container_width=True):
                generate_ai_operational_directives.clear()
                st.rerun()

        col_actions, col_quick = st.columns([3, 2])

        with col_actions:
            ai_directives = generate_ai_operational_directives(
                location_filter, avg_occupancy, seated_guests, total_seats, weather_text, patio_status, overstay_summary, upcoming_res
            )

            last_eval = datetime.now(PACIFIC_TZ).strftime("%I:%M:%S %p PT")
            st.success(f"**Cortex AI (llama3.1-70b)** · Last analyzed: {last_eval} · Refreshes every 30s", icon=":material/smart_toy:")

            if ai_directives is None:
                st.caption("Cortex AI returned no results. Retrying on next refresh cycle.")
                ai_directives = []

            color_map = {
                "CRITICAL": ("#E53E3E", "#FC8181", "rgba(229,62,62,0.25)", "#FEB2B2", "🔴 Critical"),
                "WARNING": ("#DD6B20", "#FBD38D", "rgba(221,107,32,0.25)", "#FEEBC8", "🟠 Warning"),
                "OPPORTUNITY": ("#3182CE", "#63B3ED", "rgba(49,130,206,0.25)", "#BEE3F8", "🔵 Opportunity"),
                "SUCCESS": ("#38A169", "#68D391", "rgba(56,161,105,0.25)", "#C6F6D5", "🟢 Efficient")
            }

            for item in ai_directives:
                sev = item.get("severity", "WARNING").upper()
                border_col, title_col, badge_bg, badge_fg, badge_label = color_map.get(sev, color_map["WARNING"])
                
                st.markdown(f"""
                <div class="action-card" style="border-left: 4px solid {border_col};">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                        <strong style="color: {title_col}; font-size: 1.05em;">{item.get('title', 'Operational Item')}</strong>
                        <span style="font-size: 0.8em; background: {badge_bg}; color: {badge_fg}; padding: 2px 8px; border-radius: 4px; font-weight: bold;">{badge_label}</span>
                    </div>
                    <div style="font-size: 0.9em; color: #CBD5E0; line-height: 1.4; margin-bottom: 6px;">
                        {item.get('description', '')}
                    </div>
                    <div style="font-size: 0.9em; color: #F1F5F9; line-height: 1.4; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 6px;">
                        <strong>Action:</strong> {item.get('action', '')}
                    </div>
                </div>
                """, unsafe_allow_html=True)

        with col_quick:
            st.markdown("**Live Walk-In Quotes & Floor Throttle**")
            wait_2top = 0 if avg_occupancy < 50 else (15 if avg_occupancy < 80 else 30)
            wait_4top = 5 if avg_occupancy < 50 else (25 if avg_occupancy < 80 else 50)
            wait_6top = 15 if avg_occupancy < 50 else (40 if avg_occupancy < 80 else 75)

            with st.container(horizontal=True):
                st.metric("2-Top Walk-In", f"{wait_2top} min" if wait_2top > 0 else "Immediate", border=True)
                st.metric("4-Top Walk-In", f"{wait_4top} min" if wait_4top > 0 else "Immediate", border=True)
                st.metric("6+ Group", f"{wait_6top} min", border=True)

            st.space("small")
            st.markdown("**Quick Operator Actions**")
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                if st.button("Send Limoncello Reset", use_container_width=True, icon=":material/local_bar:"):
                    st.toast("Floor alert dispatched: Complimentary digestif sent to wrap table.", icon=":material/check:")
            with col_b2:
                if st.button("Hold Bar Seating", use_container_width=True, icon=":material/lock:"):
                    st.toast("Host stand updated: Bar counter restricted to waitlist guests.", icon=":material/check:")

# ----------------- Section 3: Sales Analysis & YoY Performance -----------------
def render_sales_section(location_filter):
    with st.container(border=True):
        col_stitle, col_sfilter = st.columns([3, 2], vertical_alignment="center")
        with col_stitle:
            st.subheader("📈 Sales Pacing & Year-over-Year (YoY) Performance")
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
        else: # Last 90 Days
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

# ----------------- Section 4: Floor Capacity & Seating Sections -----------------
def render_capacity_and_stream(location_filter):
    cap_query = "SELECT * FROM RESTAURANT_STREAM_DEMO.PUBLIC.V_OSTERIA_CAPACITY"
    cap_df = conn.query(cap_query, ttl=5)

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
        st.subheader("🪑 Location Capacity & Live Table Turnover")

        if not filtered_cap.empty:
            cap_chart_df = filtered_cap.copy()
            
            cap_chart_df["CALC_OCCUPANCY_PCT"] = cap_chart_df.apply(
                lambda r: round((float(r["CURRENT_GUESTS_SEATED"]) / float(r["MAX_SEATS"]) * 100.0), 1) if float(r["MAX_SEATS"]) > 0 else 0.0,
                axis=1
            )
            cap_chart_df["LABEL_TEXT"] = cap_chart_df.apply(
                lambda r: f" {int(r['CURRENT_GUESTS_SEATED'])}/{int(r['MAX_SEATS'])} seats ({r['CALC_OCCUPANCY_PCT']:.1f}%)", axis=1
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
                        title="Occupancy % (0% to 100% capacity)",
                        scale=alt.Scale(domain=[0, 100]),
                        axis=alt.Axis(values=[0, 20, 40, 60, 80, 100], format="d")
                    ),
                    y=alt.Y("LOCATION_NAME:N", title=None, sort="-x"),
                    color=alt.Color("HEX_COLOR:N", scale=None, legend=None),
                    tooltip=[
                        alt.Tooltip("LOCATION_NAME:N", title="Store"),
                        alt.Tooltip("CURRENT_GUESTS_SEATED:Q", title="Seated Guests"),
                        alt.Tooltip("MAX_SEATS:Q", title="Max Capacity"),
                        alt.Tooltip("CALC_OCCUPANCY_PCT:Q", title="Occupancy %", format=".1f"),
                        alt.Tooltip("UPCOMING_RESERVATIONS:Q", title="Bookings")
                    ]
                )

                text_labels = alt.Chart(cap_chart_df).mark_text(
                    align="left",
                    baseline="middle",
                    dx=6,
                    color="#F1F5F9",
                    fontSize=11,
                    fontWeight="bold"
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
                        "LOCATION_NAME": "Store Location",
                        "CURRENT_GUESTS_SEATED": st.column_config.NumberColumn("Seated", format="%d"),
                        "MAX_SEATS": st.column_config.NumberColumn("Capacity", format="%d"),
                        "OCCUPANCY_PCT_DISPLAY": "Occupancy",
                        "UPCOMING_RESERVATIONS": st.column_config.NumberColumn("Reservations", format="%d"),
                        "WAITLIST_COUNT": st.column_config.NumberColumn("Waitlist", format="%d"),
                    },
                    use_container_width=True,
                    hide_index=True
                )

    st.space("medium")

    with st.container(border=True):
        st.subheader("⏱️ Live Guest Flow & Seating Stream")

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
                    "GUEST_NAME": "Guest Name",
                    "PARTY_SIZE": st.column_config.NumberColumn("Party", format="%d guests"),
                    "TABLE_NUMBER": "Table",
                    "SEATING_AREA": "Section",
                    "VIP_TIER": "Tier",
                    "CURRENT_CHECK_TOTAL": st.column_config.NumberColumn("Current Tab", format="$%.2f"),
                    "DIETARY_NOTES": "Guest & Kitchen Notes"
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No active reservations for selected filters.")

# ----------------- Execution Layout -----------------
# 1. Executive KPI Metrics Row
render_kpi_row(selected_location)
st.space("medium")

# 2. AI Directives (instant from session state — never blocks)
render_ai_section(selected_location)
st.space("medium")

# 3. Sales Analysis & YoY Performance Charts
render_sales_section(selected_location)
st.space("medium")

# 4. Floor Capacity & Seating Live Streams
render_capacity_and_stream(selected_location)

# 5. Auto-refresh: JavaScript timer triggers a clean full-page rerun every 30s
st_autorefresh(interval=30_000, limit=None, key="dashboard_autorefresh")
