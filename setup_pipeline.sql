# ==============================================================================
# REAL-TIME RESTAURANT POS & DELIVERY TRACKER
# Snowflake Ingestion Pipeline (Snowpipe + Stored Procedure + Analytics Views)
# Database: RESTAURANT_STREAM_DEMO | Schema: PUBLIC
# ==============================================================================

-- 1. Create Database and Schema
CREATE DATABASE IF NOT EXISTS RESTAURANT_STREAM_DEMO;
USE DATABASE RESTAURANT_STREAM_DEMO;
CREATE SCHEMA IF NOT EXISTS PUBLIC;
USE SCHEMA PUBLIC;

-- 2. Create JSON File Format
CREATE OR REPLACE FILE FORMAT JSON_FF
  TYPE = 'JSON'
  STRIP_OUTER_ARRAY = TRUE;

-- 3. Create Landing Internal Stage
CREATE OR REPLACE STAGE ORDERS_STAGE
  FILE_FORMAT = JSON_FF;

-- 4. Create Bronze Landing Table (Raw Variant)
CREATE OR REPLACE TABLE RAW_ORDERS (
  RAW_PAYLOAD VARIANT,
  INGESTED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  SOURCE_FILE_NAME STRING,
  FILE_ROW_NUMBER NUMBER
);

-- 5. Create Snowpipe Definition
CREATE OR REPLACE PIPE ORDERS_PIPE
  AUTO_INGEST = FALSE
AS
  COPY INTO RAW_ORDERS (RAW_PAYLOAD, INGESTED_AT, SOURCE_FILE_NAME, FILE_ROW_NUMBER)
  FROM (
    SELECT 
      $1 AS RAW_PAYLOAD,
      CURRENT_TIMESTAMP() AS INGESTED_AT,
      METADATA$FILENAME AS SOURCE_FILE_NAME,
      METADATA$FILE_ROW_NUMBER AS FILE_ROW_NUMBER
    FROM @ORDERS_STAGE
  );

-- 6. Create Silver Enriched View (Flattened)
CREATE OR REPLACE VIEW V_ORDERS_ENRICHED AS
SELECT
  RAW_PAYLOAD:order_id::STRING AS ORDER_ID,
  RAW_PAYLOAD:restaurant_id::STRING AS RESTAURANT_ID,
  RAW_PAYLOAD:restaurant_name::STRING AS RESTAURANT_NAME,
  RAW_PAYLOAD:cuisine::STRING AS CUISINE,
  RAW_PAYLOAD:customer_name::STRING AS CUSTOMER_NAME,
  RAW_PAYLOAD:subtotal::NUMBER(10,2) AS SUBTOTAL,
  RAW_PAYLOAD:tax::NUMBER(10,2) AS TAX,
  RAW_PAYLOAD:tip::NUMBER(10,2) AS TIP,
  RAW_PAYLOAD:delivery_fee::NUMBER(10,2) AS DELIVERY_FEE,
  (RAW_PAYLOAD:subtotal::NUMBER(10,2) + RAW_PAYLOAD:tax::NUMBER(10,2) + RAW_PAYLOAD:tip::NUMBER(10,2) + RAW_PAYLOAD:delivery_fee::NUMBER(10,2)) AS TOTAL_AMOUNT,
  RAW_PAYLOAD:item_count::NUMBER AS ITEM_COUNT,
  RAW_PAYLOAD:items::ARRAY AS ITEMS,
  RAW_PAYLOAD:delivery_status::STRING AS DELIVERY_STATUS,
  RAW_PAYLOAD:delivery_lat::FLOAT AS DELIVERY_LAT,
  RAW_PAYLOAD:delivery_lon::FLOAT AS DELIVERY_LON,
  RAW_PAYLOAD:customer_notes::STRING AS CUSTOMER_NOTES,
  RAW_PAYLOAD:order_timestamp::TIMESTAMP_NTZ AS ORDER_TIMESTAMP,
  INGESTED_AT,
  SOURCE_FILE_NAME
FROM RAW_ORDERS;

-- 7. Create Gold Real-Time KPI Metrics View
CREATE OR REPLACE VIEW V_REALTIME_METRICS AS
SELECT
  COUNT(*) AS TOTAL_ORDERS,
  COALESCE(SUM(TOTAL_AMOUNT), 0) AS TOTAL_GMV,
  COALESCE(AVG(TOTAL_AMOUNT), 0) AS AVG_ORDER_VALUE,
  COALESCE(AVG(TIP), 0) AS AVG_TIP,
  COUNT(CASE WHEN DELIVERY_STATUS = 'PREPARING' THEN 1 END) AS ORDERS_PREPARING,
  COUNT(CASE WHEN DELIVERY_STATUS = 'OUT_FOR_DELIVERY' THEN 1 END) AS ORDERS_IN_TRANSIT,
  COUNT(CASE WHEN DELIVERY_STATUS = 'DELIVERED' THEN 1 END) AS ORDERS_DELIVERED,
  MAX(INGESTED_AT) AS LAST_INGESTION_TIME
FROM V_ORDERS_ENRICHED;

-- 8. Python Synthetic Order Generator Stored Procedure
CREATE OR REPLACE PROCEDURE SP_GENERATE_RESTAURANT_ORDERS(BATCH_SIZE INT)
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'generate_orders'
AS
$$
import json
import random
import time
import uuid
import tempfile
import os
from datetime import datetime, timezone

def generate_orders(session, batch_size):
    restaurants = [
        {"id": "REST_001", "name": "Bella Italia Trattoria", "cuisine": "Italian", "base_lat": 40.7580, "base_lon": -73.9855},
        {"id": "REST_002", "name": "Tokyo Express Ramen & Sushi", "cuisine": "Japanese", "base_lat": 40.7282, "base_lon": -73.9942},
        {"id": "REST_003", "name": "Taqueria El Sol", "cuisine": "Mexican", "base_lat": 40.7128, "base_lon": -74.0060},
        {"id": "REST_004", "name": "Smash Burger Works", "cuisine": "American", "base_lat": 40.7484, "base_lon": -73.9857},
        {"id": "REST_005", "name": "Taj Mahal Indian Kitchen", "cuisine": "Indian", "base_lat": 40.7614, "base_lon": -73.9776},
        {"id": "REST_006", "name": "Green Garden Vegan Bistro", "cuisine": "Healthy", "base_lat": 40.7308, "base_lon": -73.9973}
    ]

    menu_by_cuisine = {
        "Italian": [("Truffle Tagliatelle", 24.50), ("Margherita Pizza", 18.00), ("Tiramisu", 9.50), ("Garlic Focaccia", 6.00)],
        "Japanese": [("Tonkotsu Spicy Ramen", 17.50), ("Salmon Nigiri (4pc)", 14.00), ("Pork Gyoza", 8.00), ("Matcha Mochi", 6.50)],
        "Mexican": [("Birria Tacos (3pc)", 16.00), ("Guacamole & Chips", 10.50), ("Carne Asada Burrito", 15.00), ("Churros", 7.00)],
        "American": [("Double Bacon Cheeseburger", 16.50), ("Truffle Fries", 7.50), ("Crispy Chicken Sandwich", 14.00), ("Oreo Milkshake", 6.50)],
        "Indian": [("Butter Chicken", 19.00), ("Garlic Naan", 4.50), ("Paneer Tikka Masala", 17.50), ("Mango Lassi", 5.00)],
        "Healthy": [("Mediterranean Quinoa Bowl", 15.50), ("Avocado Green Wrap", 13.00), ("Cold Pressed Green Juice", 8.00)]
    }

    statuses = ["RECEIVED", "PREPARING", "OUT_FOR_DELIVERY", "DELIVERED"]
    notes = [
        "Please ring the doorbell",
        "Leave at front door",
        "Extra napkins and hot sauce please!",
        "Allergic to peanuts - please confirm",
        "Building code is #4829",
        "Call when outside",
        None
    ]
    
    first_names = ["Emma", "Liam", "Olivia", "Noah", "Ava", "Lucas", "Sophia", "Ethan", "Isabella", "Aiden", "Mia", "Oliver"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", "Garcia", "Rodriguez", "Martinez"]

    orders = []
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    for _ in range(batch_size):
        rest = random.choice(restaurants)
        cuisine = rest["cuisine"]
        menu = menu_by_cuisine[cuisine]
        
        num_items = random.randint(1, 4)
        items_ordered = []
        subtotal = 0.0
        for _ in range(num_items):
            item_name, item_price = random.choice(menu)
            qty = random.randint(1, 2)
            items_ordered.append({"item_name": item_name, "price": item_price, "qty": qty})
            subtotal += item_price * qty

        tax = round(subtotal * 0.08875, 2)
        tip = round(random.choice([0.0, 3.0, 5.0, 7.5, 10.0, subtotal * 0.18, subtotal * 0.20]), 2)
        delivery_fee = 2.99 if subtotal < 35.0 else 0.0

        lat_jitter = random.uniform(-0.025, 0.025)
        lon_jitter = random.uniform(-0.025, 0.025)

        order = {
            "order_id": f"ORD-{uuid.uuid4().hex[:8].upper()}",
            "restaurant_id": rest["id"],
            "restaurant_name": rest["name"],
            "cuisine": cuisine,
            "customer_name": f"{random.choice(first_names)} {random.choice(last_names)}",
            "items": items_ordered,
            "item_count": sum(i["qty"] for i in items_ordered),
            "subtotal": round(subtotal, 2),
            "tax": tax,
            "tip": tip,
            "delivery_fee": delivery_fee,
            "delivery_status": random.choice(statuses),
            "delivery_lat": round(rest["base_lat"] + lat_jitter, 6),
            "delivery_lon": round(rest["base_lon"] + lon_jitter, 6),
            "customer_notes": random.choice(notes),
            "order_timestamp": now_iso
        }
        orders.append(order)

    json_data = json.dumps(orders)
    file_name = f"orders_batch_{int(time.time()*1000)}.json"

    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as temp_file:
        temp_file.write(json_data)
        temp_path = temp_file.name

    try:
        session.file.put(temp_path, "@RESTAURANT_STREAM_DEMO.PUBLIC.ORDERS_STAGE", auto_compress=False, overwrite=True)
        session.sql("""
            COPY INTO RESTAURANT_STREAM_DEMO.PUBLIC.RAW_ORDERS (RAW_PAYLOAD, INGESTED_AT, SOURCE_FILE_NAME, FILE_ROW_NUMBER)
            FROM (
              SELECT 
                $1 AS RAW_PAYLOAD,
                CURRENT_TIMESTAMP() AS INGESTED_AT,
                METADATA$FILENAME AS SOURCE_FILE_NAME,
                METADATA$FILE_ROW_NUMBER AS FILE_ROW_NUMBER
              FROM @RESTAURANT_STREAM_DEMO.PUBLIC.ORDERS_STAGE
            )
        """).collect()
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return f"Successfully generated and ingested {batch_size} orders into RAW_ORDERS."
$$;

-- 9. Scheduled Task (Runs every 1 minute)
CREATE OR REPLACE TASK TASK_GENERATE_RESTAURANT_ORDERS
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = '1 MINUTE'
AS
  CALL SP_GENERATE_RESTAURANT_ORDERS(15);

-- To resume task:
-- ALTER TASK TASK_GENERATE_RESTAURANT_ORDERS RESUME;

-- To suspend task when demo is done:
-- ALTER TASK TASK_GENERATE_RESTAURANT_ORDERS SUSPEND;
