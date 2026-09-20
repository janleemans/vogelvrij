"""Named geographic areas used by movement detection and map overlays."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float


@dataclass(frozen=True)
class ApproachArea:
    name: str
    points: Tuple[GeoPoint, GeoPoint, GeoPoint, GeoPoint]

    def contains(self, *, lat: float, lon: float) -> bool:
        """Return whether a coordinate is inside or on the polygon boundary."""

        point = GeoPoint(lat=lat, lon=lon)
        inside = False
        previous = self.points[-1]

        for current in self.points:
            if _point_is_on_segment(point, previous, current):
                return True

            crosses_latitude = (current.lat > lat) != (previous.lat > lat)
            if crosses_latitude:
                crossing_lon = (
                    (previous.lon - current.lon)
                    * (lat - current.lat)
                    / (previous.lat - current.lat)
                    + current.lon
                )
                if lon < crossing_lon:
                    inside = not inside

            previous = current

        return inside


def _point_is_on_segment(point: GeoPoint, start: GeoPoint, end: GeoPoint) -> bool:
    cross_product = (point.lon - start.lon) * (end.lat - start.lat) - (
        point.lat - start.lat
    ) * (end.lon - start.lon)
    if abs(cross_product) > 1e-12:
        return False

    return (
        min(start.lat, end.lat) <= point.lat <= max(start.lat, end.lat)
        and min(start.lon, end.lon) <= point.lon <= max(start.lon, end.lon)
    )


APPROACH_25LR = ApproachArea(
    name="25LR Approach",
    points=(
        GeoPoint(lat=50.91987309755571, lon=4.514245300802378),
        GeoPoint(lat=51.04612423065292, lon=4.742741550776375),
        GeoPoint(lat=50.95089416760156, lon=4.834976170968464),
        GeoPoint(lat=50.892291454259166, lon=4.545968016656692),
    ),
)

APPROACH_7LR = ApproachArea(
    name="7LR Approach",
    points=(
        GeoPoint(lat=50.87768795368042, lon=4.458039848279057),
        GeoPoint(lat=50.897886385696516, lon=4.42721938869695),
        GeoPoint(lat=50.862354623043146, lon=4.094872908671149),
        GeoPoint(lat=50.75781521822144, lon=4.152877963570074),
    ),
)

# Broad planning corridors, not published approach-procedure boundaries. Their
# Outer edges widen toward the 15 NM circle around EBBR. Runway-threshold
# inclusion is not a requirement for these inbound observation corridors.
# Thresholds and true runway bearing: Belgian AIP, EBBR AD 2.12.
APPROACH_01 = ApproachArea(
    name="01 Approach",
    points=(
        GeoPoint(lat=50.89244669, lon=4.47594317),
        GeoPoint(lat=50.66688745, lon=4.34107385),
        GeoPoint(lat=50.64821027, lon=4.45556957),
        GeoPoint(lat=50.88705106, lon=4.50918432),
    ),
)

APPROACH_19 = ApproachArea(
    name="19 Approach",
    points=(
        GeoPoint(lat=50.920162053335346, lon=4.512586810648918),
        GeoPoint(lat=51.13187095, lon=4.65350444),
        GeoPoint(lat=51.15054813, lon=4.53781323),
        GeoPoint(lat=50.91128824, lon=4.48362329),
    ),
)

APPROACH_AREAS = (APPROACH_25LR, APPROACH_7LR, APPROACH_01, APPROACH_19)
