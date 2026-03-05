"""Configuration for AMI Simulation Platform."""

import os

# MQTT (Mosquitto)
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "31883"))
MQTT_TOPIC_METERS = "ami/meters/{meter_id}/readings"
MQTT_TOPIC_EVENTS = "ami/meters/{meter_id}/events"

# InfluxDB
INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "ami-influx-token")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "ami-org")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "meter_readings")

# PostgreSQL
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "ami_db")
POSTGRES_USER = os.getenv("POSTGRES_USER", "ami_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "ami_password")
POSTGRES_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
