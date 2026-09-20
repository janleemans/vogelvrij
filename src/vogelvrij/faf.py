"""Reference points used to select a movement's closest observed altitude.

The 25LR and 19 points are project comparison points, not published FAFs.
"""

from __future__ import annotations

from math import asin, atan2, cos, degrees, radians, sin, sqrt

from .geography import GeoPoint

EARTH_RADIUS_M = 6_371_008.8


def distance_m(first: GeoPoint, second: GeoPoint) -> float:
    """Great-circle distance between two WGS84-style latitude/longitude points."""
    lat1, lon1, lat2, lon2 = map(
        radians, (first.lat, first.lon, second.lat, second.lon)
    )
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    haversine = (
        sin(delta_lat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * asin(min(1.0, sqrt(haversine)))


def destination(start: GeoPoint, bearing_degrees: float, distance_metres: float) -> GeoPoint:
    """Point reached on a great-circle path from a start, true bearing and distance."""
    latitude = radians(start.lat)
    longitude = radians(start.lon)
    bearing = radians(bearing_degrees)
    angular_distance = distance_metres / EARTH_RADIUS_M
    end_latitude = asin(
        sin(latitude) * cos(angular_distance)
        + cos(latitude) * sin(angular_distance) * cos(bearing)
    )
    end_longitude = longitude + atan2(
        sin(bearing) * sin(angular_distance) * cos(latitude),
        cos(angular_distance) - sin(latitude) * sin(end_latitude),
    )
    return GeoPoint(degrees(end_latitude), degrees(end_longitude))


FAF_01 = GeoPoint(50.795306, 4.453861)  # User-supplied BR01F reference.
FAF_07LR = GeoPoint(50.879167, 4.309167)  # User-supplied FD07L reference.

# Published B25LF/B25RF coordinates (Belgian AIP EBBR AD 2.20), converted
# from degrees/minutes/seconds. Their midpoint is a provisional shared 25LR
# comparison point, not a charted waypoint or an actual FAF.
FAF_25L = GeoPoint(50 + 55 / 60 + 52.2 / 3600, 4 + 39 / 60 + 47.1 / 3600)
FAF_25R = GeoPoint(50 + 57 / 60 + 5.9 / 3600, 4 + 38 / 60 + 18.2 / 3600)
FAF_25LR = GeoPoint(
    (FAF_25L.lat + FAF_25R.lat) / 2,
    (FAF_25L.lon + FAF_25R.lon) / 2,
)

# The user's runway-19 comparison point is a synthetic point on the extended
# runway centreline, at the same threshold distance as their runway-01 point.
# The 01/19 thresholds and 19 true bearing are from Belgian AIP EBBR AD 2.12.
THRESHOLD_01 = GeoPoint(50 + 53 / 60 + 14.39 / 3600, 4 + 29 / 60 + 29.68 / 3600)
THRESHOLD_19 = GeoPoint(50 + 54 / 60 + 39.64 / 3600, 4 + 30 / 60 + 4.46 / 3600)
FAF_19_REFERENCE = destination(
    THRESHOLD_19, 14.43, distance_m(THRESHOLD_01, FAF_01)
)

FAF_REFERENCES = {
    "01": FAF_01,
    "07LR": FAF_07LR,
    "19": FAF_19_REFERENCE,
    "25LR": FAF_25LR,
}
