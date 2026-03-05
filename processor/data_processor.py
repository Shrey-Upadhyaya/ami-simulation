"""
AMI Data Processor - Consumes MQTT meter readings and writes to InfluxDB + PostgreSQL.

Flow: MQTT (ami/meters/+/readings) -> InfluxDB (time-series) + PostgreSQL (daily aggregates)
"""

import json
import sys
from datetime import datetime, date
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
from psycopg2.extras import execute_values
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
import paho.mqtt.client as mqtt

from config import (
    MQTT_BROKER,
    MQTT_PORT,
    INFLUXDB_URL,
    INFLUXDB_TOKEN,
    INFLUXDB_ORG,
    INFLUXDB_BUCKET,
    POSTGRES_URL,
)


def get_influx_client():
    return InfluxDBClient(
        url=INFLUXDB_URL,
        token=INFLUXDB_TOKEN,
        org=INFLUXDB_ORG,
    )


def get_pg_conn():
    return psycopg2.connect(POSTGRES_URL)


def write_to_influx(point: Point):
    """Write a single point to InfluxDB."""
    with get_influx_client() as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)
        write_api.write(bucket=INFLUXDB_BUCKET, record=point)


def upsert_daily_reading(meter_id: str, kwh: float, conn):
    """Upsert daily aggregate in PostgreSQL."""
    today = date.today()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO daily_readings (meter_id, reading_date, total_kwh, peak_kwh, off_peak_kwh)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (meter_id, reading_date)
            DO UPDATE SET total_kwh = daily_readings.total_kwh + EXCLUDED.total_kwh,
                          peak_kwh = daily_readings.peak_kwh + EXCLUDED.peak_kwh,
                          off_peak_kwh = daily_readings.off_peak_kwh + EXCLUDED.off_peak_kwh
        """, (meter_id, today, kwh, kwh * 0.6, kwh * 0.4))
    conn.commit()


def ensure_customer_exists(meter_id: str, conn):
    """Ensure customer record exists for meter (for demo)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customers (meter_id, customer_name, address, tariff_id) VALUES (%s, %s, %s, 1) ON CONFLICT (meter_id) DO NOTHING",
            (meter_id, f"Customer {meter_id}", f"Address for {meter_id}"),
        )
    conn.commit()


def on_message(client, userdata, msg):
    """Handle incoming MQTT message: write to InfluxDB and PostgreSQL."""
    try:
        data = json.loads(msg.payload.decode())
        meter_id = data.get("meter_id")
        kwh = float(data.get("kwh", 0))
        ts = data.get("timestamp", datetime.utcnow().isoformat())

        # InfluxDB - time-series point
        point = (
            Point("meter_reading")
            .tag("meter_id", meter_id)
            .field("kwh", kwh)
            .field("kvarh", float(data.get("kvarh", 0)))
            .field("voltage", float(data.get("voltage", 220)))
            .field("power_factor", float(data.get("power_factor", 1)))
            .time(datetime.fromisoformat(ts.replace("Z", "+00:00")))
        )
        write_to_influx(point)

        # PostgreSQL - daily aggregates
        pg_conn = userdata["pg_conn"]
        ensure_customer_exists(meter_id, pg_conn)
        upsert_daily_reading(meter_id, kwh, pg_conn)

        print(f"Processed: {meter_id} -> {kwh} kWh")
    except Exception as e:
        print(f"Error processing message: {e}")


def run_processor():
    pg_conn = get_pg_conn()
    client = mqtt.Client(client_id="ami-data-processor")
    client.user_data_set({"pg_conn": pg_conn})
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.subscribe("ami/meters/+/readings", qos=1)
    print("Data processor started. Subscribed to ami/meters/+/readings")
    client.loop_forever()


if __name__ == "__main__":
    run_processor()
