from datetime import datetime, timezone

import pytest
import responses

from vogelvrij import weather


@responses.activate
def test_fetch_latest_ebbr_metar_and_convert_wind():
    responses.get(
        weather.METAR_URL,
        json=[
            {"icaoId": "EBBR", "obsTime": 1_767_225_600, "wdir": 270, "wspd": 10, "wgst": 15},
            {"icaoId": "EBBR", "obsTime": 1_767_229_200, "wdir": 360, "wspd": 12},
        ],
    )

    report = weather.fetch_latest_metar()
    observation = weather.wind_observation(report)

    assert responses.calls[0].request.headers["User-Agent"] == weather.USER_AGENT
    assert observation.observed_at == datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    assert observation.direction_degrees == 0
    assert observation.speed_mps == pytest.approx(12 * weather.KNOTS_TO_MPS)
    assert observation.gust_speed_mps is None
    assert observation.raw_data == report


@responses.activate
def test_no_content_metar_does_not_parse_json():
    responses.get(weather.METAR_URL, status=204)

    assert weather.fetch_latest_metar() is None


@pytest.mark.parametrize(
    "field,value", [("wdir", "VRB"), ("wdir", None), ("wspd", None), ("wspd", -1)]
)
def test_unusable_wind_is_not_stored(field, value):
    report = {"icaoId": "EBBR", "obsTime": 1_767_225_600, "wdir": 250, "wspd": 10}
    report[field] = value

    assert weather.wind_observation(report) is None


@responses.activate
def test_print_only_does_not_open_database(capsys):
    responses.get(
        weather.METAR_URL,
        json=[{"icaoId": "EBBR", "obsTime": 1_767_225_600, "wdir": 220, "wspd": 8}],
    )
    assert weather.main(["--no-store"]) == 0
    assert "wdir=220, wspd=8 kt" in capsys.readouterr().out
