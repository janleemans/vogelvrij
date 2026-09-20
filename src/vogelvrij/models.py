"""SQLAlchemy models for observations and later flight enrichment."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False, default="adsb.lol")
    request_lat: Mapped[float] = mapped_column(Float, nullable=False)
    request_lon: Mapped[float] = mapped_column(Float, nullable=False)
    request_radius_nm: Mapped[float] = mapped_column(Float, nullable=False)
    response_message: Mapped[Optional[str]] = mapped_column(Text)
    provider_now_ms: Mapped[Optional[int]] = mapped_column(BigInteger)
    provider_cached_at_ms: Mapped[Optional[int]] = mapped_column(BigInteger)
    provider_processing_ms: Mapped[Optional[float]] = mapped_column(Float)
    provider_total: Mapped[Optional[int]] = mapped_column(Integer)
    response_metadata: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)

    observations: Mapped[List[AircraftObservation]] = relationship(
        back_populates="collection_run", cascade="all, delete-orphan"
    )


class FlightMovement(Base):
    """One detected approach encounter, available for later route enrichment."""

    __tablename__ = "flight_movements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    aircraft_icao: Mapped[Optional[str]] = mapped_column(Text)
    callsign: Mapped[Optional[str]] = mapped_column(Text)
    approach_corridor: Mapped[Optional[str]] = mapped_column(Text)
    first_observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    faf_altitude_ft: Mapped[Optional[int]] = mapped_column(Integer)
    faf_distance_m: Mapped[Optional[float]] = mapped_column(Float)
    wind_direction_degrees: Mapped[Optional[float]] = mapped_column(Float)
    wind_speed_knots: Mapped[Optional[float]] = mapped_column(Float)
    expected_approach: Mapped[Optional[str]] = mapped_column(Text)
    origin_airport_icao: Mapped[Optional[str]] = mapped_column(Text)
    origin_airport_iata: Mapped[Optional[str]] = mapped_column(Text)
    destination_airport_icao: Mapped[Optional[str]] = mapped_column(Text)
    destination_airport_iata: Mapped[Optional[str]] = mapped_column(Text)
    route_provider: Mapped[Optional[str]] = mapped_column(Text)
    route_enriched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    route_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)

    observations: Mapped[List[AircraftObservation]] = relationship(
        back_populates="flight_movement"
    )

    __table_args__ = (
        Index("ix_flight_movements_aircraft_created_at", "aircraft_icao", "created_at"),
    )


class AircraftObservation(Base):
    """One aircraft state returned by one geographic API request.

    Provider fields are nullable because ADS-B messages contain different subsets. `raw_data`
    retains fields that are new, experimental, nested, or not useful enough to normalize yet.
    """

    __tablename__ = "aircraft_observations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    collection_run_id: Mapped[int] = mapped_column(
        ForeignKey("collection_runs.id", ondelete="CASCADE"), nullable=False
    )
    flight_movement_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("flight_movements.id", ondelete="SET NULL")
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    hex: Mapped[Optional[str]] = mapped_column(Text)
    address_type: Mapped[Optional[str]] = mapped_column(Text)
    flight: Mapped[Optional[str]] = mapped_column(Text)
    registration: Mapped[Optional[str]] = mapped_column(Text)
    aircraft_type: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    operator: Mapped[Optional[str]] = mapped_column(Text)
    year: Mapped[Optional[int]] = mapped_column(Integer)
    db_flags: Mapped[Optional[int]] = mapped_column(Integer)

    lat: Mapped[Optional[float]] = mapped_column(Float)
    lon: Mapped[Optional[float]] = mapped_column(Float)
    alt_baro_ft: Mapped[Optional[int]] = mapped_column(Integer)
    alt_baro_state: Mapped[Optional[str]] = mapped_column(Text)
    alt_geom_ft: Mapped[Optional[int]] = mapped_column(Integer)
    ground_speed_knots: Mapped[Optional[float]] = mapped_column(Float)
    indicated_airspeed_knots: Mapped[Optional[float]] = mapped_column(Float)
    true_airspeed_knots: Mapped[Optional[float]] = mapped_column(Float)
    mach: Mapped[Optional[float]] = mapped_column(Float)
    track_degrees: Mapped[Optional[float]] = mapped_column(Float)
    track_rate_dps: Mapped[Optional[float]] = mapped_column(Float)
    roll_degrees: Mapped[Optional[float]] = mapped_column(Float)
    magnetic_heading_degrees: Mapped[Optional[float]] = mapped_column(Float)
    true_heading_degrees: Mapped[Optional[float]] = mapped_column(Float)
    barometric_rate_fpm: Mapped[Optional[int]] = mapped_column(Integer)
    geometric_rate_fpm: Mapped[Optional[int]] = mapped_column(Integer)

    squawk: Mapped[Optional[str]] = mapped_column(Text)
    emergency: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(Text)
    nav_qnh_hpa: Mapped[Optional[float]] = mapped_column(Float)
    nav_altitude_mcp_ft: Mapped[Optional[int]] = mapped_column(Integer)
    nav_altitude_fms_ft: Mapped[Optional[int]] = mapped_column(Integer)
    nav_heading_degrees: Mapped[Optional[float]] = mapped_column(Float)
    nav_modes: Mapped[Optional[List[str]]] = mapped_column(JSONB)

    nic: Mapped[Optional[int]] = mapped_column(Integer)
    radius_of_containment_m: Mapped[Optional[int]] = mapped_column(Integer)
    seen_position_seconds: Mapped[Optional[float]] = mapped_column(Float)
    adsb_version: Mapped[Optional[int]] = mapped_column(Integer)
    nic_baro: Mapped[Optional[int]] = mapped_column(Integer)
    nac_p: Mapped[Optional[int]] = mapped_column(Integer)
    nac_v: Mapped[Optional[int]] = mapped_column(Integer)
    sil: Mapped[Optional[int]] = mapped_column(Integer)
    sil_type: Mapped[Optional[str]] = mapped_column(Text)
    gva: Mapped[Optional[int]] = mapped_column(Integer)
    sda: Mapped[Optional[int]] = mapped_column(Integer)
    alert: Mapped[Optional[int]] = mapped_column(Integer)
    spi: Mapped[Optional[int]] = mapped_column(Integer)
    mlat_fields: Mapped[Optional[List[str]]] = mapped_column(JSONB)
    tisb_fields: Mapped[Optional[List[str]]] = mapped_column(JSONB)
    messages: Mapped[Optional[int]] = mapped_column(BigInteger)
    seen_seconds: Mapped[Optional[float]] = mapped_column(Float)
    rssi_dbfs: Mapped[Optional[float]] = mapped_column(Float)

    wind_direction_degrees: Mapped[Optional[float]] = mapped_column(Float)
    wind_speed_knots: Mapped[Optional[float]] = mapped_column(Float)
    outside_air_temperature_c: Mapped[Optional[float]] = mapped_column(Float)
    total_air_temperature_c: Mapped[Optional[float]] = mapped_column(Float)
    receiver_distance_nm: Mapped[Optional[float]] = mapped_column(Float)
    receiver_direction_degrees: Mapped[Optional[float]] = mapped_column(Float)
    rough_receiver_lat: Mapped[Optional[float]] = mapped_column(Float)
    rough_receiver_lon: Mapped[Optional[float]] = mapped_column(Float)
    last_position: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    acas_resolution_advisory: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    gps_ok_before: Mapped[Optional[float]] = mapped_column(Float)
    gps_ok_lat: Mapped[Optional[float]] = mapped_column(Float)
    gps_ok_lon: Mapped[Optional[float]] = mapped_column(Float)
    raw_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)

    collection_run: Mapped[CollectionRun] = relationship(back_populates="observations")
    flight_movement: Mapped[Optional[FlightMovement]] = relationship(
        back_populates="observations"
    )

    __table_args__ = (
        Index("ix_aircraft_observations_collection_run_id", "collection_run_id"),
        Index("ix_aircraft_observations_hex_observed", "hex", "observed_at"),
        Index("ix_aircraft_observations_flight_observed", "flight", "observed_at"),
        Index("ix_aircraft_observations_observed_at", "observed_at"),
    )


class WindObservation(Base):
    __tablename__ = "wind_observations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    direction_degrees: Mapped[float] = mapped_column(Float, nullable=False)
    speed_mps: Mapped[float] = mapped_column(Float, nullable=False)
    gust_speed_mps: Mapped[Optional[float]] = mapped_column(Float)
    source: Mapped[Optional[str]] = mapped_column(Text)
    raw_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)

    __table_args__ = (Index("ix_wind_observations_observed_at", "observed_at"),)


class TafForecast(Base):
    __tablename__ = "taf_forecasts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    station: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_taf: Mapped[str] = mapped_column(Text, nullable=False)
    raw_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        Index("ux_taf_forecasts_station_raw_taf", "station", "raw_taf", unique=True),
        Index("ix_taf_forecasts_station_issued", "station", "issued_at"),
    )
