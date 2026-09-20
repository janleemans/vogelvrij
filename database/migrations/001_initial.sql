CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE collection_runs (
    id BIGSERIAL PRIMARY KEY,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider TEXT NOT NULL DEFAULT 'adsb.lol',
    request_lat DOUBLE PRECISION NOT NULL,
    request_lon DOUBLE PRECISION NOT NULL,
    request_radius_nm DOUBLE PRECISION NOT NULL CHECK (request_radius_nm > 0),
    response_message TEXT,
    provider_now_ms BIGINT,
    provider_cached_at_ms BIGINT,
    provider_processing_ms DOUBLE PRECISION,
    provider_total INTEGER,
    response_metadata JSONB NOT NULL
);

CREATE TABLE flight_movements (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    aircraft_icao TEXT,
    callsign TEXT,
    approach_corridor TEXT,
    first_observed_at TIMESTAMPTZ,
    last_observed_at TIMESTAMPTZ,
    origin_airport_icao TEXT,
    origin_airport_iata TEXT,
    destination_airport_icao TEXT,
    destination_airport_iata TEXT,
    route_provider TEXT,
    route_enriched_at TIMESTAMPTZ,
    route_data JSONB
);

CREATE INDEX ix_flight_movements_identity
    ON flight_movements (aircraft_icao, callsign, first_observed_at);
CREATE INDEX ix_flight_movements_aircraft_created_at
    ON flight_movements (aircraft_icao, created_at);

CREATE TABLE aircraft_observations (
    id BIGSERIAL PRIMARY KEY,
    collection_run_id BIGINT NOT NULL REFERENCES collection_runs(id) ON DELETE CASCADE,
    flight_movement_id BIGINT REFERENCES flight_movements(id) ON DELETE SET NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    hex TEXT,
    address_type TEXT,
    flight TEXT,
    registration TEXT,
    aircraft_type TEXT,
    description TEXT,
    operator TEXT,
    year INTEGER,
    db_flags INTEGER,
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    position GEOGRAPHY(POINT, 4326) GENERATED ALWAYS AS (
        CASE
            WHEN lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180
            THEN ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
            ELSE NULL
        END
    ) STORED,
    alt_baro_ft INTEGER,
    alt_baro_state TEXT,
    alt_geom_ft INTEGER,
    ground_speed_knots DOUBLE PRECISION,
    indicated_airspeed_knots DOUBLE PRECISION,
    true_airspeed_knots DOUBLE PRECISION,
    mach DOUBLE PRECISION,
    track_degrees DOUBLE PRECISION,
    track_rate_dps DOUBLE PRECISION,
    roll_degrees DOUBLE PRECISION,
    magnetic_heading_degrees DOUBLE PRECISION,
    true_heading_degrees DOUBLE PRECISION,
    barometric_rate_fpm INTEGER,
    geometric_rate_fpm INTEGER,
    squawk TEXT,
    emergency TEXT,
    category TEXT,
    nav_qnh_hpa DOUBLE PRECISION,
    nav_altitude_mcp_ft INTEGER,
    nav_altitude_fms_ft INTEGER,
    nav_heading_degrees DOUBLE PRECISION,
    nav_modes JSONB,
    nic INTEGER,
    radius_of_containment_m INTEGER,
    seen_position_seconds DOUBLE PRECISION,
    adsb_version INTEGER,
    nic_baro INTEGER,
    nac_p INTEGER,
    nac_v INTEGER,
    sil INTEGER,
    sil_type TEXT,
    gva INTEGER,
    sda INTEGER,
    alert INTEGER,
    spi INTEGER,
    mlat_fields JSONB,
    tisb_fields JSONB,
    messages BIGINT,
    seen_seconds DOUBLE PRECISION,
    rssi_dbfs DOUBLE PRECISION,
    wind_direction_degrees DOUBLE PRECISION,
    wind_speed_knots DOUBLE PRECISION,
    outside_air_temperature_c DOUBLE PRECISION,
    total_air_temperature_c DOUBLE PRECISION,
    receiver_distance_nm DOUBLE PRECISION,
    receiver_direction_degrees DOUBLE PRECISION,
    rough_receiver_lat DOUBLE PRECISION,
    rough_receiver_lon DOUBLE PRECISION,
    last_position JSONB,
    acas_resolution_advisory JSONB,
    gps_ok_before DOUBLE PRECISION,
    gps_ok_lat DOUBLE PRECISION,
    gps_ok_lon DOUBLE PRECISION,
    raw_data JSONB NOT NULL
);

CREATE INDEX ix_aircraft_observations_hex_observed
    ON aircraft_observations (hex, observed_at);
CREATE INDEX ix_aircraft_observations_flight_observed
    ON aircraft_observations (flight, observed_at);
CREATE INDEX ix_aircraft_observations_observed_at
    ON aircraft_observations (observed_at);
CREATE INDEX ix_aircraft_observations_position
    ON aircraft_observations USING GIST (position);

CREATE TABLE wind_observations (
    id BIGSERIAL PRIMARY KEY,
    observed_at TIMESTAMPTZ NOT NULL,
    direction_degrees DOUBLE PRECISION NOT NULL
        CHECK (direction_degrees >= 0 AND direction_degrees < 360),
    speed_mps DOUBLE PRECISION NOT NULL CHECK (speed_mps >= 0),
    gust_speed_mps DOUBLE PRECISION CHECK (gust_speed_mps IS NULL OR gust_speed_mps >= 0),
    source TEXT,
    raw_data JSONB
);

CREATE INDEX ix_wind_observations_observed_at ON wind_observations (observed_at);
