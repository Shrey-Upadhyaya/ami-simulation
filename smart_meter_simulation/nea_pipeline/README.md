# NEA AMI Data Pipeline
### Nepal Electricity Authority — Kathmandu Valley PoC

Integrated with **nea_v2** for holistic data generation. See [../README.md](../README.md) for the full platform.

---

## Architecture

```
Simulator (Python) — nea_v2 logic, per-phase metering
    │  MQTT publish QoS 1/2
    ▼
Mosquitto MQTT Broker  :1883
    │  subscribe nea/#
    ▼
MQTT→Kafka Bridge (Python)
    │  produce (partitioned by feeder_id)
    ▼
Apache Kafka KRaft  :9092
    ├── nea.meters.readings   (10 partitions, 7d retention)
    ├── nea.meters.events     (10 partitions, 30d retention)
    ├── nea.meters.alerts     (3 partitions  — CRITICAL only)
    └── nea.dcus.heartbeat    (5 partitions, 1d retention)
    │  consume (batch, 500 rows / 5s flush)
    ▼
Kafka→TimescaleDB Writer (Python)
    │  COPY bulk insert
    ▼
TimescaleDB (PostgreSQL 16)  :5432
    ├── interval_readings     HYPERTABLE (weekly chunks)
    ├── meter_events          HYPERTABLE (monthly chunks)
    ├── dcu_heartbeat         HYPERTABLE (daily chunks)
    ├── dtr_hourly_summary    CONTINUOUS AGGREGATE
    └── feeder_hourly_summary CONTINUOUS AGGREGATE
    │
    ▼
Grafana  :3000
    └── NEA AMI Overview Dashboard
```

---

## Quick Start

### Prerequisites
- Docker Engine 24+
- Docker Compose v2.20+
- 4 GB RAM minimum (8 GB recommended)
- 10 GB disk

### Start the stack
```bash
# Clone / navigate to project
cd nea_pipeline

# Start all services (first run downloads images ~2GB)
docker compose up -d

# Watch logs
docker compose logs -f bridge simulator

# Check status
docker compose ps
```

### Access UIs
| Service | URL | Credentials |
|---|---|---|
| Grafana | http://localhost:3000 | admin / nea_grafana_pass |
| Kafka UI | http://localhost:8080 | (no auth) |
| TimescaleDB | localhost:5432 | nea_user / nea_secure_pass |
| Mosquitto | localhost:1883 | (anonymous PoC mode) |

---

## MQTT Topic Structure

```
nea/readings/{feeder_id}/{meter_serial}   ← 15-min interval (QoS 1)
nea/events/{feeder_id}/{meter_serial}     ← events/alarms   (QoS 2)
nea/heartbeat/{dcu_id}                   ← DCU health       (QoS 1)
```

### Sample reading payload
```json
{
  "meter_id": "4c962bd6-...",
  "meter_serial": "NEA26019511",
  "consumer_category": "DOM",
  "consumer_subtype": "DOM_SP_15A",
  "tariff_code": "D2",
  "feeder_id": "FDR_02",
  "dtr_id": "DTR_FDR_02_01",
  "timestamp_npt": "2026-03-08 19:30:00",
  "import_kwh": 0.3421,
  "active_power_kw": 1.3684,
  "voltage_v": 218.4,
  "current_a": 7.234,
  "power_factor": 0.914,
  "frequency_hz": 50.023,
  "is_outage": false,
  "is_voltage_event": true,
  "event_flags": "LOW_VOLTAGE"
}
```

---

## Kafka Topics

| Topic | Partitions | Key | Retention |
|---|---|---|---|
| nea.meters.readings | 10 | feeder_id | 7 days |
| nea.meters.events | 10 | meter_id | 30 days |
| nea.meters.alerts | 3 | meter_id | 30 days |
| nea.dcus.heartbeat | 5 | dcu_id | 1 day |

Readings are partitioned by `feeder_id` — all readings from the same
feeder go to the same Kafka partition, preserving order for loss calculations.

---

## TimescaleDB Schema

### Key tables

```sql
-- Fast time-range query: last hour of readings for a feeder
SELECT time, meter_serial, import_kwh, voltage_v
FROM interval_readings
WHERE feeder_id = 'FDR_02'
  AND time > NOW() - INTERVAL '1 hour'
ORDER BY time DESC;

-- DTR load rollup (uses continuous aggregate — instant)
SELECT bucket, dtr_id, avg_demand_kw, peak_demand_kw, min_voltage_v
FROM dtr_hourly_summary
WHERE feeder_id = 'FDR_05'
  AND bucket > NOW() - INTERVAL '24 hours'
ORDER BY bucket DESC;

-- Unacknowledged alerts
SELECT * FROM active_alerts LIMIT 20;

-- AT&C loss proxy: tampered meters' consumption
SELECT meter_serial, feeder_id, SUM(import_kwh) as billed_kwh,
       AVG(gt_tamper_bypass_pct) as bypass_pct
FROM interval_readings
WHERE gt_is_tampered = true
  AND time > NOW() - INTERVAL '30 days'
GROUP BY meter_serial, feeder_id;
```

---

## Simulator Speed Control

```bash
# 60x realtime (default) — 1 tick every 1 second
docker compose up -d simulator

# 1x realtime — one tick every 15 minutes (production-like)
SIM_SPEED=1 docker compose up -d simulator

# Turbo mode — as fast as possible
SIM_SPEED=900 docker compose up -d simulator
```

---

## Stopping & Cleanup

```bash
# Stop all services (keep data)
docker compose down

# Stop + remove all data volumes
docker compose down -v

# Rebuild after code change
docker compose build bridge simulator
docker compose up -d bridge simulator
```

---

## Batch Ingestion (nea_v2 CSV → Kafka)

To load historical batch data from nea_v2:

```bash
# 1. Generate batch (in nea_v2)
python simulator.py --mode batch --days 7

# 2. Start pipeline (no simulator)
docker compose up -d mosquitto kafka kafka-init bridge timescaledb db-writer grafana

# 3. Ingest
pip install kafka-python-ng
python ingest/batch_to_kafka.py --input ../nea_v2/output/batch --days 7
```

---

## Next Steps

1. **Flink stream processing** — real-time AT&C loss calc, anomaly detection
2. **MinIO data lake** — Parquet export of raw readings for historical analysis
3. **Alert manager** — email/SMS on CRITICAL events (tamper, prolonged outage)
4. **TLS on Mosquitto** — secure MQTT with client certificates per DCU
5. **Kafka Connect** — JDBC sink to replace custom db_writer.py

---

*Nepal Electricity Authority | Computer Engineer Level 7 | NEA Data Center*
*Balaju Primary Substation — AMI PoC*
