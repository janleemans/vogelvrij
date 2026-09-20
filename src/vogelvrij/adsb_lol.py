"""Client and response normalization for the public adsb.lol API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import requests

ADSB_LOL_BASE_URL = "https://api.adsb.lol/v2"
DEFAULT_USER_AGENT = "BrusselsPlaneTracker/1.0"
MAX_RADIUS_NM = 250.0


@dataclass(frozen=True)
class Aircraft:
    """An aircraft with a usable reported position."""

    hex: str
    flight: str
    lat: float
    lon: float
    altitude: Any
    speed: Any
    track: Any
    registration: str = ""
    aircraft_type: str = ""
    vertical_rate: Any = None
    raw_data: Dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result.pop("raw_data")
        return result


@dataclass(frozen=True)
class CollectionResult:
    """A complete API response split into its envelope and aircraft records."""

    aircraft: List[Aircraft]
    metadata: Dict[str, Any]
    raw_aircraft: List[Dict[str, Any]] = field(default_factory=list)


class AdsbLolClient:
    """Fetch aircraft located within a radius of a geographic point."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        user_agent: str = DEFAULT_USER_AGENT,
        session: Optional[requests.Session] = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if not user_agent.strip():
            raise ValueError("user_agent must not be blank")

        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.session = session or requests.Session()

    def build_url(self, *, lat: float, lon: float, radius_nm: float) -> str:
        _validate_search_area(lat=lat, lon=lon, radius_nm=radius_nm)
        return f"{ADSB_LOL_BASE_URL}/lat/{lat}/lon/{lon}/dist/{radius_nm}"

    def fetch_nearby(self, *, lat: float, lon: float, radius_nm: float) -> List[Aircraft]:
        """Return nearby aircraft that contain a valid latitude and longitude."""

        return self.fetch_collection(lat=lat, lon=lon, radius_nm=radius_nm).aircraft

    def fetch_collection(
        self, *, lat: float, lon: float, radius_nm: float
    ) -> CollectionResult:
        """Return normalized aircraft and all non-aircraft response metadata."""

        url = self.build_url(lat=lat, lon=lon, radius_nm=radius_nm)
        response = self.session.get(
            url,
            timeout=self.timeout_seconds,
            headers={"User-Agent": self.user_agent},
        )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError("adsb.lol returned a non-object JSON response")

        raw_aircraft = payload.get("ac", [])
        if not isinstance(raw_aircraft, list):
            raise ValueError("adsb.lol response field 'ac' is not a list")

        aircraft: List[Aircraft] = []
        raw_records: List[Dict[str, Any]] = []
        for plane in raw_aircraft:
            if isinstance(plane, Mapping):
                raw_records.append(dict(plane))
            normalized = _normalize_aircraft(plane)
            if normalized is not None:
                aircraft.append(normalized)

        metadata = {key: value for key, value in payload.items() if key != "ac"}
        return CollectionResult(
            aircraft=aircraft,
            metadata=metadata,
            raw_aircraft=raw_records,
        )


def _validate_search_area(*, lat: float, lon: float, radius_nm: float) -> None:
    if not -90 <= lat <= 90:
        raise ValueError("lat must be between -90 and 90")
    if not -180 <= lon <= 180:
        raise ValueError("lon must be between -180 and 180")
    if not 0 < radius_nm <= MAX_RADIUS_NM:
        raise ValueError(f"radius_nm must be greater than zero and at most {MAX_RADIUS_NM:g}")


def _normalize_aircraft(plane: object) -> Optional[Aircraft]:
    if not isinstance(plane, Mapping):
        return None

    lat = _position_number(plane.get("lat"))
    lon = _position_number(plane.get("lon"))
    if lat is None or lon is None:
        return None
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None

    return Aircraft(
        hex=_clean_text(plane.get("hex")),
        flight=_clean_text(plane.get("flight")),
        lat=lat,
        lon=lon,
        altitude=plane.get("alt_baro"),
        speed=plane.get("gs"),
        track=plane.get("track"),
        registration=_clean_text(plane.get("r")),
        aircraft_type=_clean_text(plane.get("t")),
        vertical_rate=plane.get("baro_rate"),
        raw_data=dict(plane),
    )


def _position_number(value: object) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _clean_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
