-- Additive and idempotent. Existing movements remain NULL: their insertion-time
-- wind cannot be reconstructed reliably from the current latest METAR.
ALTER TABLE flight_movements
    ADD COLUMN IF NOT EXISTS wind_direction_degrees DOUBLE PRECISION
        CHECK (wind_direction_degrees >= 0 AND wind_direction_degrees <= 360),
    ADD COLUMN IF NOT EXISTS wind_speed_knots DOUBLE PRECISION
        CHECK (wind_speed_knots >= 0),
    ADD COLUMN IF NOT EXISTS expected_approach TEXT;
