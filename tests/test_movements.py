"""Movement qualification and fifteen-minute aircraft-level deduplication."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from vogelvrij.adsb_lol import CollectionResult
from vogelvrij.faf import (
    FAF_01,
    FAF_07LR,
    FAF_19_REFERENCE,
    FAF_25L,
    FAF_25LR,
    FAF_25R,
    THRESHOLD_01,
    THRESHOLD_19,
    distance_m,
)
from vogelvrij.models import FlightMovement
from vogelvrij.movements import classify_approach, sync_movements_for_run, update_faf_altitude
from vogelvrij.repository import store_collection

START = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)


def _session():
    session = Mock()
    session.scalars.return_value.first.return_value = None
    return session


def _observation(lat, lon, track, speed=100, *, hex_code="abc123", flight="BEL1", when=START):
    return SimpleNamespace(
        lat=lat,
        lon=lon,
        track_degrees=track,
        ground_speed_knots=speed,
        hex=hex_code,
        flight=flight,
        observed_at=when,
        alt_baro_ft=2000,
        alt_geom_ft=None,
        flight_movement=None,
    )


@pytest.mark.parametrize(
    ("lat", "lon", "low_heading", "high_heading", "corridor"),
    [
        (50.9282, 4.5891, 240, 260, "25LR"),
        (50.84, 4.28, 60, 80, "07LR"),
        (50.77, 4.445, 0, 20, "01"),
        (51.03, 4.548, 180, 200, "19"),
    ],
)
def test_qualifying_tracks_include_both_heading_bounds_and_100_knots(
    lat, lon, low_heading, high_heading, corridor
):
    assert classify_approach(_observation(lat, lon, low_heading)) == corridor
    assert classify_approach(_observation(lat, lon, high_heading)) == corridor


def test_missing_or_bad_movement_data_is_rejected():
    assert classify_approach(_observation(50.77, 4.445, 10, speed=99.9)) is None
    assert classify_approach(_observation(50.77, 4.445, 359)) is None
    assert classify_approach(_observation(50.77, 4.445, None)) is None
    assert classify_approach(_observation(50.77, 4.445, 10, speed=None)) is None
    assert classify_approach(_observation(50.85, 4.35, 10)) is None


def test_route_reference_points_use_supplied_locations_and_derived_points():
    assert (FAF_01.lat, FAF_01.lon) == (50.795306, 4.453861)
    assert (FAF_07LR.lat, FAF_07LR.lon) == (50.879167, 4.309167)
    assert FAF_25LR.lat == pytest.approx((FAF_25L.lat + FAF_25R.lat) / 2)
    assert FAF_25LR.lon == pytest.approx((FAF_25L.lon + FAF_25R.lon) / 2)
    assert distance_m(THRESHOLD_19, FAF_19_REFERENCE) == pytest.approx(
        distance_m(THRESHOLD_01, FAF_01), abs=0.01
    )
    assert FAF_19_REFERENCE.lat > THRESHOLD_19.lat


def test_faf_altitude_changes_only_when_a_later_observation_is_closer():
    session = _session()
    session.scalar.return_value = None
    first = _observation(50.77, 4.445, 10)
    first.alt_baro_ft = 3000
    first_run = SimpleNamespace(requested_at=START, observations=[first])
    assert sync_movements_for_run(session, first_run) == 1
    movement = first.flight_movement
    first_distance = movement.faf_distance_m
    assert movement.faf_altitude_ft == 3000

    session.scalar.return_value = movement
    closer_time = START + timedelta(minutes=1)
    closer = _observation(FAF_01.lat, FAF_01.lon, 10, when=closer_time)
    closer.alt_baro_ft = None
    closer.alt_geom_ft = 2200
    assert sync_movements_for_run(
        session, SimpleNamespace(requested_at=closer_time, observations=[closer])
    ) == 0
    assert closer.flight_movement is movement
    assert movement.faf_altitude_ft == 2200
    assert movement.faf_distance_m == pytest.approx(0)
    assert movement.faf_distance_m < first_distance

    farther = _observation(50.77, 4.445, 10, when=START + timedelta(minutes=2))
    farther.alt_baro_ft = 1000
    assert sync_movements_for_run(
        session, SimpleNamespace(requested_at=farther.observed_at, observations=[farther])
    ) == 0
    assert movement.faf_altitude_ft == 2200
    assert movement.faf_distance_m == pytest.approx(0)


def test_equal_distance_and_missing_altitude_do_not_replace_faf_altitude():
    movement = FlightMovement(approach_corridor="07LR")
    first = _observation(FAF_07LR.lat, FAF_07LR.lon, 70)
    assert update_faf_altitude(movement, first)
    first_distance = movement.faf_distance_m
    equal = _observation(FAF_07LR.lat, FAF_07LR.lon, 70)
    equal.alt_baro_ft = 1500
    assert not update_faf_altitude(movement, equal)
    assert movement.faf_altitude_ft == 2000
    assert movement.faf_distance_m == first_distance
    equal.alt_baro_ft = None
    assert not update_faf_altitude(movement, equal)


def test_movement_reuses_same_aircraft_with_changed_callsign_inside_15_minutes():
    session = _session()
    session.scalar.return_value = None
    first = _observation(50.77, 4.445, 10, flight="BEL1")
    first_run = SimpleNamespace(requested_at=START, observations=[first])

    assert sync_movements_for_run(session, first_run) == 1
    movement = first.flight_movement
    assert isinstance(movement, FlightMovement)
    assert movement.aircraft_icao == "abc123"
    assert movement.approach_corridor == "01"
    assert movement.callsign == "BEL1"

    session.scalar.return_value = movement
    later = START + timedelta(minutes=14, seconds=59)
    second = _observation(50.77, 4.445, 10, flight="DIFFERENT", when=later)
    second_run = SimpleNamespace(requested_at=later, observations=[second])

    assert sync_movements_for_run(session, second_run) == 0
    assert second.flight_movement is movement
    assert movement.last_observed_at == later
    assert movement.callsign == "BEL1"

    at_boundary = START + timedelta(minutes=15)
    third = _observation(50.77, 4.445, 10, flight="DIFFERENT", when=at_boundary)
    third_run = SimpleNamespace(requested_at=at_boundary, observations=[third])

    assert sync_movements_for_run(session, third_run) == 1
    assert third.flight_movement is not movement
    assert third.flight_movement.callsign == "DIFFERENT"


def test_same_aircraft_is_created_only_once_within_one_run():
    session = _session()
    session.scalar.return_value = None
    first = _observation(50.77, 4.445, 10)
    second = _observation(50.78, 4.45, 12, when=START + timedelta(seconds=1))
    run = SimpleNamespace(requested_at=START, observations=[first, second])

    assert sync_movements_for_run(session, run) == 1
    assert first.flight_movement is second.flight_movement
    assert first.flight_movement.last_observed_at == second.observed_at
    assert session.scalar.call_count == 1


def test_new_movement_snapshots_latest_metar_and_keeps_it_on_repeat_sightings():
    session = _session()
    session.scalar.return_value = None
    wind = SimpleNamespace(
        direction_degrees=240,
        speed_mps=13 * 0.514444,
        gust_speed_mps=None,
        raw_data={"wdir": 240, "wspd": 13},
    )
    session.scalars.return_value.first.return_value = wind
    first = _observation(50.77, 4.445, 10)
    second_aircraft = _observation(50.77, 4.445, 10, hex_code="def456")
    run = SimpleNamespace(requested_at=START, observations=[first, second_aircraft])

    assert sync_movements_for_run(session, run) == 2
    for observation in run.observations:
        movement = observation.flight_movement
        assert movement.wind_direction_degrees == 240
        assert movement.wind_speed_knots == 13
        assert movement.expected_approach == "25LR"
    assert session.scalars.call_count == 1
    assert "wind_observations.source =" in str(session.scalars.call_args.args[0])

    original = first.flight_movement
    session.scalar.return_value = original
    session.scalars.return_value.first.return_value = SimpleNamespace(
        direction_degrees=180, speed_mps=8 * 0.514444,
        gust_speed_mps=30 * 0.514444, raw_data={"wdir": 180, "wspd": 8, "wgst": 30},
    )
    later = START + timedelta(minutes=1)
    repeat = _observation(50.77, 4.445, 10, when=later)
    assert sync_movements_for_run(
        session, SimpleNamespace(requested_at=later, observations=[repeat])
    ) == 0
    assert repeat.flight_movement is original
    assert (original.wind_direction_degrees, original.wind_speed_knots,
            original.expected_approach) == (240, 13, "25LR")
    assert session.scalars.call_count == 1

    boundary = START + timedelta(minutes=15)
    next_leg = _observation(50.77, 4.445, 10, when=boundary)
    assert sync_movements_for_run(
        session, SimpleNamespace(requested_at=boundary, observations=[next_leg])
    ) == 1
    assert next_leg.flight_movement is not original
    assert (next_leg.flight_movement.wind_direction_degrees,
            next_leg.flight_movement.wind_speed_knots,
            next_leg.flight_movement.expected_approach) == (180, 8, "19")
    assert session.scalars.call_count == 2


def test_new_movement_without_metar_has_no_wind_prediction():
    session = _session()
    session.scalar.return_value = None
    observation = _observation(50.77, 4.445, 10)
    assert sync_movements_for_run(
        session, SimpleNamespace(requested_at=START, observations=[observation])
    ) == 1
    movement = observation.flight_movement
    assert movement.wind_direction_degrees is None
    assert movement.wind_speed_knots is None
    assert movement.expected_approach is None


def test_missing_aircraft_address_cannot_create_deduplicated_movement():
    session = _session()
    observation = _observation(50.77, 4.445, 10, hex_code=None)
    run = SimpleNamespace(requested_at=START, observations=[observation])

    assert sync_movements_for_run(session, run) == 0
    assert observation.flight_movement is None
    session.scalar.assert_not_called()


def test_every_stored_collection_invokes_movement_detection(monkeypatch):
    detector = Mock()
    monkeypatch.setattr("vogelvrij.repository.sync_movements_for_run", detector)
    session = _session()
    result = CollectionResult(aircraft=[], metadata={}, raw_aircraft=[])

    run = store_collection(
        session, result, request_lat=50.85, request_lon=4.35, request_radius_nm=25
    )

    detector.assert_called_once_with(session, run)
    session.flush.assert_called_once()


def test_collection_keeps_outside_positions_but_only_links_corridor_movements():
    session = _session()
    session.scalar.return_value = None

    def assign_requested_at():
        session.add.call_args.args[0].requested_at = START

    session.flush.side_effect = assign_requested_at
    result = CollectionResult(
        aircraft=[],
        metadata={},
        raw_aircraft=[
            {"hex": "outside", "alt_baro": 5_000, "lat": 50.85, "lon": 4.35,
             "track": 250, "gs": 150},
            {"hex": "inside", "alt_baro": 5_000, "lat": 50.9282, "lon": 4.5891,
             "track": 250, "gs": 150},
        ],
    )

    run = store_collection(
        session, result, request_lat=50.85, request_lon=4.35, request_radius_nm=25
    )

    assert len(run.observations) == 2
    by_hex = {observation.hex: observation for observation in run.observations}
    assert by_hex["outside"].flight_movement is None
    assert by_hex["inside"].flight_movement.approach_corridor == "25LR"
    assert session.scalar.call_count == 1
