"""
NEA AMI — Batch CSV to Kafka Ingester
======================================
Reads nea_v2 batch output CSVs and produces to Kafka (same format as MQTT stream).
Use after: python nea_v2/simulator.py --mode batch --days N

Usage:
  python batch_to_kafka.py --input ../nea_v2/output/batch --days 7
  # or with env: CSV_DIR=../nea_v2/output/batch python batch_to_kafka.py
"""

import os
import sys
import json
import csv
import argparse
from pathlib import Path

from kafka import KafkaProducer

KAFKA_BOOT = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
T_READINGS = os.getenv("KAFKA_TOPIC_READINGS", "nea.meters.readings")
T_EVENTS   = os.getenv("KAFKA_TOPIC_EVENTS", "nea.meters.events")
CSV_DIR    = os.getenv("CSV_DIR", "")
BATCH_SIZE = 500


def _parse_bool(v):
    if v in ("", None): return False
    return str(v).lower() in ("true", "1", "yes")


def _ensure_npt_ts(ts):
    """Append +05:45 if timestamp has no timezone."""
    if not ts:
        return None
    s = str(ts).strip()
    if "+" in s or "Z" in s or s.endswith("NPT"):
        return s
    return f"{s}+05:45"


def csv_row_to_reading(row):
    """Convert CSV row (dict) to Kafka payload format (matches MQTT bridge)."""
    return {
        "timestamp_npt":  _ensure_npt_ts(row.get("timestamp_npt")),
        "time_slot":      int(row["time_slot"]) if row.get("time_slot") else None,
        "hour":           int(row["hour"]) if row.get("hour") else None,
        "weekday":        int(row["weekday"]) if row.get("weekday") else None,
        "is_saturday":    _parse_bool(row.get("is_saturday")),
        "meter_id":       row.get("meter_id"),
        "meter_serial":   row.get("meter_serial"),
        "consumer_id":    row.get("consumer_id"),
        "consumer_name":  row.get("consumer_name"),
        "consumer_category": row.get("consumer_category"),
        "consumer_subtype":  row.get("consumer_subtype"),
        "tariff_code":    row.get("tariff_code"),
        "phase":          row.get("phase"),
        "supply_level":   row.get("supply_level"),
        "dcs_id":         row.get("dcs_id"),
        "pss_id":         row.get("pss_id"),
        "feeder_id":      row.get("feeder_id"),
        "dtr_id":         row.get("dtr_id"),
        "dcu_id":         row.get("dcu_id"),
        "import_kwh":     float(row["import_kwh"]) if row.get("import_kwh") else None,
        "export_kwh":     float(row["export_kwh"]) if row.get("export_kwh") else None,
        "cumulative_kwh": float(row["cumulative_kwh"]) if row.get("cumulative_kwh") else None,
        "active_power_kw": float(row["active_power_kw"]) if row.get("active_power_kw") else None,
        "voltage_v":      float(row["voltage_v"]) if row.get("voltage_v") else None,
        "current_a":      float(row["current_a"]) if row.get("current_a") else None,
        "power_factor":   float(row["power_factor"]) if row.get("power_factor") else None,
        "frequency_hz":   float(row["frequency_hz"]) if row.get("frequency_hz") else None,
        "voltage_an":     float(row["voltage_an"]) if row.get("voltage_an") else None,
        "voltage_bn":     float(row["voltage_bn"]) if row.get("voltage_bn") else None,
        "voltage_cn":     float(row["voltage_cn"]) if row.get("voltage_cn") else None,
        "current_a_ph":   float(row["current_a_ph"]) if row.get("current_a_ph") else None,
        "current_b_ph":   float(row["current_b_ph"]) if row.get("current_b_ph") else None,
        "current_c_ph":   float(row["current_c_ph"]) if row.get("current_c_ph") else None,
        "is_outage":      _parse_bool(row.get("is_outage")),
        "is_comm_loss":   _parse_bool(row.get("is_comm_loss")),
        "is_voltage_event": _parse_bool(row.get("is_voltage_event")),
        "is_tamper_event":  _parse_bool(row.get("is_tamper_event")),
        "event_flags":    row.get("event_flags") or None,
        "gt_is_tampered": _parse_bool(row.get("gt_is_tampered")),
        "gt_tamper_bypass_pct": float(row["gt_tamper_bypass_pct"]) if row.get("gt_tamper_bypass_pct") else 0.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", "-i", default=CSV_DIR, help="Path to nea_v2 output/batch dir")
    ap.add_argument("--days", "-d", type=int, default=999, help="Max number of CSV files to ingest (default: all)")
    args = ap.parse_args()

    input_dir = Path(args.input or ".").resolve()
    if not input_dir.exists():
        print(f"Error: Input dir not found: {input_dir}")
        sys.exit(1)

    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOT,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
        acks="all",
        batch_size=32768,
        linger_ms=50,
    )
    print(f"Connected to Kafka {KAFKA_BOOT}")

    total = 0
    csv_files = sorted(input_dir.glob("nea_readings_*.csv"))
    if not csv_files:
        print(f"No nea_readings_*.csv files in {input_dir}")
        sys.exit(1)
    if args.days < 999:
        csv_files = csv_files[: args.days]

    for csv_path in csv_files:
        day_str = csv_path.stem.replace("nea_readings_", "")

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                payload = csv_row_to_reading(row)
                key = payload.get("feeder_id", "unknown")
                producer.send(T_READINGS, value=payload, key=key)
                total += 1

        producer.flush()
        print(f"  Ingested {day_str}: {total:,} rows so far")

    print(f"\nDone. Produced {total:,} readings to {T_READINGS}")


if __name__ == "__main__":
    main()
