#!/bin/sh
set -eu

usage() {
    printf 'Usage: %s INTERVAL_SECONDS RUNS [vogelvrij-collect options...]\n' "$0" >&2
    printf '%s\n' 'INTERVAL_SECONDS must be greater than zero; RUNS must be a positive integer.' >&2
    exit 2
}

[ "$#" -ge 2 ] || usage
interval_seconds=$1
runs=$2
shift 2

LC_ALL=C awk -v value="$interval_seconds" '
    BEGIN { exit !(value ~ /^[0-9]+([.][0-9]+)?$/ && value + 0 > 0) }
' || usage

case "$runs" in
    ''|*[!0-9]*) usage ;;
esac
[ "$runs" -gt 0 ] 2>/dev/null || usage

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(dirname -- "$script_dir")

if command -v vogelvrij-collect >/dev/null 2>&1; then
    collector=vogelvrij-collect
elif [ -x "$project_dir/.venv/bin/vogelvrij-collect" ]; then
    collector="$project_dir/.venv/bin/vogelvrij-collect"
else
    printf '%s\n' 'vogelvrij-collect not found; activate or install the project environment.' >&2
    exit 1
fi

run=1
while [ "$run" -le "$runs" ]; do
    printf 'Collection %s/%s\n' "$run" "$runs"
    "$collector" "$@"
    printf 'Collection %s/%s done, sleeping for %s seconds...\n' "$run" "$runs" "$interval_seconds"
    if [ "$run" -lt "$runs" ]; then
        sleep "$interval_seconds"
    fi
    run=$((run + 1))
done
