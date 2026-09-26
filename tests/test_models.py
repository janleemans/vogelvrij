from datetime import datetime, timezone

from vogelvrij.adsb_lol import Aircraft, CollectionResult
from vogelvrij.database import DEFAULT_DATABASE_URL, database_url
from vogelvrij.geography import APPROACH_25LR
from vogelvrij.models import AircraftObservation, FlightMovement, WindObservation
from vogelvrij.repository import (
    EXCLUDED_AIRCRAFT_TYPES,
    _observation,
    _provider_datetime,
    _should_store_aircraft,
)

INSIDE_25LR = {"lat": 50.9282, "lon": 4.5891}


def test_aircraft_provider_fields_are_nullable_and_raw_data_is_required():
    nullable_columns = [
        column
        for column in AircraftObservation.__table__.columns
        if column.name not in {"id", "collection_run_id", "observed_at", "raw_data"}
    ]

    assert nullable_columns
    assert all(column.nullable for column in nullable_columns)
    assert not AircraftObservation.__table__.columns.raw_data.nullable


def test_observation_has_collection_run_index_for_map_queries():
    index = next(
        index
        for index in AircraftObservation.__table__.indexes
        if index.name == "ix_aircraft_observations_collection_run_id"
    )

    assert [column.name for column in index.columns] == ["collection_run_id"]


def test_wind_observation_has_independent_timestamp_and_canonical_speed():
    columns = WindObservation.__table__.columns

    assert "observed_at" in columns
    assert "direction_degrees" in columns
    assert "speed_mps" in columns


def test_movement_wind_snapshot_is_nullable_for_historical_rows():
    columns = FlightMovement.__table__.columns
    assert columns.wind_direction_degrees.nullable
    assert columns.wind_speed_knots.nullable
    assert columns.expected_approach.nullable


def test_observation_maps_numeric_altitude_and_preserves_raw_data():
    raw = {
        "hex": "44cc45",
        "flight": "BEL7LW  ",
        "alt_baro": 13_875,
        "lat": 50.812,
        "lon": 3.824,
        "future_field": {"kept": True},
    }

    observation = _observation(raw, observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert observation.flight == "BEL7LW"
    assert observation.alt_baro_ft == 13_875
    assert observation.alt_baro_state is None
    assert observation.raw_data["future_field"] == {"kept": True}


def test_observation_maps_ground_altitude_without_forcing_it_to_a_number():
    observation = _observation(
        {"alt_baro": "ground"}, observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    assert observation.alt_baro_ft is None
    assert observation.alt_baro_state == "ground"


def test_provider_millisecond_timestamp_is_converted_to_utc_datetime():
    assert _provider_datetime(1_767_225_600_000) == datetime(
        2026, 1, 1, tzinfo=timezone.utc
    )


def test_collection_result_keeps_envelope_metadata_separate_from_aircraft():
    result = CollectionResult(
        aircraft=[Aircraft("abc123", "TEST1", 50.0, 4.0, 1000, 100, 180)],
        metadata={"msg": "No error", "total": 1},
    )

    assert result.metadata["total"] == 1
    assert result.aircraft[0].hex == "abc123"


def test_local_database_is_the_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert database_url() == DEFAULT_DATABASE_URL


def test_grounded_aircraft_is_not_stored():
    assert not _should_store_aircraft({"alt_baro": "ground", **INSIDE_25LR})


def test_excluded_aircraft_types_are_not_stored():
    for aircraft_type in (*EXCLUDED_AIRCRAFT_TYPES, " c152 ", "p28a"):
        assert not _should_store_aircraft(
            {"t": aircraft_type, "alt_baro": 5_000, **INSIDE_25LR}
        )


def test_other_and_unknown_aircraft_types_remain_eligible():
    for aircraft_type in ("A320", "DA42", None):
        assert _should_store_aircraft(
            {"t": aircraft_type, "alt_baro": 5_000, **INSIDE_25LR}
        )


def test_aircraft_above_10000_feet_is_not_stored():
    assert not _should_store_aircraft({"alt_baro": 10_001, **INSIDE_25LR})


def test_aircraft_at_10000_feet_is_stored():
    assert _should_store_aircraft({"alt_baro": 10_000, **INSIDE_25LR})


def test_geometric_altitude_is_used_when_barometric_altitude_is_missing():
    assert not _should_store_aircraft({"alt_geom": 12_000, **INSIDE_25LR})


def test_aircraft_with_unknown_altitude_is_not_stored():
    assert not _should_store_aircraft(INSIDE_25LR)


def test_positioned_aircraft_outside_approach_is_still_stored():
    assert _should_store_aircraft({"alt_baro": 5_000, "lat": 50.85, "lon": 4.35})


def test_aircraft_without_a_position_is_not_stored():
    assert not _should_store_aircraft({"alt_baro": 5_000})


def test_positioned_aircraft_on_25lr_approach_boundary_is_stored():
    first_point = APPROACH_25LR.points[0]

    assert _should_store_aircraft(
        {"alt_baro": 5_000, "lat": first_point.lat, "lon": first_point.lon}
    )
