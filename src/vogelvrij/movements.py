"""Detect and correlate approach movements from stored aircraft observations."""

from __future__ import annotations

from datetime import timedelta
from math import isfinite
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .faf import FAF_REFERENCES, distance_m
from .geography import APPROACH_AREAS, GeoPoint
from .models import AircraftObservation, CollectionRun, FlightMovement, WindObservation
from .runway_prediction import predict_landing_approach
from .weather import WIND_SOURCE, stored_wind_values

MIN_GROUND_SPEED_KNOTS = 100
MAX_HEADING_DIFFERENCE_DEGREES = 10
MOVEMENT_DEDUP_WINDOW = timedelta(minutes=15)

# These nominal headings implement the requested inclusive ranges: 240-260,
# 60-80, 0-20, and 180-200 degrees. Ground track, not nav heading, is used.
APPROACH_HEADINGS = {
    "25LR Approach": ("25LR", 250),
    "7LR Approach": ("07LR", 70),
    "01 Approach": ("01", 10),
    "19 Approach": ("19", 190),
}


def classify_approach(observation: AircraftObservation) -> Optional[str]:
    """Return a matching corridor for a positioned, aligned aircraft at >=100 kt."""

    lat = _finite_number(observation.lat)
    lon = _finite_number(observation.lon)
    track = _finite_number(observation.track_degrees)
    speed = _finite_number(observation.ground_speed_knots)
    if (
        lat is None
        or lon is None
        or track is None
        or speed is None
        or not (-90 <= lat <= 90 and -180 <= lon <= 180)
        or speed < MIN_GROUND_SPEED_KNOTS
    ):
        return None

    track %= 360
    for area in APPROACH_AREAS:
        corridor, heading = APPROACH_HEADINGS[area.name]
        difference = abs((track - heading + 180) % 360 - 180)
        if difference <= MAX_HEADING_DIFFERENCE_DEGREES and area.contains(lat=lat, lon=lon):
            return corridor
    return None


def sync_movements_for_run(session: Session, run: CollectionRun) -> int:
    """Create/link movements for this run; return the number of new movements."""

    recent_by_aircraft: Dict[str, Optional[FlightMovement]] = {}
    created = 0
    wind_loaded = False
    wind = None
    for observation in run.observations:
        corridor = classify_approach(observation)
        aircraft_icao = (observation.hex or "").strip().lower()
        if corridor is None or not aircraft_icao:
            # Without a stable aircraft address, a later call cannot be deduplicated.
            continue

        if aircraft_icao not in recent_by_aircraft:
            recent_by_aircraft[aircraft_icao] = session.scalar(
                select(FlightMovement)
                .where(FlightMovement.aircraft_icao == aircraft_icao)
                .order_by(FlightMovement.created_at.desc(), FlightMovement.id.desc())
                .limit(1)
            )
        movement = recent_by_aircraft[aircraft_icao]
        if movement is None or not (
            timedelta(0) <= run.requested_at - movement.created_at < MOVEMENT_DEDUP_WINDOW
        ):
            if not wind_loaded:
                wind = session.scalars(
                    select(WindObservation)
                    .where(WindObservation.source == WIND_SOURCE)
                    .order_by(WindObservation.observed_at.desc(), WindObservation.id.desc())
                    .limit(1)
                ).first()
                wind_loaded = True
            direction, speed, gust = stored_wind_values(wind) if wind is not None else (None,) * 3
            movement = FlightMovement(
                created_at=run.requested_at,
                aircraft_icao=aircraft_icao,
                callsign=(observation.flight or "").strip() or None,
                approach_corridor=corridor,
                first_observed_at=observation.observed_at,
                last_observed_at=observation.observed_at,
                wind_direction_degrees=direction,
                wind_speed_knots=speed,
                expected_approach=predict_landing_approach(direction, speed, gust),
            )
            session.add(movement)
            recent_by_aircraft[aircraft_icao] = movement
            created += 1
        else:
            if (
                movement.last_observed_at is None
                or observation.observed_at > movement.last_observed_at
            ):
                movement.last_observed_at = observation.observed_at
            if not movement.callsign and observation.flight:
                movement.callsign = observation.flight.strip() or None

        observation.flight_movement = movement
        update_faf_altitude(movement, observation)

    return created


def update_faf_altitude(movement: FlightMovement, observation: AircraftObservation) -> bool:
    """Keep the altitude of the closest eligible observation to this corridor's point."""
    reference = FAF_REFERENCES.get(movement.approach_corridor)
    lat = _finite_number(observation.lat)
    lon = _finite_number(observation.lon)
    altitude = observation.alt_baro_ft
    if altitude is None:
        altitude = observation.alt_geom_ft
    if reference is None or lat is None or lon is None or altitude is None:
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    distance = distance_m(GeoPoint(lat, lon), reference)
    if movement.faf_distance_m is not None and distance >= movement.faf_distance_m:
        return False
    movement.faf_altitude_ft = altitude
    movement.faf_distance_m = distance
    return True


def _finite_number(value: object) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) else None
