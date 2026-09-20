"""Command-line entry point for a single adsb.lol collection run."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from typing import Optional

from .adsb_lol import AdsbLolClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch aircraft near a geographic point.")
    parser.add_argument("--lat", type=float, default=_env_float("VOGELVRIJ_LAT"))
    parser.add_argument("--lon", type=float, default=_env_float("VOGELVRIJ_LON"))
    parser.add_argument("--radius-nm", type=float, default=_env_float("VOGELVRIJ_RADIUS_NM"))
    parser.add_argument(
        "--no-store",
        action="store_true",
        help="print the response without storing it in PostgreSQL",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    missing = [
        name
        for name, value in (
            ("--lat", args.lat),
            ("--lon", args.lon),
            ("--radius-nm", args.radius_nm),
        )
        if value is None
    ]
    if missing:
        parser.error(
            "missing required location configuration: "
            + ", ".join(missing)
            + " (or set the corresponding VOGELVRIJ_* environment variables)"
        )

    client = AdsbLolClient()
    url = client.build_url(lat=args.lat, lon=args.lon, radius_nm=args.radius_nm)
    print(f"Calling: {url}")

    result = client.fetch_collection(lat=args.lat, lon=args.lon, radius_nm=args.radius_nm)
    print(json.dumps([plane.to_dict() for plane in result.aircraft], indent=2))
    print(f"Aircraft with positions: {len(result.aircraft)}")

    if not args.no_store:
        from .database import make_engine, session_scope
        from .repository import store_collection

        engine = make_engine()
        with session_scope(engine) as session:
            run = store_collection(
                session,
                result,
                request_lat=args.lat,
                request_lon=args.lon,
                request_radius_nm=args.radius_nm,
            )
            print(
                f"Stored collection run: {run.id} "
                f"({len(run.observations)} aircraft observations after filtering)"
            )
    return 0


def _env_float(name: str) -> Optional[float]:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return None
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
