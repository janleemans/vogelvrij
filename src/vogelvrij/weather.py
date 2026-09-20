"""Collect the latest Brussels Airport METAR wind independently of aircraft."""

from __future__ import annotations

import argparse
import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

METAR_URL = "https://aviationweather.gov/api/data/metar?ids=EBBR&format=json"
USER_AGENT = "VogelvrijWeatherCollector/1.0"
WIND_SOURCE = "aviationweather.gov EBBR METAR"
KNOTS_TO_MPS = 0.514444


def fetch_latest_metar(session: Optional[requests.Session] = None) -> Optional[Dict[str, Any]]:
    """Return the newest EBBR report, or None when the API has no report."""
    http = session or requests.Session()
    response = http.get(METAR_URL, timeout=15, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    if response.status_code == 204:
        return None

    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("METAR API returned a non-list JSON response")
    if not payload:
        return None
    reports = [
        report for report in payload
        if isinstance(report, dict) and report.get("icaoId") == "EBBR"
    ]
    if not reports:
        raise ValueError("METAR API returned no EBBR report")
    return max(reports, key=lambda report: _observation_time(report).timestamp())


def _observation_time(report: Mapping[str, Any]) -> datetime:
    value = report.get("obsTime")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("METAR obsTime must be a Unix timestamp in seconds")
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("METAR obsTime is out of range") from exc


def _wind_number(report: Mapping[str, Any], field: str) -> Optional[float]:
    value = report.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def stored_wind_values(wind: Any) -> tuple[float, float, Optional[float]]:
    """Use the reported METAR values, falling back to normalized stored columns."""
    raw = wind.raw_data if isinstance(wind.raw_data, dict) else {}
    direction = _wind_number(raw, "wdir")
    if direction is None or not 0 <= direction <= 360:
        direction = wind.direction_degrees
    speed = _wind_number(raw, "wspd")
    if speed is None or speed < 0:
        speed = round(wind.speed_mps / KNOTS_TO_MPS, 1)
    gust = _wind_number(raw, "wgst")
    if gust is None or gust < 0:
        stored_gust = getattr(wind, "gust_speed_mps", None)
        gust = (
            stored_gust / KNOTS_TO_MPS
            if stored_gust is not None and math.isfinite(stored_gust) and stored_gust >= 0
            else None
        )
    return float(direction), float(speed), float(gust) if gust is not None else None


def wind_observation(report: Mapping[str, Any]):
    """Build a stored reading; variable or missing wind cannot fit the current schema."""
    from .models import WindObservation

    direction = _wind_number(report, "wdir")
    speed = _wind_number(report, "wspd")
    if direction is None or not 0 <= direction <= 360 or speed is None or speed < 0:
        return None
    gust = _wind_number(report, "wgst")
    if gust is not None and gust < 0:
        gust = None
    return WindObservation(
        observed_at=_observation_time(report),
        direction_degrees=0.0 if direction == 360 else direction,
        speed_mps=speed * KNOTS_TO_MPS,
        gust_speed_mps=gust * KNOTS_TO_MPS if gust is not None else None,
        source=WIND_SOURCE,
        raw_data=dict(report),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch the latest EBBR METAR wind.")
    parser.add_argument(
        "--no-store", action="store_true", help="print without storing in PostgreSQL"
    )
    args = parser.parse_args(argv)

    report = fetch_latest_metar()
    if report is None:
        print("No EBBR METAR available; nothing stored.")
        return 0

    print(
        f"EBBR METAR at {_observation_time(report).isoformat()}: "
        f"wdir={report.get('wdir')!r}, wspd={report.get('wspd')!r} kt"
    )
    observation = wind_observation(report)
    if observation is None:
        print("Wind direction or speed is missing/variable; nothing stored.")
        return 0
    if args.no_store:
        return 0

    from sqlalchemy import select

    from .database import make_engine, session_scope
    from .models import WindObservation

    engine = make_engine()
    with session_scope(engine) as db:
        existing = db.scalar(
            select(WindObservation.id).where(
                WindObservation.source == observation.source,
                WindObservation.observed_at == observation.observed_at,
            ).limit(1)
        )
        if existing is not None:
            print(f"METAR already stored as wind observation {existing}.")
        else:
            db.add(observation)
            db.flush()
            print(f"Stored wind observation: {observation.id}")
    return 0
