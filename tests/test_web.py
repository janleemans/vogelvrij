import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from vogelvrij.web import (
    SCRIPT,
    TEMPLATE,
    forecast_display,
    history_data,
    latest_taf,
    latest_wind,
    make_handler,
    map_csp,
    movement_data,
    render_page,
    snapshot,
    theoretical_runway_cell,
    today_bounds,
    wind_component,
    wind_display,
    wind_light,
)


def test_today_bounds_follow_brussels_daylight_saving_time():
    start, end = today_bounds(datetime(2026, 3, 29, 12, tzinfo=timezone.utc))
    assert start == datetime(2026, 3, 28, 23, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 29, 22, tzinfo=timezone.utc)


def test_movement_data_counts_only_known_corridors_and_limits_recent_rows():
    class FakeSession:
        def execute(self, query):
            sql = str(query)
            assert "flight_movements.created_at >= :created_at_1" in sql
            assert "flight_movements.created_at < :created_at_2" in sql
            return [("07LR", 4), ("19", 2), (None, 12)]

        def scalars(self, query):
            sql = str(query)
            assert "LIMIT :param_1" in sql
            assert "flight_movements.faf_altitude_ft" in sql
            assert query._limit_clause.value == 10
            return SimpleNamespace(all=lambda: ["recent"])

    counts, recent = movement_data(FakeSession(), datetime.now(timezone.utc))
    assert counts == {"07LR": 4, "25LR": 0, "01": 0, "19": 2}
    assert recent == ["recent"]


def test_taf_selection_prefers_current_bulletin_then_falls_back_to_latest():
    now = datetime(2026, 9, 20, 11, 45, tzinfo=timezone.utc)
    current = object()
    newest = object()

    class FakeSession:
        def __init__(self, results):
            self.results = iter(results)
            self.queries = []

        def scalars(self, query):
            self.queries.append(str(query))
            return SimpleNamespace(first=lambda: next(self.results))

    session = FakeSession([current])
    assert latest_taf(session, now) is current
    assert len(session.queries) == 1
    assert "taf_forecasts.valid_from <=" in session.queries[0]
    assert "taf_forecasts.valid_to >" in session.queries[0]

    session = FakeSession([None, newest])
    assert latest_taf(session, now) is newest
    assert len(session.queries) == 2
    assert "taf_forecasts.valid_from <=" not in session.queries[1]
    assert "ORDER BY taf_forecasts.issued_at DESC, taf_forecasts.id DESC" in session.queries[1]


def test_history_buckets_distinguish_repeated_dst_hour_and_show_collection_coverage():
    class FakeSession:
        def execute(self, query):
            sql = str(query)
            if "flight_movements" in sql:
                assert "flight_movements.created_at >= :created_at_1" in sql
                assert "GROUP BY" in sql
                return [
                    (datetime(2026, 10, 25, 0), "07LR", 1),
                    (datetime(2026, 10, 25, 1), "19", 1),
                    (datetime(2026, 10, 25, 1), None, 3),
                ]
            assert "collection_runs.requested_at >= :requested_at_1" in sql
            return [(datetime(2026, 10, 25, 0), 1)]

    now = datetime(2026, 10, 25, 1, 45, tzinfo=timezone.utc)
    history = history_data(FakeSession(), now)
    assert len(history["days"]) == 7
    assert len(history["hours"]) == 24
    today = history["days"][0]
    assert today["date"] == "2026-10-25"
    assert today["counts"] == {"07LR": 1, "25LR": 0, "01": 0, "19": 1}
    assert (today["total"], today["runs"]) == (2, 1)
    repeated_hours = [hour for hour in history["hours"] if hour["label"].startswith("25/10 02")]
    assert [hour["label"] for hour in repeated_hours] == ["25/10 02:00 CEST", "25/10 02:00 CET"]
    assert [(hour["total"], hour["runs"]) for hour in repeated_hours] == [(1, 1), (1, 0)]
    assert history["days"][-1]["total"] == 0
    assert history["days"][0]["date"] > history["days"][1]["date"]


def test_history_is_rendered_on_initial_page_and_in_snapshot():
    class EmptySession:
        def execute(self, query):
            return []

    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    history = history_data(EmptySession(), now)
    page = render_page(dict.fromkeys(("07LR", "25LR", "01", "19"), 0), [], now,
                       history=history)
    assert 'id="history-daily"' in page
    assert 'id="history-hourly"' in page
    assert page.count('class="daily-row"') == 7
    assert page.count('class="hour-column"') == 24
    assert page.count('class="hour-total" aria-hidden="true">0</span>') == 24
    assert "{{HISTORY_" not in page
    assert snapshot({}, [], now, history=history)["history"] == history


def test_latest_wind_selects_newest_ebbr_reading():
    class FakeSession:
        def scalars(self, query):
            sql = str(query)
            assert "wind_observations.source = :source_1" in sql
            assert "wind_observations.observed_at DESC" in sql
            assert "wind_observations.id DESC" in sql
            assert query._limit_clause.value == 1
            return SimpleNamespace(first=lambda: "wind")

    assert latest_wind(FakeSession()) == "wind"


def test_render_page_escapes_provider_fields_and_shows_empty_state():
    now = datetime(2026, 9, 19, 10, tzinfo=timezone.utc)
    movement = SimpleNamespace(
        callsign="<script>alert(1)</script>",
        aircraft_icao="abc123",
        approach_corridor="07LR",
        expected_approach="25LR",
        faf_altitude_ft=2400,
        created_at=now,
        first_observed_at=now,
        last_observed_at=None,
        origin_airport_iata=None,
        origin_airport_icao=None,
        destination_airport_iata="BRU",
        destination_airport_icao=None,
    )
    counts = {"07LR": 3, "25LR": 2, "01": 1, "19": 0}
    page = render_page(counts, [movement], now)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<script>alert(1)</script>" not in page
    assert "19/09/2026 12:00" in page
    assert "<th>Hoogte</th>" in page
    assert "<th>Gebruikte baan</th><th>Theoretische baan</th>" in page
    assert '<td>07LR</td><td class="theoretical-runway-mismatch"' in page
    assert 'Wijkt af van de gedetecteerde baan">25LR</td>' in page
    assert "<td>2400 ft</td>" in page
    assert "Toestel (ICAO)" not in page
    assert "<th>Gedetecteerd</th>" not in page
    assert "<th>Herkomst</th>" not in page
    assert "<th>Bestemming</th>" not in page
    assert 'colspan="6"' in render_page(counts, [], now)
    assert "Landingen over Dilbeek vandaag:" in page
    assert "{{" not in page
    assert "Nog geen bewegingen geregistreerd." in render_page(counts, [], now)
    assert "Nog geen windmeting beschikbaar." in page
    assert page.count("Windcomponenten niet beschikbaar.") == 4
    assert page.count('class="wind-light wind-light-unknown"') == 4
    assert "Geen windmeting beschikbaar" in page
    assert 'id="wind-approach-content" hidden' in page


def test_theoretical_runway_cell_colors_matches_and_keeps_missing_values_neutral():
    assert 'class="theoretical-runway-match"' in theoretical_runway_cell("25LR", "25LR")
    assert 'class="theoretical-runway-mismatch"' in theoretical_runway_cell("07LR", "25LR")
    assert theoretical_runway_cell("07LR", None) == "<td>—</td>"
    assert theoretical_runway_cell(None, "25LR") == "<td>25LR</td>"
    assert "&lt;script&gt;" in theoretical_runway_cell("07LR", "<script>")


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        (70, "Rugwind 12.8 kt · Zijwind 2.3 kt"),
        (250, "Tegenwind 12.8 kt · Zijwind 2.3 kt"),
        (10, "Rugwind 8.4 kt · Zijwind 10.0 kt"),
        (190, "Tegenwind 8.4 kt · Zijwind 10.0 kt"),
    ],
)
def test_wind_components_for_all_corridor_headings(heading, expected):
    assert wind_component(240, 13, heading) == expected


def test_crosswind_magnitude_handles_angle_past_180_degrees():
    assert wind_component(350, 10, 10) == "Tegenwind 9.4 kt · Zijwind 3.4 kt"


@pytest.mark.parametrize(
    ("direction", "speed", "heading", "tailwind_limit", "expected"),
    [
        (180, 7, 0, 7, "red"),
        (180, 6.99, 0, 7, "green"),
        (180, 3, 0, 3, "green"),
        (180, 3.01, 0, 3, "red"),
        (90, 20, 0, 7, "red"),
        (90, 20, 0, 3, "red"),
        (90, 19.99, 0, 3, "green"),
        (0, 20, 0, 3, "green"),
    ],
)
def test_wind_light_uses_inclusive_unrounded_tailwind_and_crosswind_limits(
    direction, speed, heading, tailwind_limit, expected
):
    assert wind_light(direction, speed, heading, tailwind_limit) == expected


@pytest.mark.parametrize(
    ("wind_direction", "corridor", "speed", "expected", "label"),
    [
        (250, "07LR", 5, "red", "rugwind meer dan 3 kt"),
        (70, "25LR", 5, "green", "Onder de ingestelde winddrempels"),
        (70, "25LR", 7, "red", "rugwind minstens 7 kt"),
        (190, "01", 5, "red", "rugwind meer dan 3 kt"),
        (10, "19", 5, "red", "rugwind meer dan 3 kt"),
    ],
)
def test_wind_display_uses_corridor_specific_tailwind_limits(
    wind_direction, corridor, speed, expected, label
):
    wind = SimpleNamespace(
        observed_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        direction_degrees=wind_direction,
        speed_mps=speed * 0.514444,
        raw_data={"wdir": wind_direction, "wspd": speed},
    )
    values = wind_display(wind)
    assert values["lights"][corridor] == expected
    assert label in values["light_labels"][corridor]


def test_wind_display_uses_original_metar_values_and_local_time():
    wind = SimpleNamespace(
        observed_at=datetime(2026, 9, 19, 17, 50, tzinfo=timezone.utc),
        direction_degrees=0.0,
        speed_mps=13 * 0.514444,
        raw_data={"wdir": 360, "wspd": 13},
    )
    values = wind_display(wind)
    assert values["direction"] == "360°"
    assert values["speed"] == "13 kt"
    assert values["bearing"] == 180.0
    assert values["observed"] == "19/09/2026 19:50"
    assert values["approach"] == "25LR"
    assert set(values["components"]) == {"07LR", "25LR", "01", "19"}
    assert values["lights"]["19"] == "red"
    assert values["lights"]["01"] == "green"
    counts = {"07LR": 3, "25LR": 2, "01": 1, "19": 0}
    page = render_page(counts, [], wind.observed_at, wind=wind)
    assert 'transform="rotate(180 50 50)"' in page
    assert 'id="wind-direction">360°' in page
    assert 'id="wind-speed">13 kt' in page
    assert 'id="wind-approach">25LR' in page
    assert "Te verwachten nadering op basis van gemeten wind" in page
    assert 'id="wind-content" hidden' not in page
    assert 'id="wind-empty" hidden' in page
    assert 'id="wind-components-07lr">' in page
    assert 'class="wind-light wind-light-red" id="wind-light-19"' in page
    assert 'class="wind-light wind-light-green" id="wind-light-01"' in page
    assert "Windcomponenten niet beschikbaar." not in page
    assert snapshot(counts, [], wind.observed_at, wind=wind)["wind"] == values


def test_wind_approach_uses_metar_gust_and_stored_gust_fallback():
    observed_at = datetime(2026, 9, 20, tzinfo=timezone.utc)
    wind = SimpleNamespace(
        observed_at=observed_at,
        direction_degrees=180,
        speed_mps=8 * 0.514444,
        gust_speed_mps=30 * 0.514444,
        raw_data={"wdir": 180, "wspd": 8, "wgst": 30},
    )
    assert wind_display(wind)["approach"] == "19"
    wind.raw_data = {"wdir": 180, "wspd": 8}
    assert wind_display(wind)["approach"] == "19"


def test_json_endpoint_exposes_only_display_fields():
    movement = SimpleNamespace(
        callsign="<script>x</script>",
        aircraft_icao="abc123",
        approach_corridor="07LR",
        expected_approach=None,
        faf_altitude_ft=None,
        created_at=datetime(2026, 9, 19, 10, tzinfo=timezone.utc),
        first_observed_at=None,
        last_observed_at=None,
        origin_airport_iata=None,
        origin_airport_icao=None,
        destination_airport_iata=None,
        destination_airport_icao=None,
        raw_data={"private": "not public"},
    )
    handler = object.__new__(make_handler(object()))
    handler.path = "/api/movements"
    sent = []
    handler.send_body = lambda body, content_type: sent.append((body, content_type))
    with patch("vogelvrij.web.Session"), patch(
        "vogelvrij.web.latest_run_id", return_value=12
    ), patch(
        "vogelvrij.web.latest_taf", return_value=None
    ), patch(
        "vogelvrij.web.latest_wind",
        return_value=SimpleNamespace(
            observed_at=datetime(2026, 9, 19, 10, tzinfo=timezone.utc),
            direction_degrees=240.0,
            speed_mps=13 * 0.514444,
            raw_data={"wdir": 240, "wspd": 13, "rawOb": "METAR EBBR"},
        ),
    ), patch(
        "vogelvrij.web.movement_data",
        return_value=({"07LR": 1, "25LR": 0, "01": 0, "19": 0}, [movement]),
    ):
        handler.do_GET()
    body, content_type = sent[0]
    payload = json.loads(body)
    assert content_type == "application/json; charset=utf-8"
    assert payload["counts"]["07LR"] == 1
    assert payload["map_run_id"] == 12
    assert payload["wind"]["direction"] == "240°"
    assert payload["wind"]["speed"] == "13 kt"
    assert payload["wind"]["bearing"] == 60.0
    assert payload["wind"]["approach"] == "25LR"
    assert payload["wind"]["components"]["07LR"] == "Rugwind 12.8 kt · Zijwind 2.3 kt"
    assert payload["wind"]["lights"] == {
        "07LR": "red", "25LR": "green", "01": "red", "19": "green"
    }
    assert "rugwind meer dan 3 kt" in payload["wind"]["light_labels"]["07LR"]
    assert payload["wind"]["light_labels"]["25LR"] == "Onder de ingestelde winddrempels"
    assert payload["rows"][0][0] == "<script>x</script>"
    assert payload["rows"][0] == ["<script>x</script>", "07LR", "—", "—", "—", "—"]
    assert "private" not in body.decode("utf-8")
    assert "rawOb" not in body.decode("utf-8")
    assert payload["forecast"] is None
    assert len(payload["history"]["days"]) == 7
    assert len(payload["history"]["hours"]) == 24


def test_forecast_timeline_distinguishes_becmg_and_ignores_windless_tempo():
    taf = SimpleNamespace(
        id=7,
        issued_at=datetime(2026, 9, 19, 17, tzinfo=timezone.utc),
        valid_from=datetime(2026, 9, 19, 18, tzinfo=timezone.utc),
        valid_to=datetime(2026, 9, 21, tzinfo=timezone.utc),
        raw_data={"fcsts": [
            {"timeFrom": 1789840800, "timeTo": 1789898400, "fcstChange": None,
             "wdir": 240, "wspd": 12, "wgst": None},
            {"timeFrom": 1789866000, "timeTo": 1789891200, "fcstChange": "TEMPO",
             "wdir": None, "wspd": None},
            {"timeFrom": 1789898400, "timeBec": 1789905600, "timeTo": 1789948800,
             "fcstChange": "BECMG", "wdir": 300, "wspd": 12, "wgst": 20},
        ]},
    )
    now = datetime(2026, 9, 20, 8, tzinfo=timezone.utc)
    data = forecast_display(taf, now)
    assert [period["kind"] for period in data["periods"]] == [
        "prevailing", "transition", "prevailing"
    ]
    assert data["periods"][0]["bearing"] == 60
    assert data["periods"][1]["from"] == "20/09/2026 12:00"
    assert data["periods"][1]["to"] == "20/09/2026 14:00"
    assert data["periods"][2]["speed"] == "12 kt · stoten 20 kt"
    assert [period["approach"] for period in data["periods"]] == [
        "25LR", "25LR", "25LR"
    ]
    page = render_page({"07LR": 0, "25LR": 0, "01": 0, "19": 0}, [], now, taf=taf)
    assert 'data-forecast-id="7"' in page
    assert "Geleidelijke overgang" in page
    assert "Wind uit 300°" in page
    assert "Wind uit 240°" in page
    assert "Verwachte naderingsbaan" in page
    assert "{{" not in page
    assert data["status"] == "current"
    assert forecast_display(taf, taf.valid_from - timedelta(seconds=1))["status"] == "upcoming"
    assert forecast_display(taf, taf.valid_to)["status"] == "expired"
    assert snapshot({"07LR": 0, "25LR": 0, "01": 0, "19": 0}, [],
                    taf.valid_to, taf=taf)["forecast"]["status_label"] == "Verlopen"
    assert "Actueel" in page
    stale_page = render_page({"07LR": 0, "25LR": 0, "01": 0, "19": 0}, [],
                             taf.valid_to, taf=taf)
    assert "Verlopen" in stale_page
    assert 'id="forecast-empty" hidden' in stale_page


def test_forecast_transition_and_temporary_wind_keep_distinct_prognoses():
    taf = SimpleNamespace(
        id=8,
        issued_at=datetime(2026, 9, 19, 17, tzinfo=timezone.utc),
        valid_from=datetime(2026, 9, 19, 18, tzinfo=timezone.utc),
        valid_to=datetime(2026, 9, 21, tzinfo=timezone.utc),
        raw_data={"fcsts": [
            {"timeFrom": 1789840800, "timeTo": 1789898400, "wdir": 240, "wspd": 12},
            {"timeFrom": 1789866000, "timeTo": 1789891200,
             "fcstChange": "TEMPO", "wdir": 180, "wspd": 30},
            {"timeFrom": 1789898400, "timeBec": 1789905600, "timeTo": 1789948800,
             "fcstChange": "BECMG", "wdir": 90, "wspd": 20},
        ]},
    )
    now = datetime(2026, 9, 20, 8, tzinfo=timezone.utc)
    periods = forecast_display(taf, now)["periods"]
    assert [(period["kind"], period["approach"]) for period in periods] == [
        ("prevailing", "25LR"),
        ("temporary", "19"),
        ("transition", "25LR → 07LR"),
        ("prevailing", "07LR"),
    ]
    page = render_page({"07LR": 0, "25LR": 0, "01": 0, "19": 0}, [], now, taf=taf)
    assert "25LR → 07LR" in page
    assert "Mogelijke naderingsbaan" in page


def test_consecutive_becmg_groups_carry_the_new_prevailing_approach():
    taf = SimpleNamespace(
        id=9,
        issued_at=datetime(2026, 9, 19, 17, tzinfo=timezone.utc),
        valid_from=datetime(2026, 9, 19, 18, tzinfo=timezone.utc),
        valid_to=datetime(2026, 9, 21, tzinfo=timezone.utc),
        raw_data={"fcsts": [
            {"timeFrom": 1789840800, "timeTo": 1789898400, "wdir": 240, "wspd": 12},
            {"timeFrom": 1789898400, "timeBec": 1789905600, "timeTo": 1789905600,
             "fcstChange": "BECMG", "wdir": 90, "wspd": 20},
            {"timeFrom": 1789905600, "timeBec": 1789909200, "timeTo": 1789912800,
             "fcstChange": "BECMG", "wdir": 180, "wspd": 30},
        ]},
    )
    periods = forecast_display(taf, datetime(2026, 9, 20, 8, tzinfo=timezone.utc))["periods"]
    assert [(p["kind"], p["approach"]) for p in periods] == [
        ("prevailing", "25LR"),
        ("transition", "25LR → 07LR"),
        ("transition", "07LR → 19"),
        ("prevailing", "19"),
    ]


def test_page_loads_30_second_same_origin_polling_script():
    template = TEMPLATE.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    assert '<script src="/public_page.js" defer></script>' in template
    assert "REFRESH_INTERVAL_MS = 30_000" in script
    assert 'fetch("/api/movements", { cache: "no-store" })' in script
    assert script.index('getElementById("forecast-status").textContent') < script.index(
        'section.dataset.forecastId === String(forecast.id)'
    )
    assert "cell.colSpan = 6" in script
    assert 'cell.className = matches ? "theoretical-runway-match"' in script
    assert '.theoretical-runway-match { background:' in template
    assert '.theoretical-runway-mismatch { background:' in template
    assert 'document.addEventListener("visibilitychange"' in script
    assert 'src="/maps/history"' in template
    assert 'loading="lazy"' in template
    assert 'id="map-loaded-at"' in template
    assert 'id="map-refresh-button" type="button" disabled' in template
    assert 'mapFrame.addEventListener("load", markMapLoaded)' in script
    assert 'mapRefreshButton.addEventListener("click"' in script
    assert 'mapFrame.src = `/maps/history?refresh=${Date.now()}`' in script
    assert 'timeZone: "Europe/Brussels"' in script
    assert "refreshMapIfChanged" not in script
    assert 'updateWind(data.wind)' in script
    assert 'updateHistory(data.history)' in script
    assert 'column.append(bar, total, tick)' in script
    assert 'wind.components[corridor]' in script
    assert 'wind.lights[corridor]' in script
    assert 'wind.light_labels[corridor]' in script
    assert 'document.getElementById("wind-approach").textContent = wind.approach' in script
    assert 'document.getElementById("wind-approach-content").hidden = wind == null' in script
    assert 'approachValue.textContent = period.approach' in script
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr))' in template


def test_forecast_approach_labels_are_anchored_to_card_bottoms():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert ".forecast-periods { display: flex; align-items: stretch;" in template
    assert ".forecast-period { display: flex; flex-direction: column;" in template
    assert ".forecast-approach { display: block; margin-top: auto;" in template


def test_history_map_route_uses_own_nonce_policy_and_safe_renderer():
    handler = object.__new__(make_handler(object()))
    handler.path = "/maps/history?run=12"
    sent = []
    handler.send_body = lambda body, content_type, **options: sent.append(
        (body, content_type, options)
    )
    with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "dummy-test-key"}), patch(
        "vogelvrij.web.Session"
    ), patch("vogelvrij.web.load_recent_runs", return_value={"aircraft": []}):
        handler.do_GET()
    body, content_type, options = sent[0]
    page = body.decode("utf-8")
    assert content_type == "text/html; charset=utf-8"
    assert "dummy-test-key" in page
    assert "__CSP_NONCE__" not in page
    assert "nonce=" in page
    assert "frame-ancestors 'self'" in options["csp"]
    assert "https://*.googleapis.com" in options["csp"]
    assert "'strict-dynamic'" in options["csp"]


def test_history_map_without_key_has_clear_embeddable_fallback():
    handler = object.__new__(make_handler(object()))
    handler.path = "/maps/history"
    sent = []
    handler.send_body = lambda body, content_type, **options: sent.append((body, options))
    with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}):
        handler.do_GET()
    body, options = sent[0]
    assert options["status"] == 503
    assert "Google Maps is nog niet geconfigureerd" in body.decode("utf-8")
    assert "frame-ancestors 'self'" in options["csp"]


def test_map_csp_does_not_relax_main_page_policy():
    policy = map_csp("test-nonce")
    assert "script-src 'nonce-test-nonce'" in policy
    assert "img-src 'self'" in policy
