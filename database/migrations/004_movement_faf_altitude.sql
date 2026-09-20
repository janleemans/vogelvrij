-- Additive and idempotent. Existing movement rows are populated separately by
-- scripts/backfill-faf-altitudes.py after this migration is applied.
ALTER TABLE flight_movements
    ADD COLUMN IF NOT EXISTS faf_altitude_ft INTEGER,
    ADD COLUMN IF NOT EXISTS faf_distance_m DOUBLE PRECISION;
