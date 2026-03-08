-- Per-phase voltage and current for advanced 3P metering (nea_v2 integration)
-- 1P meters: voltage_an/current_a_ph only; 3P: all six columns populated

ALTER TABLE interval_readings
  ADD COLUMN IF NOT EXISTS voltage_an   NUMERIC(8,2),
  ADD COLUMN IF NOT EXISTS voltage_bn   NUMERIC(8,2),
  ADD COLUMN IF NOT EXISTS voltage_cn   NUMERIC(8,2),
  ADD COLUMN IF NOT EXISTS current_a_ph NUMERIC(8,3),
  ADD COLUMN IF NOT EXISTS current_b_ph NUMERIC(8,3),
  ADD COLUMN IF NOT EXISTS current_c_ph NUMERIC(8,3);

CREATE INDEX IF NOT EXISTS idx_readings_voltage_an ON interval_readings (voltage_an) WHERE voltage_an IS NOT NULL;
