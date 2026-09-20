-- Additive migration for existing volumes; also runs at init on a fresh volume.
CREATE TABLE IF NOT EXISTS taf_forecasts (
    id BIGSERIAL PRIMARY KEY,
    station TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    issued_at TIMESTAMPTZ NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NOT NULL,
    raw_taf TEXT NOT NULL,
    raw_data JSONB NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_taf_forecasts_station_raw_taf
    ON taf_forecasts (station, raw_taf);
CREATE INDEX IF NOT EXISTS ix_taf_forecasts_station_issued
    ON taf_forecasts (station, issued_at);
