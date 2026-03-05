"""
AMI Meter Simulator - Publishes simulated smart meter readings to MQTT.

Simulates multiple meters with realistic consumption patterns:
- Daily load curves (peak morning/evening, low at night)
- Random variation per meter
- Voltage, power factor, and status fields
"""

import json
import random
import time
from datetime import datetime
from typing import List

import paho.mqtt.client as mqtt

from config import MQTT_BROKER, MQTT_PORT, MQTT_TOPIC_METERS, MQTT_TOPIC_EVENTS

# Simulated meter fleet
DEFAULT_METERS = [
    "MTR-001", "MTR-002", "MTR-003", "MTR-004", "MTR-005",
    "MTR-006", "MTR-007", "MTR-008", "MTR-009", "MTR-010",
]


def get_load_multiplier() -> float:
    """Simulate daily load curve: higher in morning (7-9) and evening (18-22)."""
    hour = datetime.now().hour
    minute = datetime.now().minute
    t = hour + minute / 60
    if 7 <= t <= 9 or 18 <= t <= 22:
        return 1.2 + random.uniform(0, 0.3)
    elif 0 <= t <= 5:
        return 0.4 + random.uniform(0, 0.2)
    else:
        return 0.7 + random.uniform(0, 0.2)


def generate_reading(meter_id: str) -> dict:
    """Generate one simulated meter reading."""
    base_kwh = random.uniform(0.01, 0.15)
    multiplier = get_load_multiplier()
    kwh = round(base_kwh * multiplier, 4)
    kvarh = round(kwh * random.uniform(0.02, 0.1), 4)
    return {
        "meter_id": meter_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "kwh": kwh,
        "kvarh": kvarh,
        "voltage": round(220 + random.uniform(-10, 10), 1),
        "power_factor": round(random.uniform(0.85, 1.0), 2),
        "status": "normal",
        "interval_minutes": 15,
    }


def generate_event(meter_id: str, event_type: str = "reading") -> dict:
    """Generate meter event (for HES-style event stream)."""
    return {
        "meter_id": meter_id,
        "event_type": event_type,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "data": generate_reading(meter_id) if event_type == "reading" else {},
    }


def run_simulator(meters: List[str] = None, interval_sec: int = 15):
    """Run the meter simulator, publishing readings to MQTT."""
    meters = meters or DEFAULT_METERS
    client = mqtt.Client(client_id="ami-meter-simulator")
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()

    try:
        print(f"AMI Meter Simulator started. Publishing {len(meters)} meters every {interval_sec}s")
        while True:
            for meter_id in meters:
                reading = generate_reading(meter_id)
                topic = MQTT_TOPIC_METERS.format(meter_id=meter_id)
                payload = json.dumps(reading)
                client.publish(topic, payload, qos=1)
                print(f"Published: {topic} -> {reading['kwh']} kWh")
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        client.loop_stop()
        client.disconnect()
        print("Simulator stopped.")


if __name__ == "__main__":
    run_simulator()
