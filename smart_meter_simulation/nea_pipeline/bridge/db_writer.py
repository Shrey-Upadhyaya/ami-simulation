"""
NEA AMI — Kafka → TimescaleDB Writer
======================================
Consumes from Kafka topics and batch-inserts into TimescaleDB.

Design:
  - Reads from nea.meters.readings and nea.meters.events
  - Buffers rows in memory (BATCH_SIZE or FLUSH_INTERVAL_SEC, whichever first)
  - Uses COPY for readings (fast bulk insert ~50k rows/sec)
  - Uses INSERT for events (lower volume, need conflict handling)
  - Commits Kafka offsets only after successful DB insert (at-least-once)
"""

import os, json, logging, time, threading, io
from datetime import datetime, timezone, timedelta

import psycopg2
import psycopg2.extras
from kafka import KafkaConsumer
from kafka.errors import KafkaError

# ─── Config ───────────────────────────────────────────────────────────────────
KAFKA_BOOT   = os.getenv("KAFKA_BOOTSTRAP",    "localhost:9092")
T_READINGS   = os.getenv("KAFKA_TOPIC_READINGS","nea.meters.readings")
T_EVENTS     = os.getenv("KAFKA_TOPIC_EVENTS",  "nea.meters.events")
GROUP_ID     = os.getenv("KAFKA_GROUP_ID",      "nea-db-writer-group")

DB_HOST      = os.getenv("DB_HOST",  "localhost")
DB_PORT      = int(os.getenv("DB_PORT", "5432"))
DB_NAME      = os.getenv("DB_NAME",  "nea_ami")
DB_USER      = os.getenv("DB_USER",  "nea_user")
DB_PASS      = os.getenv("DB_PASS",  "nea_secure_pass")

BATCH_SIZE   = int(os.getenv("BATCH_SIZE",         "500"))
FLUSH_SEC    = int(os.getenv("FLUSH_INTERVAL_SEC",  "5"))

NPT          = timezone(timedelta(hours=5, minutes=45))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
log = logging.getLogger("nea.db_writer")

# ─── DB Connection ────────────────────────────────────────────────────────────
def make_db():
    while True:
        try:
            conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                user=DB_USER, password=DB_PASS,
                connect_timeout=10,
            )
            conn.autocommit = False
            log.info(f"✅ Connected to TimescaleDB: {DB_HOST}/{DB_NAME}")
            return conn
        except Exception as e:
            log.warning(f"DB not ready ({e}), retrying in 5s...")
            time.sleep(5)

# ─── INSERT helpers ───────────────────────────────────────────────────────────

READING_COLS = [
    "time","time_slot","hour","weekday","is_saturday",
    "meter_id","meter_serial","consumer_id","consumer_category","consumer_subtype",
    "tariff_code","phase","supply_level",
    "dcs_id","pss_id","feeder_id","dtr_id","dcu_id",
    "import_kwh","export_kwh","cumulative_kwh",
    "active_power_kw","voltage_v","current_a","power_factor","frequency_hz",
    "voltage_an","voltage_bn","voltage_cn","current_a_ph","current_b_ph","current_c_ph",
    "quality_flag","is_outage","is_comm_loss","is_voltage_event","is_tamper_event",
    "event_flags","gt_is_tampered","gt_tamper_bypass_pct","kafka_offset",
]

def _to_reading_row(msg):
    p = msg.value
    return (
        p.get("timestamp_npt"),
        p.get("time_slot"),
        p.get("hour"),
        p.get("weekday"),
        p.get("is_saturday", False),
        p.get("meter_id"),
        p.get("meter_serial"),
        p.get("consumer_id"),
        p.get("consumer_category"),
        p.get("consumer_subtype"),
        p.get("tariff_code"),
        p.get("phase"),
        p.get("supply_level", "LV"),
        p.get("dcs_id"),
        p.get("pss_id"),
        p.get("feeder_id"),
        p.get("dtr_id"),
        p.get("dcu_id"),
        p.get("import_kwh"),
        p.get("export_kwh"),
        p.get("cumulative_kwh"),
        p.get("active_power_kw"),
        p.get("voltage_v"),
        p.get("current_a"),
        p.get("power_factor"),
        p.get("frequency_hz"),
        p.get("voltage_an"),
        p.get("voltage_bn"),
        p.get("voltage_cn"),
        p.get("current_a_ph"),
        p.get("current_b_ph"),
        p.get("current_c_ph"),
        "VALID" if not p.get("is_comm_loss") else "MISSING",
        p.get("is_outage", False),
        p.get("is_comm_loss", False),
        p.get("is_voltage_event", False),
        p.get("is_tamper_event", False),
        p.get("event_flags"),
        p.get("gt_is_tampered", False),
        p.get("gt_tamper_bypass_pct", 0.0),
        msg.offset,
    )

def flush_readings(cur, rows):
    """Use execute_values for fast batch insert."""
    sql = f"""
        INSERT INTO interval_readings ({','.join(READING_COLS)})
        VALUES %s
        ON CONFLICT DO NOTHING
    """
    psycopg2.extras.execute_values(cur, sql, rows, page_size=500)

def flush_events(cur, rows):
    """Insert meter events."""
    sql = """
        INSERT INTO meter_events
            (time, meter_id, meter_serial, consumer_category,
             feeder_id, dtr_id, dcs_id,
             event_category, event_code, event_description,
             severity, raw_payload)
        VALUES %s
        ON CONFLICT DO NOTHING
    """
    psycopg2.extras.execute_values(cur, sql, rows, page_size=200)

def _to_event_row(msg):
    p = msg.value
    flags = p.get("event_flags", "") or ""
    code  = flags.split("|")[0] if flags else "UNKNOWN"
    cat   = (
        "TAMPER"  if "TAMPER" in code or "COVER" in code or "MAGNETIC" in code or "REVERSAL" in code
        else "POWER"   if "OUTAGE" in code or "FAULT" in code
        else "QUALITY" if "VOLTAGE" in code
        else "COMM"
    )
    sev = "CRITICAL" if cat == "TAMPER" else "WARNING"
    return (
        p.get("timestamp_npt"),
        p.get("meter_id"),
        p.get("meter_serial"),
        p.get("consumer_category"),
        p.get("feeder_id"),
        p.get("dtr_id"),
        p.get("dcs_id"),
        cat, code, flags, sev,
        json.dumps(p),
    )

# ─── Main writer loop ─────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("  NEA AMI — Kafka → TimescaleDB Writer")
    log.info(f"  Kafka:  {KAFKA_BOOT}")
    log.info(f"  Topics: {T_READINGS} | {T_EVENTS}")
    log.info(f"  DB:     {DB_HOST}/{DB_NAME}")
    log.info(f"  Batch:  {BATCH_SIZE} rows / {FLUSH_SEC}s flush")
    log.info("=" * 60)

    conn = make_db()

    consumer = KafkaConsumer(
        T_READINGS, T_EVENTS,
        bootstrap_servers=KAFKA_BOOT,
        group_id=GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=False,       # manual commit after DB write
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        max_poll_records=BATCH_SIZE,
        fetch_max_bytes=52428800,       # 50MB fetch
        session_timeout_ms=30000,
        heartbeat_interval_ms=10000,
    )
    log.info("✅ Kafka consumer ready")

    reading_buf, event_buf = [], []
    last_flush  = time.time()
    total_written = 0

    def _flush():
        nonlocal total_written, last_flush
        if not reading_buf and not event_buf:
            return
        try:
            with conn.cursor() as cur:
                if reading_buf:
                    flush_readings(cur, reading_buf)
                    log.info(f"  💾 Flushed {len(reading_buf)} readings to TimescaleDB")
                if event_buf:
                    flush_events(cur, event_buf)
                    log.info(f"  📋 Flushed {len(event_buf)} events to TimescaleDB")
            conn.commit()
            consumer.commit()
            total_written += len(reading_buf) + len(event_buf)
            reading_buf.clear()
            event_buf.clear()
            last_flush = time.time()
        except Exception as e:
            conn.rollback()
            log.error(f"DB flush error: {e}", exc_info=True)
            # Re-connect on connection errors
            if conn.closed:
                conn = make_db()

    while True:
        try:
            records = consumer.poll(timeout_ms=1000)

            for tp, messages in records.items():
                for msg in messages:
                    if tp.topic == T_READINGS:
                        p = msg.value
                        # Only store events-containing readings separately
                        if p.get("event_flags"):
                            event_buf.append(_to_event_row(msg))
                        reading_buf.append(_to_reading_row(msg))
                    elif tp.topic == T_EVENTS:
                        event_buf.append(_to_event_row(msg))

            # Flush if batch full OR timer expired
            should_flush = (
                len(reading_buf) >= BATCH_SIZE
                or (time.time() - last_flush) >= FLUSH_SEC
            )
            if should_flush:
                _flush()

        except KafkaError as e:
            log.error(f"Kafka error: {e}")
            time.sleep(2)
        except KeyboardInterrupt:
            log.info("Shutting down writer...")
            _flush()
            break

if __name__ == "__main__":
    main()
