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
        SELECT
            id AS \"Movement ID\",
            COALESCE(callsign, '-') AS \"Flight\",
            COALESCE(aircraft_icao, '-') AS \"Aircraft ICAO\",
            COALESCE(approach_corridor, '-') AS \"Approach\",
            COALESCE(wind_direction_degrees::text, '-') AS \"METAR wind dir (deg)\",
            COALESCE(wind_speed_knots::text, '-') AS \"METAR wind speed (kt)\",
            COALESCE(expected_approach, '-') AS \"Expected approach\",
            to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
                || ' UTC' AS \"Detected\",
            to_char(first_observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
                || ' UTC' AS \"First seen\",
            to_char(last_observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
                || ' UTC' AS \"Last seen\"
        FROM flight_movements
        ORDER BY created_at DESC, id DESC;
    "
