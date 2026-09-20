"""Generate a Google Maps page from the newest stored collection run."""

from __future__ import annotations

import argparse
import html
import json
import os
import tempfile
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import make_engine
from .geography import APPROACH_AREAS
from .models import AircraftObservation, CollectionRun

DEFAULT_OUTPUT = Path("generated/planes_map.html")
TEMPLATE = Path(__file__).parent / "templates" / "aircraft_map.html"


def load_latest_run(session: Session) -> Dict[str, Any]:
    run = session.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(1))
    if run is None:
        raise ValueError("No collection runs found. Run vogelvrij-collect first.")

    observations = session.scalars(
        select(AircraftObservation)
        .where(AircraftObservation.collection_run_id == run.id)
        .where(AircraftObservation.lat.is_not(None))
        .where(AircraftObservation.lon.is_not(None))
        .order_by(AircraftObservation.observed_at.desc(), AircraftObservation.id.desc())
    ).all()

    aircraft: List[Dict[str, Any]] = []
    for observation in observations:
        aircraft.append(
            {
                "hex": observation.hex,
                "flight": observation.flight,
                "lat": observation.lat,
                "lon": observation.lon,
                "altitude_ft": (
                    observation.alt_baro_ft
                    if observation.alt_baro_ft is not None
                    else observation.alt_geom_ft
                ),
                "speed_knots": observation.ground_speed_knots,
                "track_degrees": observation.track_degrees,
                "observed_at": observation.observed_at.astimezone(timezone.utc).isoformat(),
            }
        )

    return {
        "run_id": run.id,
        "collected_at": run.requested_at.astimezone(timezone.utc).isoformat(),
        "center": {"lat": run.request_lat, "lng": run.request_lon},
        "radius_nm": run.request_radius_nm,
        "radius_m": run.request_radius_nm * 1852,
        "approaches": [
            {
                "name": approach.name,
                "points": [
                    {"lat": point.lat, "lng": point.lon} for point in approach.points
                ],
            }
            for approach in APPROACH_AREAS
        ],
        "aircraft": aircraft,
    }


def render_html(
    data: Dict[str, Any], api_key: str, *, template_path: Path = TEMPLATE, nonce: str = ""
) -> str:
    if not api_key.strip():
        raise ValueError("GOOGLE_MAPS_API_KEY is required")

    # A JSON script element is inert, but escape HTML-sensitive characters so provider
    # strings cannot terminate the element and inject markup or executable JavaScript.
    safe_json = (
        json.dumps(data, ensure_ascii=False, allow_nan=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    maps_url = "https://maps.googleapis.com/maps/api/js?" + urlencode(
        {"key": api_key, "loading": "async", "callback": "initMap"}
    )
    template = template_path.read_text(encoding="utf-8")
    return (
        template.replace("__MAP_DATA__", safe_json)
        .replace("__MAPS_SCRIPT_URL__", html.escape(maps_url, quote=True))
        .replace("__CSP_NONCE__", nonce)
    )


def write_map(
    data: Dict[str, Any], api_key: str, output: Path, *, template_path: Path = TEMPLATE
) -> Path:
    page = render_html(data, api_key, template_path=template_path)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=output.parent, prefix=".vogelvrij-map-", delete=False
    ) as temporary:
        temporary.write(page)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, output)
    output.chmod(0o600)
    return output


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Map aircraft from the latest stored run.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key.strip():
        parser.error("set GOOGLE_MAPS_API_KEY in the environment before generating the map")

    engine = make_engine()
    with Session(engine) as session:
        data = load_latest_run(session)

    output = write_map(data, api_key, args.output)
    print(f"Map written to {output} ({len(data['aircraft'])} aircraft, run {data['run_id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
