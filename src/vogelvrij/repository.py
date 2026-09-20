"""Persistence operations for collected provider responses."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session

from .adsb_lol import CollectionResult
from .models import AircraftObservation, CollectionRun
from .movements import sync_movements_for_run

MAX_STORED_ALTITUDE_FT = 10_000
EXCLUDED_AIRCRAFT_TYPES = frozenset({"C152", "P28A","BT36","PIVI"})


def store_collection(
    session: Session,
    result: CollectionResult,
    *,
    request_lat: float,
    request_lon: float,
    request_radius_nm: float,
) -> CollectionRun:
    """Persist one API response and every positioned aircraft it contained."""

    metadata = result.metadata
    observed_at = _provider_datetime(metadata.get("now")) or datetime.now(timezone.utc)
    run = CollectionRun(
        provider="adsb.lol",
        request_lat=request_lat,
        request_lon=request_lon,
        request_radius_nm=request_radius_nm,
        response_message=_text(metadata.get("msg")),
        provider_now_ms=_integer(metadata.get("now")),
        provider_cached_at_ms=_integer(metadata.get("ctime")),
        provider_processing_ms=_number(metadata.get("ptime")),
        provider_total=_integer(metadata.get("total")),
        response_metadata=dict(metadata),
    )
    session.add(run)

    raw_records = result.raw_aircraft or [aircraft.raw_data for aircraft in result.aircraft]
    for raw_aircraft in raw_records:
        if not _should_store_aircraft(raw_aircraft):
            continue
        run.observations.append(_observation(raw_aircraft, observed_at=observed_at))

    session.flush()
    sync_movements_for_run(session, run)
    return run


def _should_store_aircraft(data: Mapping[str, Any]) -> bool:
    """Keep eligible airborne, low-altitude aircraft with valid positions."""

    aircraft_type = _text(data.get("t"))
    if aircraft_type and aircraft_type.upper() in EXCLUDED_AIRCRAFT_TYPES:
        return False

    barometric_altitude = data.get("alt_baro")
    if isinstance(barometric_altitude, str) and barometric_altitude.lower() == "ground":
        return False

    altitude_ft = _number(barometric_altitude)
    if altitude_ft is None:
        altitude_ft = _number(data.get("alt_geom"))

    if altitude_ft is None or altitude_ft > MAX_STORED_ALTITUDE_FT:
        return False

    lat = _number(data.get("lat"))
    lon = _number(data.get("lon"))
    if lat is None or lon is None:
        return False

    # Keep positions for maps/history; corridor and track filtering belongs to movement detection.
    return True


def _observation(data: Mapping[str, Any], *, observed_at: datetime) -> AircraftObservation:
    alt_baro = data.get("alt_baro")
    return AircraftObservation(
        observed_at=observed_at,
        hex=_text(data.get("hex")),
        address_type=_text(data.get("type")),
        flight=_text(data.get("flight")),
        registration=_text(data.get("r")),
        aircraft_type=_text(data.get("t")),
        description=_text(data.get("desc")),
        operator=_text(data.get("ownOp")),
        year=_integer(data.get("year")),
        db_flags=_integer(data.get("dbFlags")),
        lat=_number(data.get("lat")),
        lon=_number(data.get("lon")),
        alt_baro_ft=_integer(alt_baro),
        alt_baro_state=alt_baro if isinstance(alt_baro, str) else None,
        alt_geom_ft=_integer(data.get("alt_geom")),
        ground_speed_knots=_number(data.get("gs")),
        indicated_airspeed_knots=_number(data.get("ias")),
        true_airspeed_knots=_number(data.get("tas")),
        mach=_number(data.get("mach")),
        track_degrees=_number(data.get("track")),
        track_rate_dps=_number(data.get("track_rate")),
        roll_degrees=_number(data.get("roll")),
        magnetic_heading_degrees=_number(data.get("mag_heading")),
        true_heading_degrees=_number(data.get("true_heading")),
        barometric_rate_fpm=_integer(data.get("baro_rate")),
        geometric_rate_fpm=_integer(data.get("geom_rate")),
        squawk=_text(data.get("squawk")),
        emergency=_text(data.get("emergency")),
        category=_text(data.get("category")),
        nav_qnh_hpa=_number(data.get("nav_qnh")),
        nav_altitude_mcp_ft=_integer(data.get("nav_altitude_mcp")),
        nav_altitude_fms_ft=_integer(data.get("nav_altitude_fms")),
        nav_heading_degrees=_number(data.get("nav_heading")),
        nav_modes=_list_or_none(data.get("nav_modes")),
        nic=_integer(data.get("nic")),
        radius_of_containment_m=_integer(data.get("rc")),
        seen_position_seconds=_number(data.get("seen_pos")),
        adsb_version=_integer(data.get("version")),
        nic_baro=_integer(data.get("nic_baro")),
        nac_p=_integer(data.get("nac_p")),
        nac_v=_integer(data.get("nac_v")),
        sil=_integer(data.get("sil")),
        sil_type=_text(data.get("sil_type")),
        gva=_integer(data.get("gva")),
        sda=_integer(data.get("sda")),
        alert=_integer(data.get("alert")),
        spi=_integer(data.get("spi")),
        mlat_fields=_list_or_none(data.get("mlat")),
        tisb_fields=_list_or_none(data.get("tisb")),
        messages=_integer(data.get("messages")),
        seen_seconds=_number(data.get("seen")),
        rssi_dbfs=_number(data.get("rssi")),
        wind_direction_degrees=_number(data.get("wd")),
        wind_speed_knots=_number(data.get("ws")),
        outside_air_temperature_c=_number(data.get("oat")),
        total_air_temperature_c=_number(data.get("tat")),
        receiver_distance_nm=_number(data.get("dst", data.get("r_dst"))),
        receiver_direction_degrees=_number(data.get("dir", data.get("r_dir"))),
        rough_receiver_lat=_number(data.get("rr_lat")),
        rough_receiver_lon=_number(data.get("rr_lon")),
        last_position=_dict_or_none(data.get("lastPosition")),
        acas_resolution_advisory=_dict_or_none(data.get("acas_ra")),
        gps_ok_before=_number(data.get("gpsOkBefore")),
        gps_ok_lat=_number(data.get("gpsOkLat")),
        gps_ok_lon=_number(data.get("gpsOkLon")),
        raw_data=dict(data),
    )


def _provider_datetime(value: object) -> Optional[datetime]:
    timestamp = _number(value)
    if timestamp is None:
        return None
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _number(value: object) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _integer(value: object) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _text(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _list_or_none(value: object) -> Optional[list]:
    return list(value) if isinstance(value, list) else None


def _dict_or_none(value: object) -> Optional[dict]:
    return dict(value) if isinstance(value, Mapping) else None
