from datetime import datetime, timezone

import pytest
import responses

from vogelvrij import taf

REPORT = {
    "icaoId": "EBBR",
    "issueTime": "2026-09-19T17:00:00.000Z",
    "validTimeFrom": 1789840800,
    "validTimeTo": 1789948800,
    "rawTAF": "TAF EBBR 191700Z 1918/2024 24012KT",
    "fcsts": [{"timeFrom": 1789840800, "timeTo": 1789948800, "wdir": 240, "wspd": 12}],
}


@responses.activate
def test_fetch_taf_and_print_without_database(capsys):
    responses.get(taf.TAF_URL, json=[REPORT])
    assert taf.main(["--no-store"]) == 0
    assert responses.calls[0].request.headers["User-Agent"] == taf.USER_AGENT
    assert "wdir=240, wspd=12 kt" in capsys.readouterr().out
    forecast = taf.taf_forecast(REPORT)
    assert forecast.issued_at == datetime(2026, 9, 19, 17, tzinfo=timezone.utc)
    assert forecast.station == "EBBR"


@responses.activate
def test_no_content_taf_does_not_parse_json():
    responses.get(taf.TAF_URL, status=204)
    assert taf.fetch_latest_taf() is None


def test_invalid_taf_validity_rejected():
    with pytest.raises(ValueError, match="validity"):
        taf.taf_forecast({**REPORT, "validTimeTo": REPORT["validTimeFrom"]})
