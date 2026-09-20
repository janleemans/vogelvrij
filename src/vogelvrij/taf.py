"""Collect an EBBR TAF bulletin separately from measured METAR wind."""

from __future__ import annotations

import argparse
import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Optional

import requests

TAF_URL = "https://aviationweather.gov/api/data/taf?ids=EBBR&format=json"
USER_AGENT = "VogelvrijTafCollector/1.0"


def timestamp(value: Any) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("TAF validity time must be a Unix timestamp")
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("TAF validity time is out of range") from exc


def issue_time(report: Mapping[str, Any]) -> datetime:
    value = report.get("issueTime")
    if not isinstance(value, str):
        raise ValueError("TAF issueTime is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("TAF issueTime is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("TAF issueTime needs a timezone")
    return parsed.astimezone(timezone.utc)


def fetch_latest_taf(session: Optional[requests.Session] = None) -> Optional[dict[str, Any]]:
    http = session or requests.Session()
    response = http.get(TAF_URL, timeout=15, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    if response.status_code == 204:
        return None
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("TAF API returned a non-list JSON response")
    reports = [
        report for report in payload
        if isinstance(report, dict) and report.get("icaoId") == "EBBR"
    ]
    if not reports:
        if not payload:
            return None
        raise ValueError("TAF API returned no EBBR report")
    return max(reports, key=issue_time)


def taf_forecast(report: Mapping[str, Any]):
    from .models import TafForecast

    raw_taf = report.get("rawTAF")
    if report.get("icaoId") != "EBBR" or not isinstance(raw_taf, str) or not raw_taf.strip():
        raise ValueError("TAF must contain an EBBR raw bulletin")
    valid_from = timestamp(report.get("validTimeFrom"))
    valid_to = timestamp(report.get("validTimeTo"))
    if valid_to <= valid_from:
        raise ValueError("TAF validity range is invalid")
    if not isinstance(report.get("fcsts"), list):
        raise ValueError("TAF forecast periods are missing")
    return TafForecast(
        station="EBBR",
        issued_at=issue_time(report),
        valid_from=valid_from,
        valid_to=valid_to,
        raw_taf=raw_taf,
        raw_data=dict(report),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch the latest EBBR TAF forecast.")
    parser.add_argument("--no-store", action="store_true", help="print without storing")
    args = parser.parse_args(argv)
    report = fetch_latest_taf()
    if report is None:
        print("No EBBR TAF available; nothing stored.")
        return 0
    forecast = taf_forecast(report)
    print(
        f"EBBR TAF issued {forecast.issued_at.isoformat()}, valid "
        f"{forecast.valid_from.isoformat()}–{forecast.valid_to.isoformat()}:"
    )
    for group in report["fcsts"]:
        if isinstance(group, dict):
            print(
                f"  {group.get('fcstChange') or 'BASE'} "
                f"{group.get('timeFrom')}–{group.get('timeBec') or group.get('timeTo')}: "
                f"wdir={group.get('wdir')!r}, wspd={group.get('wspd')!r} kt, "
                f"wgst={group.get('wgst')!r} kt"
            )
    if args.no_store:
        return 0

    from sqlalchemy import select

    from .database import make_engine, session_scope
    from .models import TafForecast

    with session_scope(make_engine()) as db:
        existing = db.scalar(
            select(TafForecast.id)
            .where(TafForecast.station == "EBBR", TafForecast.raw_taf == forecast.raw_taf)
            .limit(1)
        )
        if existing is not None:
            print(f"TAF already stored as forecast {existing}.")
        else:
            db.add(forecast)
            db.flush()
            print(f"Stored TAF forecast: {forecast.id}")
    return 0
