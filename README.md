# Vogelvrij

Vogelvrij collects public aircraft-position observations for later filtering, statistics,
and visualization of landing traffic over a defined region.

The first integration uses the public [adsb.lol API](https://api.adsb.lol/docs). The API and
published data are licensed under the Open Data Commons Open Database License (ODbL) 1.0.
Any public data product built from this source must retain the required attribution and comply
with that license.

## Run one collection

Python 3.9 or newer is required.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Pass the center and radius directly:

```sh
vogelvrij-collect --lat 50.8503 --lon 4.3517 --radius-nm 25
```

Or configure the three location variables shown in `.env.example` and run:

```sh
python -m vogelvrij
```

The command prints normalized aircraft that include a valid reported latitude and longitude.

To collect repeatedly, pass a positive interval in seconds, a positive number of runs, and
optionally the usual collector arguments. The first call runs immediately; the script waits
after each call except the last:

```sh
./scripts/collect-repeatedly.sh 60 10 --lat 50.8503 --lon 4.3517 --radius-nm 25
```

The script also works with `VOGELVRIJ_*` location variables instead of command-line location
arguments. It stops if a collection fails. Choose a conservative interval to respect the
provider's dynamic rate limits; this is a foreground loop, not a background scheduler.

## Continuous collection on a server

`scripts/collect-forever.py` runs all three installed one-shot commands in one foreground
process. It starts each immediately, then schedules flights every 60 seconds (configurable
with `--flight-interval SECONDS` or `VOGELVRIJ_FLIGHT_INTERVAL`) and EBBR METAR and TAF every
3,600 seconds each. Flights default to `--lat 50.900167 --lon 4.460000 --radius-nm 15`; the
runner accepts those flags or `VOGELVRIJ_LAT`, `VOGELVRIJ_LON`, and
`VOGELVRIJ_RADIUS_NM`. Command-line options take precedence over environment values. It
prefers this checkout's `.venv/bin` commands, then `PATH`.
Set `DATABASE_URL` in the service environment if the database is not at the local default.
Install the project, start the database, and apply all migrations before starting it:

```sh
./scripts/collect-forever.py
```

The runner logs failed attempts and tries again at the next scheduled slot; it never starts
two collectors simultaneously or bursts through missed intervals. A long collector can delay
another due job, so this is a best-effort cadence rather than an exact wall-clock scheduler.
Stop with SIGTERM or Ctrl-C. It does not daemonize, persist a queue, or manage the database.
Keep only one runner (and no other flight collector) active against a given database: movement
creation is not protected against concurrent collectors. Choose a flight interval appropriate
to the upstream API's rate limits.

The checked-in systemd templates in `deploy/systemd/` run both the continuous collector and
the web prototype as user `deploy` from `/home/deploy/vogelvrij`. The `%i` instance is either
`test` or `prod`; it selects the required `/etc/vogelvrij/%i.env` file. Install or update the
unit definitions after each relevant deployment with:

```sh
sudo ./scripts/install-systemd-services.sh
```

The installer copies the two templates to `/etc/systemd/system` and reloads systemd. It does
not create secrets, enable services, or start processes. Before starting an instance, the CD
system must atomically provision `/etc/vogelvrij/test.env` or `/etc/vogelvrij/prod.env` as a
root-owned mode-0600 file. Use `deploy/systemd/test.env.example` and `prod.env.example` as the
complete variable contract for both Compose and systemd, but construct the real file from the
CD secret store rather than editing or committing it. `DATABASE_URL` must match the
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_PORT` values used to
initialize the database. The raw password belongs in `POSTGRES_PASSWORD`; URL-significant
characters must be percent-encoded in the copy embedded in `DATABASE_URL`.

The default web ports are intentionally separate and loopback-only: test uses 8767 and
production uses 8766. Enable and start the desired environment after its database is healthy
and its environment file is installed:

```sh
# Test
sudo systemctl enable --now vogelvrij-collector@test.service vogelvrij-web@test.service

# Production
sudo systemctl enable --now vogelvrij-collector@prod.service vogelvrij-web@prod.service
```

Inspect them with, for example:

```sh
systemctl status vogelvrij-collector@test.service vogelvrij-web@test.service
journalctl -u vogelvrij-collector@test.service -u vogelvrij-web@test.service -f
```

The collector template uses `Restart=always`; the web template uses `Restart=on-failure`.
Both restart ten seconds after an unexpected exit, start at boot when enabled, wait for basic
network/Docker ordering, and receive all runtime configuration through the protected
environment file. The applications validate numeric settings before starting. Docker Compose
remains responsible for starting and restarting PostgreSQL. A database failure is retried on
the collector's next scheduled run; the web page returns HTTP 503 while its database is
unavailable.

### Test and production database deployments

The repository has separate, self-contained Compose files for continuous deployment. They do
not change or extend the developer `docker-compose.yml`, so the normal local database remains
the `vogelvrij` Compose project on port 5433.

| Environment | Compose file | Project | Host binding | Default database/user |
| --- | --- | --- | --- | --- |
| Development | `docker-compose.yml` | directory-derived | all interfaces, port 5433 | `vogelvrij` |
| Test | `docker-compose.test.yml` | `vogelvrij-test` | `127.0.0.1:5434` | `vogelvrij_test` |
| Production | `docker-compose.prod.yml` | `vogelvrij-prod` | `127.0.0.1:5435` | `vogelvrij_prod` |

Test and production use different Compose project names, image names, host ports, and named
volumes. They can therefore run beside each other and beside the developer database without
sharing data or claiming the same port. Both deployment databases use the `unless-stopped`
restart policy, so Docker restarts them after a daemon or server restart unless an operator
explicitly stopped them. Their ports bind only to loopback and are not directly exposed on a
public network interface.

The deployment files deliberately have no default password. Provision the complete protected
environment file from the CD secret store; do not write secrets into a Compose file or commit
the real environment file. Pass the same file to Compose that systemd will load, so database
name, user, password, and port cannot silently diverge. Example deployment commands are:

```sh
sudo docker compose --env-file /etc/vogelvrij/test.env \
  -f docker-compose.test.yml up -d --build --wait
sudo docker compose --env-file /etc/vogelvrij/prod.env \
  -f docker-compose.prod.yml up -d --build --wait
```

Applications running on the host use the corresponding loopback URL. These examples assume
the default database and user names; insert the secret using the CD system rather than putting
it in shell history or logs:

```text
test:       postgresql+psycopg://vogelvrij_test:<password>@127.0.0.1:5434/vogelvrij_test
production: postgresql+psycopg://vogelvrij_prod:<password>@127.0.0.1:5435/vogelvrij_prod
```

Always name the intended deployment file explicitly. Plain `docker compose up` continues to
operate only the development environment. Likewise, use the matching file for status, logs,
exec, stop, and removal commands. Never add `-v` to `docker compose down` unless deletion of
that environment's PostgreSQL data was explicitly intended.

## Collect Brussels Airport wind

Run `vogelvrij-collect-wind` to fetch the latest EBBR METAR from the
[Aviation Weather Center Data API](https://aviationweather.gov/data/api/) and store its
`wdir`/`wspd` values in `wind_observations`. This is a separate one-shot command; schedule it
independently from aircraft collection. It prints the direction in degrees and speed in knots,
stores the speed in metres per second, and retains the complete METAR object in `raw_data`.
`--no-store` fetches and prints without opening the database.

Repeated calls for the same METAR observation time do not insert another row. An empty API
response, or a report with missing/variable wind direction or missing speed, inserts nothing.
Most METARs update hourly; choose a modest polling interval and respect the provider's
published rate limits. The command does not install a scheduler or run continuously.

For the separate EBBR wind **forecast**, apply migration 003 to an existing database, then run
`vogelvrij-collect-taf` at the cadence you choose (or `--no-store` to print only):

```sh
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U vogelvrij -d vogelvrij \
  -f /docker-entrypoint-initdb.d/003_taf_forecasts.sql
vogelvrij-collect-taf
```

The command calls the Aviation Weather Center TAF JSON endpoint, prints the forecast groups,
and stores each distinct bulletin once in `taf_forecasts`, separate from measured
`wind_observations`. It does not install a scheduler, loop, or backoff. Migration 003 has already
been applied to this project's current local database; a fresh Compose volume runs it at init.

## Database

Start the PostgreSQL 16 database with PostGIS:

```sh
docker compose up -d db
```

The database image is built from the official multi-architecture PostgreSQL image and installs
PostGIS from Debian packages, so local development works on both Apple Silicon and AMD64.

On the first start, `database/migrations/001_initial.sql` creates:

- `collection_runs`, containing request parameters and all top-level API response metadata;
- `aircraft_observations`, containing nullable analytical columns and the complete aircraft JSON;
- `flight_movements`, holding detected approach encounters and ready for later origin/destination enrichment;
- `wind_observations`, independently timestamped wind direction and speed measurements.

The collector stores results by default in the local database on port `5433`:

```sh
vogelvrij-collect --lat 50.8503 --lon 4.3517 --radius-nm 25
```

Set `DATABASE_URL` to use another database. Use `--no-store` only when a print-only collection
is intentional:

```sh
vogelvrij-collect --lat 50.8503 --lon 4.3517 --radius-nm 25 --no-store
```

All provider fields are nullable because ADS-B messages do not always contain every field.
The `raw_data` JSONB column preserves unrecognized and future fields. The PostGIS `position`
column is generated from longitude and latitude for efficient regional analysis.
Migration 006 adds a B-tree index on `aircraft_observations.collection_run_id` for latest-run
and ten-run map lookups. On an existing volume, apply it while collection continues:

```sh
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U vogelvrij -d vogelvrij \
  -f /docker-entrypoint-initdb.d/006_observation_collection_run_index.sql
```

`CREATE INDEX CONCURRENTLY` must run outside a transaction. A fresh volume runs this
migration at initialization. The index does not change or delete observation rows.

Before insertion, aircraft explicitly reported as `ground` are discarded. Aircraft above
10,000 feet are also discarded; barometric altitude is preferred, with geometric altitude used
when barometric altitude is unavailable. Aircraft with no numeric altitude are discarded.
Aircraft whose API `t` type code is in `EXCLUDED_AIRCRAFT_TYPES` in
`src/vogelvrij/repository.py` are also discarded. The list currently contains `C152` and
`P28A`; add more ICAO type codes there as needed. Missing type codes are not excluded.

Aircraft must have a numeric latitude and longitude. Collection intentionally stores eligible
positions even outside the approach polygons so they remain available for map/history views.
The four corridors in `src/vogelvrij/geography.py` are applied later when deciding whether a
stored observation qualifies as a movement. See `HANDOVER.md` for current geometry limitations.

After each stored collection, qualifying observations are linked to a `flight_movements` row.
A movement requires a position inside one of the four approach corridors, ground track within
10° of its nominal approach heading (25LR: 240–260°, 07LR: 60–80°, 01: 0–20°, 19: 180–200°),
ground speed of at least 100 knots, and an ICAO aircraft address. The corridor code is stored
as `25LR`, `07LR`, `01`, or `19`. A repeat observation of the same aircraft within 15 minutes
of the movement's creation updates that movement, even if its callsign changes. At exactly
15 minutes or later, a new movement can be created. Missing aircraft addresses cannot be
reliably deduplicated and do not produce movements. This is a heuristic **approach encounter**,
not proof of a landing. `--no-store` does not create a movement.

At first insertion only, a new movement snapshots the latest stored EBBR METAR wind direction
in degrees and speed in knots, and the expected approach calculated by the same gust-aware,
wind-only rule as the page's "Verwachte naderingsbaan". A missing METAR leaves all three fields
empty; no wind-feasible runway leaves the expected approach empty. Later sightings do not
change the snapshot. The METAR can be stale, and this theoretical approach is not an observed
or ATC-assigned runway. Existing movements are not backfilled because their insertion-time
wind cannot reliably be inferred later.

Apply the additive migration to an existing database before restarting the collector or web
server with this code (adjust database credentials if customized):

```sh
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U vogelvrij -d vogelvrij \
  -f /docker-entrypoint-initdb.d/005_movement_wind_snapshot.sql
```

A fresh database volume runs migration 005 automatically during initialization. Keep the
existing PostgreSQL volume; the migration adds nullable columns without deleting rows.

An existing PostgreSQL volume needs the additive migration before the updated collector runs:

```sh
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U vogelvrij -d vogelvrij \
  -f /docker-entrypoint-initdb.d/002_flight_movement_detection.sql
```

It has already been applied to this project's current local database. To display every movement:

```sh
./scripts/show-movements.sh
```

`wind_observations` stores wind speed canonically in metres per second; movement snapshots
retain the displayed METAR speed in knots. Provider-specific units should be converted during
ingestion, while the original payload can be retained in `raw_data`.

### Display the latest stored aircraft

With the database running, show flight number, barometric height, and direction for every
distinct aircraft observed so far:

```sh
./scripts/show-aircraft.sh
```

Aircraft are deduplicated by their ICAO transponder address (`hex`), and the newest observation
is displayed. Records without an aircraft identifier remain separate because they cannot be
reliably correlated. Missing provider values are displayed as `-`. Height is shown in feet,
direction is the true track over ground in degrees, and the latest observation time is shown in
UTC.

### Map the latest collection

Set `GOOGLE_MAPS_API_KEY` in your shell, then generate the page from the **latest collection
run** already stored in PostgreSQL (no new ADSB.lol request):

```sh
export GOOGLE_MAPS_API_KEY='your-restricted-browser-key'
vogelvrij-map
python3 -m http.server 8765 --directory generated
```

Open `http://localhost:8765/planes_map.html`. The default output is
`generated/planes_map.html`; use `vogelvrij-map --output /path/to/map.html` to change it.
The generated file is ignored by Git and restricted to the local user, but it **contains the
browser API key**. Do not publish or share it as a confidential file. Restrict the key in Google
Cloud to Maps JavaScript API and the intended website/referrer. A locally opened `file://` page
may not work with website restrictions, which is why the example serves it over HTTP.

The map shows a labeled search-center marker and the full radius circle from the latest run,
the `25LR Approach`, `7LR Approach`, `01 Approach`, and `19 Approach` polygons, and all stored aircraft with
positions from the latest run. If that run contains no qualifying aircraft, the map shows an
empty-state message rather than displaying older aircraft. The Dutch left-hand list shows the
latest sighting first, with times in Belgian local time.
The 01/19 polygons are broad, approximate corridors toward about 15 nautical miles from EBBR;
they are map guides, not published approach-procedure boundaries or active *observation*
collection filters. Runway-threshold inclusion is not required for these inbound corridors.
See `HANDOVER.md` for the broader limitations before interpreting runway-specific counts.

### Map tracks from the ten newest collections

With the same `GOOGLE_MAPS_API_KEY` set and the database running, generate a separate page:

```sh
vogelvrij-map-history
python3 -m http.server 8765 --directory generated
```

Open `http://localhost:8765/planes_history_map.html`. The page groups positioned observations
from the ten newest stored runs by aircraft ICAO address (`hex`). It draws a line through each
aircraft's successive distinct positions, small dots at earlier positions, and only one red
arrow at the latest observed position.
Its Dutch left-hand list orders aircraft by their latest sighting, newest first, and shows
the sighting time in Belgian local time.
Aircraft without a `hex` are shown separately because they cannot be matched reliably. The
page is a static snapshot: rerun the command after collecting new data. It has the same browser
key exposure and Git-ignore precautions as the single-run map.

### Serve the public information page

With the migrated database running, launch the read-only page:

```sh
export GOOGLE_MAPS_API_KEY='your-restricted-browser-key'
vogelvrij-web
```

`VOGELVRIJ_WEB_HOST` and `VOGELVRIJ_WEB_PORT` provide environment defaults for the equivalent
command-line flags; explicit flags take precedence. Open `http://127.0.0.1:8766/`. Use
`vogelvrij-web --host 0.0.0.0 --port 8766` only when
intentionally exposing the process through an appropriately configured reverse proxy. Set
`DATABASE_URL` for a different PostgreSQL instance. Data requests read the current database;
the browser receives display-only HTML/JSON and no database credentials. The history-map iframe
does receive the browser Maps key, which is visible to page viewers: restrict it to Maps JavaScript
API and authorized website referrers. If the key is unset or no collection runs exist, the frame
shows an explanatory unavailable state. An unavailable database returns HTTP 503, not a misleading
zero. This is a development server; HTTPS,
deployment, access controls, and collection scheduling are not configured here.

An open page refreshes its counts, latest EBBR wind reading, TAF forecast, and ten-row movement table every 30 seconds through the
read-only same-origin `/api/movements` JSON endpoint. It also refreshes when a hidden tab becomes
visible again. A failed refresh leaves the last displayed values in place and shows a warning;
the next interval retries. A normal page reload still renders current values server-side, so
the page remains useful without JavaScript. Polling also rolls the daily counts over at Belgian
midnight without requiring a new database write.

The historical overview below the recent-movement table shows stacked totals for each of the
four approach corridors on each of the last seven Belgian calendar days (including today,
shown first), and an hourly stacked chart for the last 24 hours (including the current partial hour).
The hourly bars fit the chart width without horizontal scrolling. A day's
row shows its corridor counts, total, and number of collection runs. Hourly bars expose exact
counts and run coverage in their labels, with the total printed below each hour. Only detected
movements produce colored bars; hours with no detections have no bar. Both charts use
`flight_movements.created_at`, so they count detected approach encounters rather than aircraft
observations or confirmed landings. The 30-second poll refreshes both charts. A zero with no
collection runs is not evidence that no aircraft flew. Local labels distinguish the repeated
hour during the autumn daylight-saving change; the daily boundary follows Belgian time.

Below the movement table, a lazy-loaded same-origin frame serves `/maps/history`. This route
renders the existing `vogelvrij-map-history` view directly from the ten newest collection runs;
it does not depend on or expose a generated map file, and its tracks are **not necessarily** the
ten flights in the movement table. The map loads once when the frame becomes visible, shows its
last load date and time in Belgian local time, and does **not** reload when the 30-second data poll
sees a new collection run. Visitors can use **Kaart vernieuwen** to reload the latest ten runs
manually; each such reload may count as another Google Maps load. A visitor can also open the map
in a full tab. The main page allows
only same-origin framing; the map route has a separate nonce-based CSP for Google's scripts and
map resources. Review Google Maps billing, attribution, key restrictions, and source-data license
before making the site public.

The page reproduces the text and layout of [Bruegelvogelvrij](https://bruegelvogelvrij.be/)
and links to its four original images, so those images require that site to remain available.
The first half-width card counts `07LR` movements; a matching card shows the newest stored
EBBR METAR wind direction and speed in degrees and knots, with an arrow pointing toward the
direction the wind is blowing. The text still reports the METAR direction of origin. It also
shows the observation time in Belgian local time and a wind-only expected landing approach,
calculated with the same runway preference and gust-aware limits as the TAF prognosis below.
This is where aircraft should approach based on the measured wind, not a report of the runway
they are actually using. The card has an
empty state until a usable wind reading has been collected. The cards stack on smaller screens.
The next three cards count `25LR`, `01`, and `19` movements
whose `created_at` is within the current Europe/Brussels calendar day.
Each movement card also shows estimated headwind or tailwind and crosswind in knots, derived
from the latest stored EBBR METAR. The calculation uses `speed × cos(|wind direction − runway
heading|)` for the signed along-runway component and the absolute value of `speed × sin(...)`
for crosswind. The shared 07LR and 25LR cards use nominal magnetic headings 070° and 250°;
01 and 19 use 010° and 190°. METAR direction is true, so these are quick estimates without
a magnetic-variation correction, not operational runway wind data. If no wind is stored, the
cards show an unavailable message.
Each card has a small status light: red when the unrounded tailwind is at least 7 kt on
25LR or greater than 3 kt on 07LR/01/19, or the crosswind magnitude is at least 20 kt on
any corridor; green otherwise, and grey
when no wind reading is available. These are display thresholds, not a safety clearance;
the card text and lights update together during the page's 30-second poll.

Below the four counter cards, the full-width TAF timeline shows forecast wind periods with
arrows pointing where the wind blows, exact origin direction, speed and any gusts in knots,
and issue/validity times in Belgian local time. A hatched BECMG card spans the reported
transition interval; a windless TEMPO group does not create a calm-wind card. The newest
currently valid stored EBBR bulletin takes priority. If none is currently valid, the newest
stored bulletin is still shown, labelled "Nog niet geldig" or "Verlopen" as appropriate;
only an absent or unrenderable bulletin shows an unavailable state. Forecasts never drive the measured-wind status
lights. Each card also shows an indicative landing-approach prognosis from TAF wind alone:
25LR is preferred if either runway end stays below 7 kt tailwind and 20 kt crosswind.
Otherwise, the feasible 19, 07LR, or 01 approach closest to the wind's origin is shown.
The alternative runways allow exactly 3 kt tailwind, but not more; forecast gusts count
when present. Calculations use the runways' [published true bearings](https://ops.skeyes.be/html/belgocontrol_static/eaip/eAIP_Next/html/eAIP/EB-AD-2.EBBR-en-GB.html)
to match TAF wind directions. A BECMG card shows the possible change between previous and
new prevailing approaches; explicit temporary wind has its own prognosis. Missing wind or
no feasible runway shows no reliable prediction. Actual ATC runway choice also depends on
time, availability and other conditions; this is not operational advice. The timeline stacks
vertically on narrow screens.

The table shows the ten latest movement rows across all dates, newest detection first, with callsign,
"Gebruikte baan" (the detected corridor), adjacent "Theoretische baan" (the stored wind-only
prediction at movement creation), stored closest-reference-point altitude, and first/last
observation times. A dash means no prediction was available, including old rows. For a
movement with a prediction, the theoretical cell is green when its code matches the detected
corridor and red when it differs; this color comparison does not establish an actual landing
runway. For each movement, every qualifying linked observation is compared with its corridor's reference point;
the altitude and distance in `flight_movements` change only when an observation is closer.
Barometric altitude is preferred, with geometric altitude as fallback, and the altitude is
displayed in feet (or a dash when unavailable). The 01 and 07LR points are supplied reference
coordinates; 25LR uses a provisional midpoint between the published 25L/25R FAFs, and 19 uses
a synthetic point at the same threshold distance as the 01 reference. Those two points are not
published FAFs. Apply migration 004 and run `python scripts/backfill-faf-altitudes.py` to
populate existing movements without removing observations. Times are displayed in Belgian local
time. These are detector-created approach
encounters, **not verified landings**; the detector may miss or split flights and the present
geographic/detection caveats in `HANDOVER.md` still apply. The page includes this warning and
source attribution. Do not publish it as a definitive runway traffic tally until the detector,
regional geometry, coverage, source licensing, and deployment setup have been reviewed.

### Export and restore CSV data

With the source database running and the Python package installed, export a consistent snapshot:

```sh
python scripts/export-database.py backups/2026-09-20
```

The destination must be new. It receives one headered CSV per application table and a
`manifest.json` containing column names, row counts, and SHA-256 checksums. PostGIS extension
tables are excluded, and generated columns such as `aircraft_observations.position` are rebuilt
by PostgreSQL. Keep the directory private: CSV files contain full raw provider payloads and
may contain future enrichment data. `backups/` is Git-ignored.

Create a separate, fresh database with the same migrations before importing. For example,
this starts a second Compose project without touching the existing `postgres_data` volume:

```sh
POSTGRES_PORT=5434 docker compose -p vogelvrij-restore up -d db
DATABASE_URL=postgresql+psycopg://vogelvrij:vogelvrij@localhost:5434/vogelvrij \
  python scripts/import-database.py backups/2026-09-20
```

Use matching credentials if `POSTGRES_*` was customized. The importer checks the CSV hashes,
table and column layout, and that every target application table is empty. It imports in
foreign-key order, verifies row counts, and advances serial/identity sequences. A failed
import rolls back inserted rows. It never clears an existing database. This CSV format carries
data only; database schema, PostGIS, indexes, and constraints come from the migrations.

### Erase all collected data

To delete every aircraft observation, collection run, flight enrichment, wind observation, and TAF forecast
while preserving the database schema:

```sh
./scripts/reset-database.sh
```

The script requires typing `ERASE` before it proceeds. For non-interactive use, the confirmation
can be supplied explicitly:

```sh
./scripts/reset-database.sh --yes
```

This operation cannot be undone unless the database has been backed up.

## Development checks

```sh
pytest
ruff check .
```

## Data-source behavior

- Endpoint: `https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{radius_nm}`
- User-Agent: `BrusselsPlaneTracker/1.0`
- Request timeout: 15 seconds
- Responses without valid aircraft positions are ignored.
- Radius is restricted to 250 nautical miles or less.
- API rate limits are dynamic; scheduled collection must use a conservative interval and backoff.
