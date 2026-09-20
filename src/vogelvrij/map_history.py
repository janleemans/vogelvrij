"""Generate a trajectory map from the ten newest stored collection runs."""

from __future__ import annotations

import argparse
import os
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import make_engine
from .geography import APPROACH_AREAS
from .map_page import write_map
from .models import AircraftObservation, CollectionRun

RUN_LIMIT = 10
DEFAULT_OUTPUT = Path("generated/planes_history_map.html")
TEMPLATE = Path(__file__).parent / "templates" / "aircraft_history_map.html"


def load_recent_runs(session: Session) -> Dict[str, Any]:
    runs = session.scalars(
        select(CollectionRun).order_by(CollectionRun.id.desc()).limit(RUN_LIMIT)
    ).all()
    if not runs:
        raise ValueError("No collection runs found. Run vogelvrij-collect first.")

    run_ids = [run.id for run in runs]
    observations = session.scalars(
        select(AircraftObservation)
        .where(AircraftObservation.collection_run_id.in_(run_ids))
        .where(AircraftObservation.lat.is_not(None))
        .where(AircraftObservation.lon.is_not(None))
        .order_by(AircraftObservation.observed_at, AircraftObservation.id)
    ).all()

    aircraft_by_key: Dict[str, Dict[str, Any]] = {}
    for observation in observations:
        lat, lon = observation.lat, observation.lon
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        hex_code = (observation.hex or "").strip().lower()
        key = hex_code or f"unknown:{observation.id}"
        aircraft = aircraft_by_key.setdefault(
            key,
            {"hex": hex_code or None, "flight": None, "positions": [], "observation_count": 0},
        )
        aircraft["observation_count"] += 1
        if observation.flight:
            aircraft["flight"] = observation.flight

        point = {
            "lat": lat,
            "lng": lon,
            "altitude_ft": (
                observation.alt_baro_ft
                if observation.alt_baro_ft is not None
                else observation.alt_geom_ft
            ),
            "track_degrees": observation.track_degrees,
            "observed_at": observation.observed_at.astimezone(timezone.utc).isoformat(),
            "run_id": observation.collection_run_id,
        }
        positions: List[Dict[str, Any]] = aircraft["positions"]
        if positions and (positions[-1]["lat"], positions[-1]["lng"]) == (lat, lon):
            # Preserve the latest details without drawing a zero-length segment.
            positions[-1] = point
        else:
            positions.append(point)

    newest = runs[0]
    oldest = runs[-1]
    aircraft_list = sorted(
        aircraft_by_key.values(),
        key=lambda aircraft: ((aircraft["flight"] or "").lower(), aircraft["hex"] or ""),
    )
    aircraft_list.sort(key=lambda aircraft: aircraft["positions"][-1]["observed_at"], reverse=True)
    return {
        "run_count": len(runs),
        "newest_run_id": newest.id,
        "oldest_run_id": oldest.id,
        "first_collected_at": oldest.requested_at.astimezone(timezone.utc).isoformat(),
        "last_collected_at": newest.requested_at.astimezone(timezone.utc).isoformat(),
        "center": {"lat": newest.request_lat, "lng": newest.request_lon},
        "approaches": [
            {
                "name": approach.name,
                "points": [{"lat": point.lat, "lng": point.lon} for point in approach.points],
            }
            for approach in APPROACH_AREAS
        ],
        "aircraft": aircraft_list,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Map aircraft tracks from the ten newest runs.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key.strip():
        parser.error("set GOOGLE_MAPS_API_KEY in the environment before generating the map")

    engine = make_engine()
    with Session(engine) as session:
        data = load_recent_runs(session)

    output = write_map(data, api_key, args.output, template_path=TEMPLATE)
    print(
        f"History map written to {output} "
        f"({len(data['aircraft'])} aircraft, {data['run_count']} runs)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
