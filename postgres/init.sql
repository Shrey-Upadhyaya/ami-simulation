-- AMI Platform: PostgreSQL schema for billing and customer data

-- Tariffs (electricity rates) - must exist before customers
CREATE TABLE tariffs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    rate_per_kwh DECIMAL(10, 4) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    valid_from DATE NOT NULL,
    valid_to DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Customers
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    meter_id VARCHAR(50) UNIQUE NOT NULL,
    customer_name VARCHAR(255) NOT NULL,
    address TEXT,
    meter_type VARCHAR(50) DEFAULT 'smart',
    tariff_id INTEGER REFERENCES tariffs(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default tariff
INSERT INTO tariffs (id, name, rate_per_kwh, valid_from) VALUES 
(1, 'Standard Residential', 0.12, '2020-01-01');

-- Billing cycles
CREATE TABLE billing_cycles (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
    cycle_start DATE NOT NULL,
    cycle_end DATE NOT NULL,
    total_kwh DECIMAL(12, 4) DEFAULT 0,
    amount_due DECIMAL(12, 2) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Daily aggregate readings (denormalized for billing queries)
CREATE TABLE daily_readings (
    id SERIAL PRIMARY KEY,
    meter_id VARCHAR(50) NOT NULL,
    reading_date DATE NOT NULL,
    total_kwh DECIMAL(12, 4) NOT NULL,
    peak_kwh DECIMAL(12, 4) DEFAULT 0,
    off_peak_kwh DECIMAL(12, 4) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(meter_id, reading_date)
);

-- Meter events (connect/disconnect, alarms)
CREATE TABLE meter_events (
    id SERIAL PRIMARY KEY,
    meter_id VARCHAR(50) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    event_data JSONB,
    occurred_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_daily_readings_meter ON daily_readings(meter_id);
CREATE INDEX idx_daily_readings_date ON daily_readings(reading_date);
CREATE INDEX idx_meter_events_meter ON meter_events(meter_id);
CREATE INDEX idx_meter_events_occurred ON meter_events(occurred_at);
