# Osteria Bella — Technical Architecture & Snowflake Setup Guide

## Architecture Overview

```
Streamlit App (streamlit_app.py)
    │
    ├── st.connection("snowflake") ─── Snowflake Connector (conn.query / conn.cursor)
    │       │
    │       ├── V_OSTERIA_CAPACITY (view) ──── OSTERIA_LOCATIONS + OSTERIA_RESERVATIONS
    │       ├── OSTERIA_WEATHER (table)
    │       ├── OSTERIA_SALES_HISTORY (table)
    │       ├── OSTERIA_RESERVATIONS (table)
    │       └── SNOWFLAKE.CORTEX.COMPLETE('llama3.1-70b', prompt) ── Cortex AI LLM
    │
    ├── streamlit-autorefresh (30s JS timer) ── Full-page synchronized rerun
    └── @st.cache_data(ttl=30) ────────────── AI Directives (Cortex AI)
```

## Snowflake Database Objects

All objects reside in `RESTAURANT_STREAM_DEMO.PUBLIC`.

### Tables

| Table | Description | Key Columns |
|-------|-------------|-------------|
| `OSTERIA_LOCATIONS` | 5 restaurant locations with seating metadata | `LOCATION_ID`, `LOCATION_NAME`, `MAX_SEATS`, `BAR_SEATS`, `PATIO_SEATS`, `MANAGER_NAME` |
| `OSTERIA_RESERVATIONS` | Live reservation and seating records | `RESERVATION_ID`, `LOCATION_ID`, `GUEST_NAME`, `PARTY_SIZE`, `TABLE_NUMBER`, `STATUS` (SEATED/CONFIRMED/WAITLIST), `SEATING_AREA`, `EST_DURATION_MINS`, `VIP_TIER`, `DIETARY_NOTES`, `CURRENT_CHECK_TOTAL` |
| `OSTERIA_WEATHER` | Per-location weather conditions | `LOCATION_ID`, `TEMPERATURE_F`, `CONDITION`, `PATIO_OPEN`, `WIND_MPH`, `PRECIPITATION_PCT` |
| `OSTERIA_SALES_HISTORY` | 90-day hourly sales with YoY comparisons | `LOCATION_ID`, `SALE_DATE`, `HOUR_OF_DAY`, `CATEGORY`, `NET_SALES`, `PRIOR_YEAR_SALES`, `COVERS` |

### Views

| View | Description | Source |
|------|-------------|--------|
| `V_OSTERIA_CAPACITY` | Real-time floor occupancy aggregation per location | Joins `OSTERIA_LOCATIONS` with `OSTERIA_RESERVATIONS`. Computes `CURRENT_GUESTS_SEATED`, `OCCUPANCY_PCT`, `AVAILABLE_SEATS`, `UPCOMING_RESERVATIONS`, `WAITLIST_COUNT`, `LIVE_FLOOR_REVENUE` |

### Stored Procedures

| Procedure | Description |
|-----------|-------------|
| `SP_GENERATE_OSTERIA_TELEMETRY()` | Regenerates all synthetic reservations, weather, and floor telemetry. Randomly shuffles 25 guest profiles across 5 locations using `ROW_NUMBER() OVER (PARTITION BY location ORDER BY RANDOM())` so each store gets a unique subset. Rotates weather conditions and jitters temperatures. |

## Snowflake Cortex AI Integration

### How the LLM is Called

```python
@st.cache_data(ttl=30)
def generate_ai_operational_directives(...):
    ai_df = conn.query(
        "SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3.1-70b', ?) AS AI_OUT",
        params=[prompt],
        ttl=45
    )
    # Returns (directives_list, analyzed_at_timestamp)
    return json.loads(raw_text.strip()), analyzed_at
```

- **Model**: `llama3.1-70b` (runs natively inside Snowflake — no external API keys or EAI needed)
- **Input**: Structured prompt with current occupancy %, weather, table overstays, and waitlist counts
- **Output**: JSON array of 2-3 operational directives with `title`, `severity`, `category`, `description`, `action`
- **Caching**: `@st.cache_data(ttl=30)` prevents redundant LLM calls within 30 seconds. The timestamp of the actual LLM call is baked into the cached return value, so the "Last analyzed" label only updates when a fresh call runs — not on every page render.
- **Cost**: ~0.78 credits per 1M tokens. Each call is ~450 tokens ($0.0004 per call)

### Required Cortex Privilege

```sql
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE <your_role>;
```

## Sales Data Generation Logic

Sales history is seeded with realistic variance:

| Location | YoY Growth Multiplier | Behavior |
|----------|-----------------------|----------|
| Downtown Flagship | 1.08x (positive) | Strong corporate lunch & dinner |
| Midtown West | 0.93x (negative) | Theater district foot traffic dip |
| Seaport Waterfront | 0.96x (negative) | Weather-sensitive, patio-dependent |
| Uptown Bistro | 0.97x (slight negative) | Soft weekday dinner |
| SoHo Loft | 1.15x (strong positive) | Trendy weekend brunch & late night |

Day-of-week multipliers: Friday/Saturday get 1.35x, weekdays get 0.90x.
Hourly multipliers: Dinner hours (6-9 PM) generate ~2.7x the revenue of lunch hours.
Random jitter: ±25-35% per row for natural variance.

## Deployment Options

### Option 1: Snowflake Workspace (Current)

The app runs inside Snowsight Workspaces with pre-installed dependencies. No `requirements.txt` needed. Connection uses the embedded Snowflake session via `st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))`.

### Option 2: Streamlit Community Cloud (Public URL)

1. Push `streamlit_app.py`, `pyproject.toml`, `.streamlit/config.toml`, and `requirements.txt` to GitHub.
2. Deploy on [share.streamlit.io](https://share.streamlit.io).
3. Configure secrets:
   ```toml
   [connections.snowflake]
   account = "xvqzrva-in59111"
   user = "OSTERIA_APP_SERVICE_USER"
   password = "OsteriaBella2026Secure!"
   role = "OSTERIA_APP_PUBLIC_ROLE"
   warehouse = "COMPUTE_WH"
   database = "RESTAURANT_STREAM_DEMO"
   schema = "PUBLIC"
   ```

### Service User & Role Setup

```sql
-- Read-only role for the public app
CREATE ROLE IF NOT EXISTS OSTERIA_APP_PUBLIC_ROLE;
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE OSTERIA_APP_PUBLIC_ROLE;
GRANT USAGE ON DATABASE RESTAURANT_STREAM_DEMO TO ROLE OSTERIA_APP_PUBLIC_ROLE;
GRANT USAGE ON SCHEMA RESTAURANT_STREAM_DEMO.PUBLIC TO ROLE OSTERIA_APP_PUBLIC_ROLE;
GRANT SELECT ON ALL TABLES IN SCHEMA RESTAURANT_STREAM_DEMO.PUBLIC TO ROLE OSTERIA_APP_PUBLIC_ROLE;
GRANT SELECT ON ALL VIEWS IN SCHEMA RESTAURANT_STREAM_DEMO.PUBLIC TO ROLE OSTERIA_APP_PUBLIC_ROLE;
GRANT SELECT ON FUTURE TABLES IN SCHEMA RESTAURANT_STREAM_DEMO.PUBLIC TO ROLE OSTERIA_APP_PUBLIC_ROLE;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA RESTAURANT_STREAM_DEMO.PUBLIC TO ROLE OSTERIA_APP_PUBLIC_ROLE;
GRANT USAGE ON ALL PROCEDURES IN SCHEMA RESTAURANT_STREAM_DEMO.PUBLIC TO ROLE OSTERIA_APP_PUBLIC_ROLE;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE OSTERIA_APP_PUBLIC_ROLE;

-- Service user
CREATE USER IF NOT EXISTS OSTERIA_APP_SERVICE_USER
    PASSWORD = 'OsteriaBella2026Secure!'
    DEFAULT_ROLE = OSTERIA_APP_PUBLIC_ROLE
    DEFAULT_WAREHOUSE = COMPUTE_WH
    MUST_CHANGE_PASSWORD = FALSE;

GRANT ROLE OSTERIA_APP_PUBLIC_ROLE TO USER OSTERIA_APP_SERVICE_USER;
```

## File Structure

```
/workspace/
├── streamlit_app.py              # Main Streamlit dashboard app
├── pyproject.toml                # Python dependencies (Snowflake + Streamlit Cloud compatible)
├── requirements.txt              # Fallback dependencies for Streamlit Community Cloud
├── snowflake.yml                 # Snowflake Workspace Streamlit entity configuration
├── setup_public_app_user.sql     # SQL script to create the read-only service user & role
├── .streamlit/
│   └── config.toml               # Dark luxury theme (Tuscan Gold & Midnight Slate)
├── README.md                     # General overview doc
└── TECHNICAL.md                  # This file — full technical architecture
```

## Streamlit Performance Architecture

| Section | Render Strategy | Refresh Cycle |
|---------|-----------------|---------------|
| Live Clock | Inline `datetime.now()` | Updates on each page rerun (every 30s) |
| KPI Row | Plain function, queries with `ttl=5` | Every rerun (data re-fetches when TTL expires) |
| AI Directives | `@st.cache_data(ttl=30)` with baked-in timestamp | Fresh LLM call every ~30s; "Re-Analyze Now" button clears cache for immediate re-evaluation |
| Sales & YoY Charts | Plain function, queries with `ttl=10` | Every rerun + on time window filter change |
| Capacity & Guest Feed | Plain function, queries with `ttl=5` | Every rerun |
| **Page Rerun** | `streamlit-autorefresh` (client-side JS timer) | Every 30 seconds; browser throttles when tab is inactive |

### Scheduled Data Generation

| Object | Type | Schedule |
|--------|------|----------|
| `TASK_OSTERIA_TELEMETRY_STREAM` | Snowflake Task | Every 5 minutes (currently SUSPENDED) |

The task calls `SP_GENERATE_OSTERIA_TELEMETRY()` to regenerate reservations, weather, and floor data on a schedule. Resume it before a demo with:

```sql
ALTER TASK RESTAURANT_STREAM_DEMO.PUBLIC.TASK_OSTERIA_TELEMETRY_STREAM RESUME;
```

## Theme Configuration

`.streamlit/config.toml`:
```toml
[theme]
base = "dark"
primaryColor = "#D4AF37"           # Tuscan Gold
backgroundColor = "#0F141C"        # Midnight Slate
secondaryBackgroundColor = "#171F2C" # Polished Charcoal Navy
textColor = "#F1F5F9"              # Crisp Slate White
font = "sans serif"
```

## Estimated Costs (3-Day Window)

| Configuration | Credits | Est. Cost (~$3/credit) |
|---|---|---|
| On-demand only (queries when dashboard is open) | 2-5 credits | $6-$15 |
| Auto-refresh with 60s auto-suspend warehouse | 18-20 credits | $54-$60 |
| Cortex AI (llama3.1-70b) at ~1,440 calls over 3 days | ~0.5 credits | ~$1.50 |
