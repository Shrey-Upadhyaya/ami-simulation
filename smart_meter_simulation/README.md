# NEA Smart Meter Simulation — Holistic Platform

**Nepal Electricity Authority | Kathmandu Valley AMI PoC**

End-to-end smart metering simulation: **data generation** → **ingestion** → **pipeline** → **monitoring**.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  DATA GENERATION (nea_v2)                                                         │
│  • Batch: CSV files (run locally, historical backfill)                            │
│  • Stream: MQTT (real-time, 15-min intervals)                                     │
│  • 1000 meters, 10 feeders, 113 DTRs, per-phase advanced metering                 │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┴───────────────────────┐
        │ Batch CSV              │ Stream MQTT           │
        ▼                        ▼                      │
┌───────────────────┐   ┌──────────────────┐           │
│ batch_to_kafka.py │   │ Mosquitto :1883  │           │
│ (ingest tool)     │   │ nea/readings/#   │           │
└─────────┬─────────┘   └────────┬─────────┘           │
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 ▼
                    ┌────────────────────────┐
                    │ MQTT → Kafka Bridge    │
                    │ nea.meters.readings    │
                    │ nea.meters.events      │
                    │ nea.dcus.heartbeat     │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │ Apache Kafka :9092     │
                    │ (7d retention)         │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │ Kafka → TimescaleDB    │
                    │ db_writer (batch 500)  │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │ TimescaleDB :5432      │
                    │ interval_readings      │
                    │ meter_events           │
                    │ dtr_hourly_summary     │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │ Grafana :3000          │
                    │ NEA AMI Overview       │
                    └────────────────────────┘
```

---

## Project Structure

```
smart_meter_simulation/
├── nea_v2/                    # Data generator (canonical)
│   ├── simulator.py           # Batch or stream to CSV/JSONL
│   ├── core/
│   │   ├── infrastructure.py  # Topology builder
│   │   └── generator.py       # Per-phase readings
│   ├── config/
│   │   ├── topology.py        # Feeders, consumer types
│   │   └── load_profiles.py   # 96-slot Nepal profiles
│   └── output/
│       ├── batch/             # nea_readings_YYYY-MM-DD.csv
│       └── stream/            # stream_output.jsonl
│
├── nea_pipeline/              # Data ingestion + pipeline + monitoring
│   ├── docker-compose.yml     # Full stack
│   ├── simulator/             # MQTT simulator (uses nea_v2 logic)
│   │   ├── mqtt_simulator.py  # Publishes to Mosquitto
│   │   └── config/, core/     # Synced with nea_v2
│   ├── bridge/                # MQTT→Kafka, Kafka→TimescaleDB
│   ├── ingest/
│   │   └── batch_to_kafka.py  # CSV → Kafka
│   ├── timescaledb/           # Schema + per-phase columns
│   └── grafana/               # Dashboards
│
└── README.md                  # This file
```

---

## Quick Start

### Option A: Stream (live MQTT → full pipeline)

```bash
cd nea_pipeline
docker compose up -d

# Simulator publishes to MQTT; bridge→Kafka→TimescaleDB→Grafana
# Grafana: http://localhost:3000  (admin / nea_grafana_pass)
# Kafka UI: http://localhost:8080
```

### Option B: Batch (nea_v2 CSV → Kafka → TimescaleDB)

```bash
# 1. Generate batch data (nea_v2)
cd nea_v2
python simulator.py --mode batch --days 7

# 2. Start pipeline (without simulator)
cd ../nea_pipeline
docker compose up -d mosquitto kafka kafka-init kafka-ui bridge timescaledb db-writer grafana

# 3. Ingest batch CSVs to Kafka
pip install kafka-python-ng
python ingest/batch_to_kafka.py --input ../nea_v2/output/batch --days 7

# 4. View in Grafana
```

### Option C: Batch only (no Kafka, direct CSV analysis)

```bash
cd nea_v2
python simulator.py --mode batch --days 30
# Output: output/batch/nea_readings_*.csv, meter_registry.csv, simulation_summary.json
```

---

## Modes Summary

| Mode | Use Case | Output |
|------|----------|--------|
| **nea_v2 batch** | Historical backfill, testing | CSV files |
| **nea_v2 stream** | Local JSONL debug | stream_output.jsonl |
| **nea_pipeline stream** | Production-like PoC | MQTT→Kafka→TimescaleDB→Grafana |
| **nea_pipeline batch** | Bulk load historical CSV | batch_to_kafka → Kafka → TimescaleDB |

---

## Features

- **Advanced metering**: Per-phase voltage (V_an, V_bn, V_cn) and current (I_a, I_b, I_c) for 3P meters
- **Realistic load profiles**: Nepal urban (domestic + commercial), 96 slots/day
- **Outages**: DTR-level faults (CABLE_FAULT, TREE_CONTACT, FUSE_BLOW, etc.)
- **Tampering**: 1.5% tampered meters with bypass %, tamper events
- **Voltage events**: LOW_VOLTAGE, HIGH_VOLTAGE by load tier

---

## Ports

| Service | Port |
|---------|------|
| Mosquitto | 1883 (MQTT), 9001 (WebSocket) |
| Kafka | 9092 |
| Kafka UI | 8080 |
| TimescaleDB | 5432 |
| Grafana | 3000 |

---

*NEA Data Center | Balaju Primary Substation — AMI PoC*
