# Osteria Bella — AI Restaurant Operations Dashboard

A real-time restaurant operations command dashboard for **Osteria Bella**, a contemporary Italian restaurant chain with 5 metro locations. Built with Streamlit on Snowflake, powered by Snowflake Cortex AI.

## What the Dashboard Shows

**Executive KPI Row** — Live floor sales, seat occupancy %, average table turn time, RevPASH (revenue per available seat hour), upcoming bookings/waitlist count, and local weather with patio status.

**Cortex AI Operator Directives** — Snowflake Cortex AI (llama3.1-70b) analyzes the current floor state (occupancy, table overstays, weather, waitlist pressure) and generates 2-3 tactical action items with severity levels (Critical, Warning, Opportunity, Success). Each directive includes a specific recommended action for the floor manager. The AI re-analyzes on each page load and can be forced with the "Re-Analyze Now" button.

**Sales Pacing & YoY Performance** — Revenue trend lines comparing current period vs. prior year, with an inline time window selector (Today, Last 7 Days, Last 30 Days, Last 90 Days). Includes a menu category sales mix breakdown (Antipasti, Primi Piatti, Secondi, Dolci, Vini & Cocktails).

**Location Capacity & Table Turnover** — Horizontal bar chart showing per-store occupancy percentage with color-coded thresholds (green < 50%, orange 50-80%, red > 80%), plus a breakdown table of seated guests, max capacity, upcoming reservations, and waitlist counts.

**Live Guest Flow & Seating Stream** — Real-time table of all active reservations showing status (Seated, Confirmed, Waitlist), guest name, party size, table number, seating section, VIP tier, current tab amount, and dietary/kitchen notes.

## What Data is Synthetic

All data in this dashboard is **synthetic and simulated**. No real restaurant, guests, or financial data is used.

- **Locations**: 5 fictional Osteria Bella locations (Downtown Flagship, Midtown West, Seaport Waterfront, Uptown Bistro, SoHo Loft) with realistic seating capacities (60-110 seats).
- **Reservations & Guests**: 25 fictional guest profiles randomly assigned to locations. Each location gets a unique random subset — no guest appears at every store. Includes realistic party sizes (2-8), table numbers, seating sections (Main Dining, Window, Bar Counter, Patio, Private Room), VIP tiers, dietary notes, and randomized check totals.
- **Sales History**: 90 days of synthetic hourly sales data across 5 menu categories with realistic day-of-week and lunch/dinner variance. YoY comparisons use location-specific growth multipliers — some stores are up (SoHo +18.9%), others are down (Midtown -4.5%).
- **Weather**: Simulated per-location weather conditions (temperature, sky condition, patio open/closed status) that rotate between states on each simulation cycle.
- **Table Turn Durations**: Range from 35 minutes (bar quick bite) to 140 minutes (private room tasting menu), reflecting realistic dining pacing.

## How Cortex AI Works

The dashboard calls `SNOWFLAKE.CORTEX.COMPLETE('llama3.1-70b', ...)` with a structured prompt containing the current floor telemetry snapshot:

- Current occupancy % and seated guest count
- Weather conditions and patio status
- Table overstay bottlenecks (specific tables, party sizes, durations, tab amounts)
- Upcoming bookings and waitlist pressure

The AI returns a JSON array of 2-3 operational directives, each with a title, severity classification (CRITICAL/WARNING/OPPORTUNITY/SUCCESS), category (FLOOR/WEATHER/KITCHEN), contextual description, and a concrete action recommendation. The dashboard parses this JSON and renders color-coded action cards.

Results are cached for 45 seconds via `@st.cache_data(ttl=45)` to avoid redundant LLM calls. The "Re-Analyze Now" button clears this cache and forces a fresh evaluation.

## Filters & Controls

- **Store Location**: Filter all views by a specific location or view all locations aggregated.
- **Time Window**: Switch the sales chart between Today (Hourly), Last 7 Days, Last 30 Days, or Last 90 Days — independent of the AI and floor telemetry sections.
- **Simulate Floor Shifts**: Calls a Snowflake stored procedure that randomizes reservations, table assignments, weather conditions, and check totals to simulate live floor activity.
- **Refresh**: Clears all cached data and reloads the dashboard.
- **Re-Analyze Now**: Forces Cortex AI to re-evaluate the current floor state.

## Live Streaming

The KPI row and capacity sections use Streamlit's `@st.fragment(run_every="30s")` to auto-refresh every 30 seconds without full page reloads. The AI section refreshes on page load and on-demand via the Re-Analyze button.
