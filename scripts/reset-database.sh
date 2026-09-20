#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(dirname -- "$script_dir")

cd "$project_dir"

if [ "${1:-}" != "--yes" ]; then
    printf '%s\n' "This will permanently erase all collected Vogelvrij data." \
        "The database schema will be preserved." \
        "Type ERASE to continue:"
    read -r confirmation

    if [ "$confirmation" != "ERASE" ]; then
        printf '%s\n' "Reset cancelled."
        exit 1
    fi
fi

docker compose exec -T db psql \
    -v ON_ERROR_STOP=1 \
    -U "${POSTGRES_USER:-vogelvrij}" \
    -d "${POSTGRES_DB:-vogelvrij}" \
    --command="
        TRUNCATE TABLE
            aircraft_observations,
            collection_runs,
            flight_movements,
            wind_observations,
            taf_forecasts
        RESTART IDENTITY CASCADE;
    "

printf '%s\n' "All collected Vogelvrij data has been erased."
