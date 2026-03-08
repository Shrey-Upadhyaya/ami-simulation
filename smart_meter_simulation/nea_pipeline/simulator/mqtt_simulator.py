"""
NEA AMI — MQTT Simulator
=========================
Wraps the nea_v2 smart meter simulator to publish readings via MQTT
instead of writing to CSV files.

MQTT topic structure:
  nea/readings/{feeder_id}/{meter_serial}   ← every 15-min interval
  nea/events/{feeder_id}/{meter_serial}     ← when event_flags present
  nea/heartbeat/{dcu_id}                   ← every 5 min per DCU

DCU heartbeat simulates what a real DCU would report:
  - connected_meters count
  - signal_strength_dbm (random, per DCU)
  - status: ONLINE
  - uptime_seconds

Speed factor (SIM_SPEED=60):
  60x realtime → 1 real second = 15 simulated minutes
  Each tick publishes all 1000 meter readings via MQTT
"""

import os, sys, json, time, logging, random, threading
from datetime import datetime, timezone, timedelta

import paho.mqtt.client as mqtt

# ── Pull in nea_v2 modules ────────────────────────────────────────────────────
sys.path.insert(0, "/app")
from config.topology     import DOMESTIC_TYPES, COMMERCIAL_TYPES
from config.load_profiles import LOAD_PROFILES, SEASON_MULT, WEEKDAY_MOD, ANOMALY
from core.infrastructure import build_infrastructure
from core.generator      import generate_reading

# ─── Config ───────────────────────────────────────────────────────────────────
MQTT_HOST   = os.getenv("MQTT_HOST",       "localhost")
MQTT_PORT   = int(os.getenv("MQTT_PORT",   "1883"))
MQTT_ID     = os.getenv("MQTT_CLIENT_ID",  "nea-simulator-dcs-01")
MQTT_QOS    = int(os.getenv("MQTT_QOS",    "1"))
SIM_SPEED   = float(os.getenv("SIM_SPEED", "60"))
SIM_METERS  = int(os.getenv("SIM_METERS",  "1000"))
SIM_SEED    = int(os.getenv("SIM_SEED",    "42"))

NPT         = timezone(timedelta(hours=5, minutes=45))
SLEEP_S     = (15 * 60) / SIM_SPEED      # seconds between ticks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
log = logging.getLogger("nea.simulator")

# ─── Outage manager (inline) ──────────────────────────────────────────────────
class OutageManager:
    def __init__(self, dtr_ids):
        self.dtr_ids = dtr_ids
        self.active  = {}
        self._prob   = 0.04 / 96

    def tick(self, dt):
        expired = [d for d, v in self.active.items() if v["end"] <= dt]
        for d in expired: del self.active[d]
        for dtr in self.dtr_ids:
            if dtr not in self.active and random.random() < self._prob:
                dur  = random.randint(15, 480)
                kind = random.choice(["CABLE_FAULT","TREE_CONTACT","FUSE_BLOW",
                                      "DTR_FAILURE","ANIMAL_CONTACT"])
                self.active[dtr] = {
                    "end":  dt + timedelta(minutes=dur),
                    "type": kind
                }
        return {d: v["type"] for d, v in self.active.items()}

# ─── MQTT client ──────────────────────────────────────────────────────────────
connected = threading.Event()

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        log.info(f"✅ Connected to Mosquitto {MQTT_HOST}:{MQTT_PORT}")
        connected.set()
    else:
        log.error(f"MQTT connect failed: rc={reason_code}")

def on_disconnect(client, userdata, flags, reason_code, properties):
    connected.clear()
    if reason_code != 0:
        log.warning(f"MQTT disconnected (rc={reason_code}), reconnecting...")

def make_mqtt_client():
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=MQTT_ID,
        clean_session=True,
    )
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=2, max_delay=30)

    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_start()
            connected.wait(timeout=15)
            if connected.is_set():
                return client
        except Exception as e:
            log.warning(f"Mosquitto not ready ({e}), retrying in 5s...")
            time.sleep(5)

# ─── Heartbeat publisher ──────────────────────────────────────────────────────
def _heartbeat_loop(client, dcus):
    """Publish DCU heartbeat every 5 minutes (every 5 ticks at 60x speed)."""
    interval = max(5.0, SLEEP_S * 5)
    dcu_uptime = {d["dcu_id"]: 0 for d in dcus}
    while True:
        time.sleep(interval)
        for dcu in dcus:
            dcu_uptime[dcu["dcu_id"]] += int(interval)
            hb = {
                "dcu_id":            dcu["dcu_id"],
                "dcu_serial":        dcu["dcu_serial"],
                "dtr_id":            dcu["dtr_id"],
                "feeder_id":         dcu.get("feeder_id", ""),
                "pss_id":            dcu["pss_id"],
                "dcs_id":            dcu["dcs_id"],
                "status":            "ONLINE",
                "connected_meters":  dcu["connected_meters"],
                "signal_strength_dbm": round(random.uniform(-90, -55), 1),
                "packet_loss_pct":   round(random.uniform(0, 3.5), 2),
                "uptime_seconds":    dcu_uptime[dcu["dcu_id"]],
                "timestamp_npt":     datetime.now(NPT).isoformat(),
            }
            topic = f"nea/heartbeat/{dcu['dcu_id']}"
            client.publish(topic, json.dumps(hb), qos=1)

# ─── Main simulation loop ─────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("  NEA AMI MQTT Simulator")
    log.info(f"  Speed: {SIM_SPEED}x  |  Tick interval: {SLEEP_S:.2f}s")
    log.info(f"  Meters: {SIM_METERS}  |  MQTT: {MQTT_HOST}:{MQTT_PORT}")
    log.info("=" * 60)

    # Build infrastructure
    log.info("🏗️  Building meter registry...")
    meters, dtrs, dcus = build_infrastructure(seed=SIM_SEED)
    log.info(f"   {len(meters)} meters | {len(dtrs)} DTRs | {len(dcus)} DCUs")

    # MQTT
    client = make_mqtt_client()

    # Start heartbeat thread
    hb_thread = threading.Thread(
        target=_heartbeat_loop, args=(client, dcus), daemon=True
    )
    hb_thread.start()

    # Outage manager + cumulative registers
    dtr_ids  = [d["dtr_id"] for d in dtrs]
    outage_m = OutageManager(dtr_ids)
    cum_reg  = {m["meter_id"]: m["register_start_kwh"] for m in meters}

    # Align to current 15-min boundary in NPT
    now = datetime.now(NPT)
    dt  = now.replace(second=0, microsecond=0)
    dt -= timedelta(minutes=dt.minute % 15)

    tick = 0
    log.info(f"🚀 Streaming from {dt.strftime('%Y-%m-%d %H:%M NPT')} ...")

    while True:
        t0      = time.time()
        outages = outage_m.tick(dt)
        events_this_tick = 0
        readings_this_tick = 0

        for m in meters:
            is_out   = m["dtr_id"] in outages
            out_type = outages.get(m["dtr_id"])
            rec      = generate_reading(m, dt, is_out, out_type)

            # Update cumulative register
            cum_reg[m["meter_id"]] += (rec["import_kwh"] or 0.0)
            rec["cumulative_kwh"] = round(cum_reg[m["meter_id"]], 2)

            payload = json.dumps(rec)

            # ── Publish reading ────────────────────────────────────────────
            read_topic = f"nea/readings/{m['feeder_id']}/{m['meter_serial']}"
            client.publish(read_topic, payload, qos=MQTT_QOS)
            readings_this_tick += 1

            # ── Publish event (if any flags set) ───────────────────────────
            if rec.get("event_flags"):
                event_payload = {
                    "meter_id":          rec["meter_id"],
                    "meter_serial":      rec["meter_serial"],
                    "consumer_id":       rec["consumer_id"],
                    "consumer_category": rec["consumer_category"],
                    "feeder_id":         rec["feeder_id"],
                    "dtr_id":            rec["dtr_id"],
                    "dcs_id":            rec["dcs_id"],
                    "timestamp_npt":     rec["timestamp_npt"],
                    "event_flags":       rec["event_flags"],
                    "is_outage":         rec["is_outage"],
                    "is_voltage_event":  rec["is_voltage_event"],
                    "is_tamper_event":   rec["is_tamper_event"],
                    "voltage_v":         rec["voltage_v"],
                    "event_code":        rec["event_flags"].split("|")[0],
                    "severity":          "CRITICAL" if rec["is_tamper_event"] else "WARNING",
                }
                event_topic = f"nea/events/{m['feeder_id']}/{m['meter_serial']}"
                client.publish(event_topic, json.dumps(event_payload), qos=2)
                events_this_tick += 1

        tick += 1
        elapsed = time.time() - t0
        log.info(
            f"⚡ Tick {tick:4d} [{dt.strftime('%H:%M NPT')}] "
            f"readings={readings_this_tick} events={events_this_tick} "
            f"outages={len(outages)} elapsed={elapsed:.2f}s"
        )

        dt += timedelta(minutes=15)

        # Sleep for remaining time in tick window
        if (wait := SLEEP_S - elapsed) > 0:
            time.sleep(wait)

if __name__ == "__main__":
    main()
