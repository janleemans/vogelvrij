"""Checks for the approximate 01/19 map corridors."""

from math import asin, cos, radians, sin, sqrt

import pytest

from vogelvrij.geography import APPROACH_01, APPROACH_19, APPROACH_AREAS

EBBR_REFERENCE_POINT = (50.901389, 4.484444)


def _distance_nm(start, end):
    lat_a, lon_a = map(radians, start)
    lat_b, lon_b = map(radians, end)
    delta_lat = lat_b - lat_a
    delta_lon = lon_b - lon_a
    haversine = sin(delta_lat / 2) ** 2 + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    return 2 * 3440.065 * asin(sqrt(haversine))


@pytest.mark.parametrize(
    ("area", "threshold", "inbound_centerline", "outer_direction"),
    [
        (APPROACH_01, (50.88733056, 4.49157778), (50.77, 4.445), "south"),
        (APPROACH_19, (50.91101111, 4.50123889), (51.03, 4.548), "north"),
    ],
)
def test_01_and_19_corridors_cover_inbound_centerline_to_about_15_nm(
    area, threshold, inbound_centerline, outer_direction
):
    assert len(area.points) == 4
    assert area.contains(lat=inbound_centerline[0], lon=inbound_centerline[1])

    outer = area.points[1:3]
    outer_center = (
        (outer[0].lat + outer[1].lat) / 2,
        (outer[0].lon + outer[1].lon) / 2,
    )
    assert _distance_nm(EBBR_REFERENCE_POINT, outer_center) == pytest.approx(15, abs=0.1)
    if outer_direction == "south":
        assert outer_center[0] < threshold[0]
    else:
        assert outer_center[0] > threshold[0]


def test_01_corridor_includes_its_runway_threshold():
    assert APPROACH_01.contains(lat=50.88733056, lon=4.49157778)


def test_new_approach_areas_are_available_to_both_maps():
    assert APPROACH_AREAS[-2:] == (APPROACH_01, APPROACH_19)
