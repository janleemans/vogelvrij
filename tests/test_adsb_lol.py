import pytest
import responses

from vogelvrij.adsb_lol import AdsbLolClient


@responses.activate
def test_fetch_nearby_normalizes_aircraft_and_skips_missing_positions():
    url = "https://api.adsb.lol/v2/lat/50.85/lon/4.35/dist/25.0"
    responses.get(
        url,
        json={
            "ac": [
                {
                    "hex": "44abc1",
                    "flight": "BEL123  ",
                    "lat": 50.91,
                    "lon": 4.48,
                    "alt_baro": 3200,
                    "gs": 165.2,
                    "track": 247.5,
                    "r": "OO-ABC",
                    "t": "A320",
                    "baro_rate": -832,
                },
                {"hex": "missing-position", "lat": None, "lon": None},
                "not-an-aircraft-object",
            ]
        },
        status=200,
    )

    aircraft = AdsbLolClient().fetch_nearby(lat=50.85, lon=4.35, radius_nm=25.0)

    assert len(aircraft) == 1
    assert aircraft[0].flight == "BEL123"
    assert aircraft[0].registration == "OO-ABC"
    assert aircraft[0].vertical_rate == -832
    assert responses.calls[0].request.headers["User-Agent"] == "BrusselsPlaneTracker/1.0"


@pytest.mark.parametrize(
    ("lat", "lon", "radius_nm"),
    [
        (91, 4, 25),
        (50, 181, 25),
        (50, 4, 0),
        (50, 4, 251),
    ],
)
def test_invalid_search_area_is_rejected(lat, lon, radius_nm):
    with pytest.raises(ValueError):
        AdsbLolClient().build_url(lat=lat, lon=lon, radius_nm=radius_nm)


@responses.activate
def test_invalid_aircraft_list_is_rejected():
    url = "https://api.adsb.lol/v2/lat/50.85/lon/4.35/dist/25"
    responses.get(url, json={"ac": "unexpected"}, status=200)

    with pytest.raises(ValueError, match="not a list"):
        AdsbLolClient().fetch_nearby(lat=50.85, lon=4.35, radius_nm=25)


@responses.activate
def test_collection_preserves_raw_aircraft_without_positions():
    url = "https://api.adsb.lol/v2/lat/50.85/lon/4.35/dist/25"
    responses.get(
        url,
        json={
            "ac": [
                {"hex": "positioned", "lat": 50.8, "lon": 4.4},
                {"hex": "no-position", "flight": "TEST2"},
            ],
            "total": 2,
        },
        status=200,
    )

    result = AdsbLolClient().fetch_collection(lat=50.85, lon=4.35, radius_nm=25)

    assert len(result.aircraft) == 1
    assert len(result.raw_aircraft) == 2
    assert result.raw_aircraft[1]["hex"] == "no-position"
