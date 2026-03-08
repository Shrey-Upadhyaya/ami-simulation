-- ═══════════════════════════════════════════════════════════════════════════
--  NEA AMI — TimescaleDB Schema
--  Database: nea_ami
--  Standard: IEC 62056 / DLMS-COSEM aligned
--
--  Tables:
--    meter_registry        — static meter + consumer + topology
--    dtr_registry          — distribution transformer registry
--    interval_readings     — 15-min AMI readings (HYPERTABLE)
--    meter_events          — tamper/outage/quality events (HYPERTABLE)
--    dcu_heartbeat         — DCU health telemetry (HYPERTABLE)
--    dtr_load_summary      — hourly DTR-level aggregation (continuous agg)
--    feeder_load_summary   — hourly feeder-level aggregation (continuous agg)
-- ═══════════════════════════════════════════════════════════════════════════

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ─── ENUMS ────────────────────────────────────────────────────────────────────

CREATE TYPE consumer_category AS ENUM ('DOM', 'COM');

CREATE TYPE phase_type AS ENUM ('1P', '3P');

CREATE TYPE supply_level AS ENUM ('LV', 'MV');

CREATE TYPE event_category AS ENUM
    ('TAMPER', 'POWER', 'QUALITY', 'COMM', 'BILLING', 'SYSTEM');

CREATE TYPE event_severity AS ENUM ('INFO', 'WARNING', 'CRITICAL');

CREATE TYPE reading_quality AS ENUM
    ('VALID', 'ESTIMATED', 'MISSING', 'SUBSTITUTED');

-- ─── METER REGISTRY (static / slowly changing) ───────────────────────────────

CREATE TABLE meter_registry (
    -- Identity
    meter_id            UUID        PRIMARY KEY,
    meter_serial        VARCHAR(20) NOT NULL UNIQUE,
    meter_type          VARCHAR(30),

    -- Consumer
    consumer_id         VARCHAR(20) NOT NULL,
    consumer_name       VARCHAR(100),
    consumer_category   consumer_category NOT NULL,
    consumer_subtype    VARCHAR(30) NOT NULL,
    consumer_label      VARCHAR(80),
    tariff_code         VARCHAR(5)  NOT NULL,

    -- Electrical spec
    phase               phase_type  NOT NULL,
    supply_level        supply_level NOT NULL DEFAULT 'LV',
    rated_ampere        SMALLINT,           -- for domestic (5/15/30/60A)
    rated_kva           NUMERIC(8,2),       -- for 3-phase / MV
    voltage_v           NUMERIC(10,2),
    base_load_kw        NUMERIC(8,3),

    -- Infrastructure FK hierarchy (denormalized for query speed)
    dcs_id              VARCHAR(30) NOT NULL,
    pss_id              VARCHAR(30) NOT NULL,
    pss_name            VARCHAR(80),
    feeder_id           VARCHAR(20) NOT NULL,
    feeder_name         VARCHAR(80),
    feeder_length_km    NUMERIC(5,2),
    dtr_id              VARCHAR(40) NOT NULL,
    dtr_type            VARCHAR(20),        -- LV_SHARED / MV_DEDICATED
    dcu_id              UUID,

    -- Location
    latitude            NUMERIC(10,6),
    longitude           NUMERIC(10,6),

    -- Anomaly ground truth (for ML training)
    is_tampered         BOOLEAN DEFAULT FALSE,
    tamper_bypass_pct   NUMERIC(4,2) DEFAULT 0.0,

    -- Lifecycle
    registered_at       TIMESTAMPTZ DEFAULT NOW(),
    is_active           BOOLEAN DEFAULT TRUE
);

-- Indexes for common query patterns
CREATE INDEX idx_meter_feeder   ON meter_registry (feeder_id);
CREATE INDEX idx_meter_dtr      ON meter_registry (dtr_id);
CREATE INDEX idx_meter_category ON meter_registry (consumer_category);
CREATE INDEX idx_meter_tariff   ON meter_registry (tariff_code);
CREATE INDEX idx_meter_subtype  ON meter_registry (consumer_subtype);

-- ─── DTR REGISTRY ─────────────────────────────────────────────────────────────

CREATE TABLE dtr_registry (
    dtr_id          VARCHAR(40) PRIMARY KEY,
    dtr_serial      VARCHAR(20),
    capacity_kva    SMALLINT,
    voltage_ratio   VARCHAR(20),
    dtr_type        VARCHAR(20),    -- LV_SHARED / MV_DEDICATED
    latitude        NUMERIC(10,6),
    longitude       NUMERIC(10,6),
    feeder_id       VARCHAR(20) NOT NULL,
    feeder_name     VARCHAR(80),
    pss_id          VARCHAR(30) NOT NULL,
    pss_name        VARCHAR(80),
    dcs_id          VARCHAR(30) NOT NULL,
    registered_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ─── INTERVAL READINGS (time-series — HYPERTABLE) ─────────────────────────────
-- This is the highest-volume table.
-- At 1,000 meters × 96 slots/day = 96,000 rows/day
-- At 100,000 meters               = 9,600,000 rows/day
-- Partitioned by week (chunk_time_interval = 7 days)

CREATE TABLE interval_readings (
    -- Time (always Nepal Time UTC+5:45, stored as TIMESTAMPTZ)
    time                TIMESTAMPTZ     NOT NULL,
    time_slot           SMALLINT        NOT NULL,   -- 0–95
    hour                SMALLINT        NOT NULL,
    weekday             SMALLINT        NOT NULL,
    is_saturday         BOOLEAN         NOT NULL,

    -- Identity (denormalized — avoid joins on hot queries)
    meter_id            UUID            NOT NULL,
    meter_serial        VARCHAR(20)     NOT NULL,
    consumer_id         VARCHAR(20),
    consumer_category   consumer_category NOT NULL,
    consumer_subtype    VARCHAR(30)     NOT NULL,
    tariff_code         VARCHAR(5),
    phase               phase_type,
    supply_level        supply_level,

    -- Topology (denormalized)
    dcs_id              VARCHAR(30)     NOT NULL,
    pss_id              VARCHAR(30)     NOT NULL,
    feeder_id           VARCHAR(20)     NOT NULL,
    dtr_id              VARCHAR(40)     NOT NULL,
    dcu_id              UUID,

    -- Energy measurements
    import_kwh          NUMERIC(10,4),  -- NULL = comm loss
    export_kwh          NUMERIC(10,4),
    cumulative_kwh      NUMERIC(14,2),

    -- Power quality
    active_power_kw     NUMERIC(10,4),
    voltage_v           NUMERIC(8,2),
    current_a           NUMERIC(8,3),
    power_factor        NUMERIC(5,3),
    frequency_hz        NUMERIC(6,3),

    -- Status flags
    quality_flag        reading_quality DEFAULT 'VALID',
    is_outage           BOOLEAN         DEFAULT FALSE,
    is_comm_loss        BOOLEAN         DEFAULT FALSE,
    is_voltage_event    BOOLEAN         DEFAULT FALSE,
    is_tamper_event     BOOLEAN         DEFAULT FALSE,
    event_flags         VARCHAR(200),

    -- Ground truth labels (for ML)
    gt_is_tampered      BOOLEAN         DEFAULT FALSE,
    gt_tamper_bypass_pct NUMERIC(4,2)   DEFAULT 0.0,

    -- Pipeline metadata
    kafka_offset        BIGINT,
    ingested_at         TIMESTAMPTZ     DEFAULT NOW()
);

-- Convert to TimescaleDB hypertable — partitioned by week
SELECT create_hypertable(
    'interval_readings',
    'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Compression (after 30 days, compress chunks — huge storage saving)
ALTER TABLE interval_readings SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'feeder_id, consumer_category',
    timescaledb.compress_orderby   = 'time DESC'
);

SELECT add_compression_policy('interval_readings', INTERVAL '30 days');

-- Retention policy (keep 2 years of raw data)
SELECT add_retention_policy('interval_readings', INTERVAL '730 days');

-- Indexes for common query patterns
CREATE INDEX idx_readings_meter     ON interval_readings (meter_id, time DESC);
CREATE INDEX idx_readings_feeder    ON interval_readings (feeder_id, time DESC);
CREATE INDEX idx_readings_dtr       ON interval_readings (dtr_id, time DESC);
CREATE INDEX idx_readings_category  ON interval_readings (consumer_category, time DESC);
CREATE INDEX idx_readings_outage    ON interval_readings (is_outage, time DESC) WHERE is_outage = TRUE;
CREATE INDEX idx_readings_tamper    ON interval_readings (is_tamper_event, time DESC) WHERE is_tamper_event = TRUE;

-- ─── METER EVENTS (HYPERTABLE) ────────────────────────────────────────────────

CREATE TABLE meter_events (
    time                TIMESTAMPTZ     NOT NULL,
    event_id            UUID            DEFAULT gen_random_uuid(),

    -- Source identity
    meter_id            UUID            NOT NULL,
    meter_serial        VARCHAR(20),
    consumer_category   consumer_category,
    feeder_id           VARCHAR(20),
    dtr_id              VARCHAR(40),
    dcs_id              VARCHAR(30),

    -- Event detail
    event_category      event_category  NOT NULL,
    event_code          VARCHAR(40)     NOT NULL,
    event_description   TEXT,
    severity            event_severity  NOT NULL DEFAULT 'INFO',

    -- Acknowledgement
    is_acknowledged     BOOLEAN         DEFAULT FALSE,
    acknowledged_by     VARCHAR(50),
    acknowledged_at     TIMESTAMPTZ,

    -- Raw MQTT payload (for audit trail)
    raw_payload         JSONB,
    ingested_at         TIMESTAMPTZ     DEFAULT NOW()
);

SELECT create_hypertable(
    'meter_events',
    'time',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);

SELECT add_retention_policy('meter_events', INTERVAL '1825 days');  -- 5 years

CREATE INDEX idx_events_meter    ON meter_events (meter_id, time DESC);
CREATE INDEX idx_events_feeder   ON meter_events (feeder_id, time DESC);
CREATE INDEX idx_events_severity ON meter_events (severity, time DESC);
CREATE INDEX idx_events_category ON meter_events (event_category, time DESC);
CREATE INDEX idx_events_unacked  ON meter_events (is_acknowledged, time DESC) WHERE is_acknowledged = FALSE;

-- ─── DCU HEARTBEAT (HYPERTABLE) ───────────────────────────────────────────────

CREATE TABLE dcu_heartbeat (
    time                TIMESTAMPTZ     NOT NULL,
    dcu_id              UUID            NOT NULL,
    dcu_serial          VARCHAR(20),
    dtr_id              VARCHAR(40),
    feeder_id           VARCHAR(20),
    pss_id              VARCHAR(30),

    -- Telemetry
    status              VARCHAR(20),
    connected_meters    SMALLINT,
    signal_strength_dbm NUMERIC(6,2),
    packet_loss_pct     NUMERIC(5,2),
    uptime_seconds      INTEGER,
    ingested_at         TIMESTAMPTZ     DEFAULT NOW()
);

SELECT create_hypertable(
    'dcu_heartbeat',
    'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

SELECT add_retention_policy('dcu_heartbeat', INTERVAL '90 days');

-- ─── CONTINUOUS AGGREGATES (pre-computed rollups) ─────────────────────────────

-- Hourly DTR-level load summary (for Grafana dashboards)
CREATE MATERIALIZED VIEW dtr_hourly_summary
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time)         AS bucket,
    dtr_id,
    feeder_id,
    pss_id,
    consumer_category,
    COUNT(*)                            AS reading_count,
    SUM(import_kwh)                     AS total_import_kwh,
    AVG(active_power_kw)                AS avg_demand_kw,
    MAX(active_power_kw)                AS peak_demand_kw,
    AVG(voltage_v)                      AS avg_voltage_v,
    MIN(voltage_v)                      AS min_voltage_v,
    SUM(CASE WHEN is_outage THEN 1 ELSE 0 END)        AS outage_count,
    SUM(CASE WHEN is_voltage_event THEN 1 ELSE 0 END) AS voltage_event_count,
    SUM(CASE WHEN is_comm_loss THEN 1 ELSE 0 END)     AS comm_loss_count
FROM interval_readings
GROUP BY bucket, dtr_id, feeder_id, pss_id, consumer_category
WITH NO DATA;

SELECT add_continuous_aggregate_policy('dtr_hourly_summary',
    start_offset => INTERVAL '2 hours',
    end_offset   => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '15 minutes'
);

-- Hourly feeder-level summary
CREATE MATERIALIZED VIEW feeder_hourly_summary
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time)         AS bucket,
    feeder_id,
    pss_id,
    COUNT(DISTINCT meter_id)            AS active_meters,
    SUM(import_kwh)                     AS total_import_kwh,
    AVG(active_power_kw)                AS avg_demand_kw,
    MAX(active_power_kw)                AS peak_demand_kw,
    AVG(voltage_v)                      AS avg_voltage_v,
    MIN(voltage_v)                      AS min_voltage_v,
    SUM(CASE WHEN is_outage THEN 1 ELSE 0 END)       AS outage_meter_intervals,
    SUM(CASE WHEN is_tamper_event THEN 1 ELSE 0 END) AS tamper_events
FROM interval_readings
GROUP BY bucket, feeder_id, pss_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('feeder_hourly_summary',
    start_offset => INTERVAL '2 hours',
    end_offset   => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '15 minutes'
);

-- ─── UTILITY VIEWS ────────────────────────────────────────────────────────────

-- Live meter status view (last reading per meter)
CREATE VIEW meter_latest_status AS
SELECT DISTINCT ON (meter_id)
    meter_id,
    meter_serial,
    consumer_category,
    consumer_subtype,
    tariff_code,
    feeder_id,
    dtr_id,
    time            AS last_reading_time,
    import_kwh,
    active_power_kw,
    voltage_v,
    current_a,
    power_factor,
    is_outage,
    is_comm_loss,
    is_voltage_event,
    is_tamper_event
FROM interval_readings
ORDER BY meter_id, time DESC;

-- Active unacknowledged alerts
CREATE VIEW active_alerts AS
SELECT
    e.time,
    e.meter_serial,
    e.feeder_id,
    e.event_category,
    e.event_code,
    e.severity,
    m.consumer_name,
    m.consumer_subtype,
    m.tariff_code
FROM meter_events e
LEFT JOIN meter_registry m ON e.meter_id = m.meter_id
WHERE e.is_acknowledged = FALSE
  AND e.severity IN ('WARNING', 'CRITICAL')
ORDER BY e.time DESC;

-- ─── SEED: DCS metadata ───────────────────────────────────────────────────────
CREATE TABLE dcs_registry (
    dcs_id          VARCHAR(30) PRIMARY KEY,
    dcs_name        VARCHAR(80),
    pss_id          VARCHAR(30),
    pss_name        VARCHAR(80),
    location        VARCHAR(100),
    voltage_kv      VARCHAR(20),
    capacity_mva    NUMERIC(8,2),
    latitude        NUMERIC(10,6),
    longitude       NUMERIC(10,6),
    commissioned_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO dcs_registry VALUES (
    'DCS_BALAJU_01',
    'NEA Data Collection System — Balaju Primary Substation',
    'PSS_BALAJU_01',
    'Balaju Primary Substation',
    'Balaju, Kathmandu',
    '132/11',
    50.0,
    27.7370,
    85.3005,
    NOW()
);

\echo '✅ NEA AMI TimescaleDB schema initialized successfully'
\echo '   Hypertables: interval_readings, meter_events, dcu_heartbeat'
\echo '   Continuous aggregates: dtr_hourly_summary, feeder_hourly_summary'
