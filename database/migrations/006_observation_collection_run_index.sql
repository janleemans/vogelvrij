-- Run outside a transaction. CONCURRENTLY keeps observation inserts available
-- while an existing database builds the index.
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_aircraft_observations_collection_run_id
    ON aircraft_observations (collection_run_id);
