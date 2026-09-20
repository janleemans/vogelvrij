-- Apply once to an existing database. Docker's initdb also runs it after 001 on a new volume.
ALTER TABLE flight_movements
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS approach_corridor TEXT;

CREATE INDEX IF NOT EXISTS ix_flight_movements_aircraft_created_at
    ON flight_movements (aircraft_icao, created_at);
