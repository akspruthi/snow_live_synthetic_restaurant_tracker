-- =====================================================================
-- Snowflake Setup Script: Read-Only Service User for Public Streamlit App
-- Database: RESTAURANT_STREAM_DEMO
-- =====================================================================

-- 1. Create a dedicated read-only role
CREATE ROLE IF NOT EXISTS OSTERIA_APP_PUBLIC_ROLE;

-- 2. Grant usage on warehouse, database, and schema
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE OSTERIA_APP_PUBLIC_ROLE;
GRANT USAGE ON DATABASE RESTAURANT_STREAM_DEMO TO ROLE OSTERIA_APP_PUBLIC_ROLE;
GRANT USAGE ON SCHEMA RESTAURANT_STREAM_DEMO.PUBLIC TO ROLE OSTERIA_APP_PUBLIC_ROLE;

-- 3. Grant SELECT privileges on all current and future tables and views
GRANT SELECT ON ALL TABLES IN SCHEMA RESTAURANT_STREAM_DEMO.PUBLIC TO ROLE OSTERIA_APP_PUBLIC_ROLE;
GRANT SELECT ON ALL VIEWS IN SCHEMA RESTAURANT_STREAM_DEMO.PUBLIC TO ROLE OSTERIA_APP_PUBLIC_ROLE;
GRANT SELECT ON FUTURE TABLES IN SCHEMA RESTAURANT_STREAM_DEMO.PUBLIC TO ROLE OSTERIA_APP_PUBLIC_ROLE;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA RESTAURANT_STREAM_DEMO.PUBLIC TO ROLE OSTERIA_APP_PUBLIC_ROLE;

-- 4. Grant USAGE on stored procedures (for on-demand simulation)
GRANT USAGE ON ALL PROCEDURES IN SCHEMA RESTAURANT_STREAM_DEMO.PUBLIC TO ROLE OSTERIA_APP_PUBLIC_ROLE;

-- 5. Create the dedicated service user
CREATE USER IF NOT EXISTS OSTERIA_APP_SERVICE_USER
    PASSWORD = 'OsteriaBella2026Secure!'
    DEFAULT_ROLE = OSTERIA_APP_PUBLIC_ROLE
    DEFAULT_WAREHOUSE = COMPUTE_WH
    MUST_CHANGE_PASSWORD = FALSE
    COMMENT = 'Read-only service user for public Streamlit Community Cloud dashboard';

-- 6. Assign the role to the service user
GRANT ROLE OSTERIA_APP_PUBLIC_ROLE TO USER OSTERIA_APP_SERVICE_USER;

-- =====================================================================
-- Streamlit Community Cloud Secrets (Paste into share.streamlit.io):
-- =====================================================================
-- [connections.snowflake]
-- account = "xm06262"
-- user = "OSTERIA_APP_SERVICE_USER"
-- password = "OsteriaBella2026Secure!"
-- role = "OSTERIA_APP_PUBLIC_ROLE"
-- warehouse = "COMPUTE_WH"
-- database = "RESTAURANT_STREAM_DEMO"
-- schema = "PUBLIC"
-- =====================================================================
