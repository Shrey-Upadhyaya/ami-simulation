# AMI (Advanced Metering Infrastructure) Simulation Platform

A full end-to-end simulation of a smart metering system — from meter to dashboard — built with open-source tools.

## Architecture

```
Simulated Meters → MQTT Broker → Data Processor → Time-Series DB → Dashboard
     (Python)      (Mosquitto)    (Python)         (InfluxDB)      (Grafana)
                                      ↓
                               PostgreSQL (billing, customer data)
                                      ↓
                              FastAPI (REST API for HES simulation)
```

## Quick Start

### 1. Start infrastructure (Docker)

```bash
cd ami-simulation
docker compose up -d
```

This starts:
- **Mosquitto** (MQTT) on port 31883
- **InfluxDB** on port 8086
- **PostgreSQL** on port 5432
- **Grafana** on port 3000

Wait ~30 seconds for InfluxDB/PostgreSQL to initialize.

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the data processor

```bash
python -m processor.data_processor
```

Keep this running in a terminal. It subscribes to MQTT and writes to InfluxDB + PostgreSQL.

### 4. Run the meter simulator

```bash
python -m meters.simulator
```

This publishes simulated meter readings to MQTT every 15 seconds.

### 5. Start the REST API (optional)

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### 6. View dashboards

- **Grafana**: http://localhost:3000 — Login: `admin` / `ami_admin`
- **FastAPI docs**: http://localhost:8000/docs
- **InfluxDB**: http://localhost:8086 — Login: `admin` / `ami_password`

## Project Structure

```
ami-simulation/
├── config.py              # Shared configuration
├── docker-compose.yml     # Mosquitto, InfluxDB, PostgreSQL, Grafana
├── meters/
│   └── simulator.py       # Publishes simulated readings to MQTT
├── processor/
│   └── data_processor.py  # Consumes MQTT → InfluxDB + PostgreSQL
├── api/
│   └── main.py            # FastAPI HES REST API
├── postgres/
│   └── init.sql           # Schema (customers, tariffs, billing)
├── grafana/
│   └── provisioning/      # InfluxDB datasource + AMI dashboard
└── config/
    └── mosquitto/         # Mosquitto config
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/customers` | List customers |
| `GET /api/customers/{meter_id}` | Customer by meter ID |
| `GET /api/meters/{meter_id}/readings` | Daily aggregate readings |
| `GET /api/meters/{meter_id}/billing` | Billing summary |
| `GET /api/tariffs` | List tariffs |

## Configuration

Environment variables (defaults shown):

| Variable | Default |
|----------|---------|
| `MQTT_BROKER` | localhost |
| `MQTT_PORT` | 31883 |
| `INFLUXDB_URL` | http://localhost:8086 |
| `INFLUXDB_TOKEN` | ami-influx-token |
| `POSTGRES_HOST` | localhost |
| `POSTGRES_DB` | ami_db |
| `POSTGRES_USER` | ami_user |
| `POSTGRES_PASSWORD` | ami_password |

## MQTT Topics

- `ami/meters/{meter_id}/readings` — Meter readings (kWh, voltage, power factor, etc.)
- `ami/meters/{meter_id}/events` — Meter events (optional)
