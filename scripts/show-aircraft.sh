#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(dirname -- "$script_dir")

cd "$project_dir"

docker compose exec -T db psql \
    -U "${POSTGRES_USER:-vogelvrij}" \
    -d "${POSTGRES_DB:-vogelvrij}" \
    --pset="null=-" \
    --command="
        WITH latest_per_aircraft AS (
            SELECT
                aircraft_observations.*,
                row_number() OVER (
                    PARTITION BY COALESCE(NULLIF(hex, ''), 'unknown:' || id::text)
                    ORDER BY observed_at DESC, id DESC
                ) AS observation_rank
            FROM aircraft_observations
        )
        SELECT
            COALESCE(NULLIF(flight, ''), '-') AS \"Flight number\",
            COALESCE(alt_baro_ft::text, alt_baro_state, '-') AS \"Height (ft)\",
            COALESCE(round(track_degrees::numeric, 1)::text, '-') AS \"Direction (°)\",
            to_char(
                observed_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD HH24:MI:SS'
            ) || ' UTC' AS \"Latest observation\"
        FROM latest_per_aircraft
        WHERE observation_rank = 1
        ORDER BY flight NULLS LAST, hex NULLS LAST;
    "
