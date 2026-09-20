from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from vogelvrij.map_history import TEMPLATE, load_recent_runs
from vogelvrij.map_page import render_html


def _observation(
    identifier,
    when,
    *,
    run_id=None,
    hex_code="abc123",
    lat=50.9,
    lon=4.6,
    flight="BEL1",
):
    return SimpleNamespace(
        id=identifier,
        collection_run_id=run_id if run_id is not None else identifier,
        observed_at=when,
        hex=hex_code,
        flight=flight,
        lat=lat,
        lon=lon,
        alt_baro_ft=2000 + identifier,
        alt_geom_ft=None,
        track_degrees=250,
    )


def test_history_groups_tracks_and_keeps_only_distinct_consecutive_positions():
    start = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
    runs = [
        SimpleNamespace(
            id=12, requested_at=start + timedelta(minutes=2), request_lat=50.85, request_lon=4.35
        ),
        SimpleNamespace(
            id=11, requested_at=start + timedelta(minutes=1), request_lat=50.85, request_lon=4.35
        ),
        SimpleNamespace(id=10, requested_at=start, request_lat=50.85, request_lon=4.35),
    ]
    observations = [
        _observation(10, start, hex_code="ABC123", flight="BEL1"),
        _observation(11, start + timedelta(minutes=1), flight="BEL1"),
        _observation(20, start + timedelta(minutes=1), run_id=11, hex_code=None, lat=50.8, lon=4.3),
        _observation(12, start + timedelta(minutes=2), lat=50.91, lon=4.61, flight="BEL2"),
    ]
    session = Mock()
    session.scalars.side_effect = [
        Mock(all=Mock(return_value=runs)),
        Mock(all=Mock(return_value=observations)),
    ]

    data = load_recent_runs(session)

    assert data["run_count"] == 3
    assert data["newest_run_id"] == 12
    assert data["oldest_run_id"] == 10
    assert [area["name"] for area in data["approaches"]] == [
        "25LR Approach", "7LR Approach", "01 Approach", "19 Approach"
    ]
    by_hex = {aircraft["hex"]: aircraft for aircraft in data["aircraft"]}
    track = by_hex["abc123"]
    assert track["flight"] == "BEL2"
    assert track["observation_count"] == 3
    assert [(point["lat"], point["lng"]) for point in track["positions"]] == [
        (50.9, 4.6),
        (50.91, 4.61),
    ]
    assert track["positions"][-1]["run_id"] == 12
    assert by_hex[None]["positions"][0]["run_id"] == 11
    assert [aircraft["hex"] for aircraft in data["aircraft"]] == ["abc123", None]

    run_query = session.scalars.call_args_list[0].args[0]
    observation_query = session.scalars.call_args_list[1].args[0]
    assert 10 in run_query.compile().params.values()
    assert [12, 11, 10] in observation_query.compile().params.values()


def test_history_requires_at_least_one_run():
    session = Mock()
    session.scalars.return_value.all.return_value = []

    with pytest.raises(ValueError, match="No collection runs"):
        load_recent_runs(session)


def test_history_template_draws_tracks_and_only_one_arrow_per_aircraft():
    page = render_html(
        {"aircraft": [{"flight": "</script><script>alert(1)</script>"}]},
        "dummy-test-key",
        template_path=TEMPLATE,
    )

    assert "new google.maps.Polyline" in page
    assert "positions.slice(0, -1).forEach" in page
    assert page.count("new google.maps.Marker") == 2
    assert page.count("google.maps.SymbolPath.FORWARD_CLOSED_ARROW") == 1
    assert "positions[positions.length - 1]" in page
    assert "\u003c/script\u003e" in page
    assert "<script>alert(1)</script>" not in page
    assert '<html lang="nl-BE">' in page
    assert "Laatst gezien" in page
