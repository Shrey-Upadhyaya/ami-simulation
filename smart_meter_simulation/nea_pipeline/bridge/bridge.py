"""
NEA AMI — MQTT → Kafka Bridge
==============================
Subscribes to all NEA MQTT topics on Mosquitto.
Deserializes, enriches, and routes messages to the correct Kafka topic.

MQTT topic → Kafka topic routing:
  nea/readings/#   →  nea.meters.readings
  nea/events/#     →  nea.meters.events  (+ nea.meters.alerts if CRITICAL)
  nea/heartbeat/#  →  nea.dcus.heartbeat

Message flow per reading:
  1. MQTT message arrives (JSON payload)
  2. Parse + validate JSON
  3. Extract routing key (feeder_id for readings, event_category for events)
  4. Add pipeline metadata (bridge_id, ingested_at)
  5. Produce to Kafka with partition key
  6. Log throughput metrics every 1000 messages
"""

import os
import json
import logging
import time
import threading
from datetime import datetime, timezone, timedelta

import paho.mqtt.client as mqtt
from kafka import KafkaProducer
from kafka.errors import KafkaError

# ─── Config from environment ──────────────────────────────────────────────────
MQTT_HOST    = os.getenv("MQTT_HOST",    "localhost")
MQTT_PORT    = int(os.getenv("MQTT_PORT", "1883"))
MQTT_ID      = os.getenv("MQTT_CLIENT_ID", "nea-bridge-01")
MQTT_KEEP    = int(os.getenv("MQTT_KEEPALIVE", "60"))

KAFKA_BOOT   = os.getenv("KAFKA_BOOTSTRAP",       "localhost:9092")
T_READINGS   = os.getenv("KAFKA_TOPIC_READINGS",   "nea.meters.readings")
T_EVENTS     = os.getenv("KAFKA_TOPIC_EVENTS",     "nea.meters.events")
T_ALERTS     = os.getenv("KAFKA_TOPIC_ALERTS",     "nea.meters.alerts")
T_HEARTBEAT  = os.getenv("KAFKA_TOPIC_HEARTBEAT",  "nea.dcus.heartbeat")

LOG_LEVEL    = os.getenv("LOG_LEVEL", "INFO")
BRIDGE_ID    = "bridge-01"
NPT          = timezone(timedelta(hours=5, minutes=45))

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
log = logging.getLogger("nea.bridge")

# ─── Metrics ──────────────────────────────────────────────────────────────────
class Metrics:
    def __init__(self):
        self.received   = 0
        self.produced   = 0
        self.errors     = 0
        self.alerts_fwd = 0
        self._lock      = threading.Lock()
        self._start     = time.time()

    def inc(self, field, n=1):
        with self._lock:
            setattr(self, field, getattr(self, field) + n)

    def report(self):
        elapsed = max(1, time.time() - self._start)
        log.info(
            f"[METRICS] received={self.received} produced={self.produced} "
            f"errors={self.errors} alerts={self.alerts_fwd} "
            f"rate={self.produced/elapsed:.1f} msg/s"
        )

metrics = Metrics()

# ─── Kafka Producer ───────────────────────────────────────────────────────────
def make_producer():
    while True:
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOT,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                # Reliability settings
                acks="all",             # wait for all ISR replicas
                retries=5,
                retry_backoff_ms=500,
                # Throughput settings
                linger_ms=10,           # batch for 10ms before send
                batch_size=32768,       # 32KB batch
                compression_type="lz4",
                # Buffer
                buffer_memory=33554432, # 32MB send buffer
            )
            log.info(f"✅ Kafka producer connected to {KAFKA_BOOT}")
            return producer
        except Exception as e:
            log.warning(f"Kafka not ready ({e}), retrying in 5s...")
            time.sleep(5)

producer = make_producer()

# ─── Message routing logic ────────────────────────────────────────────────────

def _enrich(payload: dict) -> dict:
    """Add bridge metadata to every message."""
    payload["_bridge_id"]    = BRIDGE_ID
    payload["_ingested_at"]  = datetime.now(NPT).isoformat()
    return payload

def _partition_key(payload: dict, msg_type: str) -> str:
    """
    Partition keys ensure related data lands on same partition.
    Readings:   feeder_id  → all readings from one feeder together
    Events:     meter_id   → all events for one meter together
    Heartbeat:  dcu_id     → DCU telemetry grouped
    """
    if msg_type == "reading":
        return payload.get("feeder_id", "unknown")
    elif msg_type == "event":
        return payload.get("meter_id", "unknown")
    elif msg_type == "heartbeat":
        return payload.get("dcu_id", "unknown")
    return "default"

def _is_critical_alert(payload: dict) -> bool:
    """Determine if event should also go to the alerts topic."""
    critical_codes = {
        "COVER_OPEN", "MAGNETIC_TAMPER", "CURRENT_REVERSAL",
        "NEUTRAL_DISTURBANCE", "CABLE_FAULT", "DTR_FAILURE",
    }
    return (
        payload.get("severity") == "CRITICAL"
        or payload.get("event_code", "") in critical_codes
        or payload.get("event_category") == "TAMPER"
    )

def route_message(mqtt_topic: str, payload: dict):
    """Core routing function: MQTT topic → Kafka topic."""
    try:
        _enrich(payload)

        # ── nea/readings/{feeder_id}/{meter_serial} ───────────────────────
        if mqtt_topic.startswith("nea/readings/"):
            key = _partition_key(payload, "reading")
            producer.send(T_READINGS, value=payload, key=key)
            metrics.inc("produced")

        # ── nea/events/{feeder_id}/{meter_serial} ─────────────────────────
        elif mqtt_topic.startswith("nea/events/"):
            key = _partition_key(payload, "event")
            producer.send(T_EVENTS, value=payload, key=key)
            metrics.inc("produced")

            # Duplicate critical events to alerts topic (fast consumer)
            if _is_critical_alert(payload):
                producer.send(T_ALERTS, value=payload, key=key)
                metrics.inc("alerts_fwd")
                log.warning(
                    f"🚨 ALERT forwarded: {payload.get('event_code')} "
                    f"meter={payload.get('meter_serial')} "
                    f"feeder={payload.get('feeder_id')}"
                )

        # ── nea/heartbeat/{dcu_id} ────────────────────────────────────────
        elif mqtt_topic.startswith("nea/heartbeat/"):
            key = _partition_key(payload, "heartbeat")
            producer.send(T_HEARTBEAT, value=payload, key=key)
            metrics.inc("produced")

        else:
            log.debug(f"Unrouted topic: {mqtt_topic}")

    except KafkaError as e:
        metrics.inc("errors")
        log.error(f"Kafka produce error on {mqtt_topic}: {e}")
    except Exception as e:
        metrics.inc("errors")
        log.error(f"Routing error on {mqtt_topic}: {e}", exc_info=True)

# ─── MQTT Callbacks ───────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        log.info(f"✅ Connected to Mosquitto at {MQTT_HOST}:{MQTT_PORT}")
        # Subscribe to all NEA topics
        subscriptions = [
            ("nea/readings/#",  1),   # QoS 1 — at-least-once for readings
            ("nea/events/#",    2),   # QoS 2 — exactly-once for events (critical)
            ("nea/heartbeat/#", 1),   # QoS 1 for heartbeats
        ]
        client.subscribe(subscriptions)
        for topic, qos in subscriptions:
            log.info(f"  📡 Subscribed: {topic} (QoS {qos})")
    else:
        log.error(f"MQTT connect failed: reason_code={reason_code}")

def on_disconnect(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        log.warning(f"⚠️  MQTT disconnected unexpectedly (rc={reason_code}), will auto-reconnect")

def on_message(client, userdata, msg):
    metrics.inc("received")

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning(f"Invalid JSON on {msg.topic}: {e}")
        metrics.inc("errors")
        return

    route_message(msg.topic, payload)

    # Periodic metrics report
    if metrics.received % 1000 == 0:
        metrics.report()

def on_subscribe(client, userdata, mid, reason_codes, properties):
    log.debug(f"Subscription confirmed mid={mid}")

# ─── Metrics reporter thread ──────────────────────────────────────────────────

def _metrics_thread():
    while True:
        time.sleep(60)
        metrics.report()

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("  NEA AMI — MQTT → Kafka Bridge")
    log.info(f"  MQTT:  {MQTT_HOST}:{MQTT_PORT}")
    log.info(f"  Kafka: {KAFKA_BOOT}")
    log.info(f"  Topics: {T_READINGS} | {T_EVENTS} | {T_ALERTS} | {T_HEARTBEAT}")
    log.info("=" * 60)

    # Start metrics thread
    t = threading.Thread(target=_metrics_thread, daemon=True)
    t.start()

    # Build MQTT client (paho v2 API)
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=MQTT_ID,
        clean_session=True,
    )
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message
    client.on_subscribe  = on_subscribe

    # Reconnect settings
    client.reconnect_delay_set(min_delay=2, max_delay=30)

    # Connect with retry
    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=MQTT_KEEP)
            break
        except Exception as e:
            log.warning(f"MQTT not ready ({e}), retrying in 5s...")
            time.sleep(5)

    log.info("🚀 Bridge running — waiting for messages...")
    client.loop_forever()

if __name__ == "__main__":
    main()
