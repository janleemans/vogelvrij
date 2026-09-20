from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from vogelvrij.map_page import load_latest_run, render_html


def test_load_latest_run_uses_only_that_runs_observations():
    when = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    run = SimpleNamespace(
        id=7,
        requested_at=when,
        request_lat=50.85,
        request_lon=4.35,
        request_radius_nm=25,
    )
    observation = SimpleNamespace(
        hex="44cc45",
        flight="BEL123",
        lat=50.93,
        lon=4.60,
        alt_baro_ft=2100,
        alt_geom_ft=2200,
        ground_speed_knots=145.0,
        track_degrees=250.0,
        observed_at=when,
    )
    session = Mock()
    session.scalar.return_value = run
    session.scalars.return_value.all.return_value = [observation]

    data = load_latest_run(session)

    assert data["run_id"] == 7
    assert data["center"] == {"lat": 50.85, "lng": 4.35}
    assert data["radius_nm"] == 25
    assert data["radius_m"] == 46_300
    assert data["aircraft"][0]["altitude_ft"] == 2100
    assert [area["name"] for area in data["approaches"]] == [
        "25LR Approach",
        "7LR Approach",
        "01 Approach",
        "19 Approach",
    ]
    assert all(len(area["points"]) == 4 for area in data["approaches"])
    assert data["approaches"][1]["points"][0] == {
        "lat": 50.87768795368042,
        "lng": 4.458039848279057,
    }
    assert data["approaches"][1]["points"][1] == {
        "lat": 50.897886385696516,
        "lng": 4.42721938869695,
    }
    query = session.scalars.call_args.args[0]
    assert "aircraft_observations.collection_run_id = :collection_run_id_1" in str(query)
    assert query.compile().params["collection_run_id_1"] == 7
    assert "aircraft_observations.observed_at DESC, aircraft_observations.id DESC" in str(query)


def test_load_latest_run_requires_a_collection():
    session = Mock()
    session.scalar.return_value = None

    with pytest.raises(ValueError, match="No collection runs"):
        load_latest_run(session)


def test_render_html_escapes_provider_strings_and_does_not_log_key():
    page = render_html(
        {"aircraft": [{"flight": "</script><script>alert(1)</script>"}]},
        "dummy-test-key",
    )

    assert "<script>alert(1)</script>" not in page
    assert "\\u003c/script\\u003e" in page
    assert "dummy-test-key" in page
    assert "__MAP_DATA__" not in page
    assert "data.approaches.forEach" in page
    assert "7LR-nadering" in page
    assert '<html lang="nl-BE">' in page
    assert "Laatst gezien" in page


def test_render_html_requires_a_key():
    with pytest.raises(ValueError, match="GOOGLE_MAPS_API_KEY"):
        render_html({}, " ")
