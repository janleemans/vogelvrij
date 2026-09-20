import pytest

from vogelvrij.runway_prediction import predict_landing_approach


@pytest.mark.parametrize(
    ("direction", "speed", "expected"),
    [
        (240, 12, "25LR"),
        (180, 12, "25LR"),  # Preference wins while 25LR remains feasible.
        (180, 30, "19"),
        (90, 20, "07LR"),
        (0, 25, "01"),
        (360, 25, "01"),
        (135, 100, None),
    ],
)
def test_preferred_then_wind_aligned_approach(direction, speed, expected):
    assert predict_landing_approach(direction, speed) == expected


def test_gust_is_used_for_feasibility():
    assert predict_landing_approach(180, 8) == "25LR"
    assert predict_landing_approach(180, 8, 30) == "19"


@pytest.mark.parametrize("direction,speed", [(None, 10), ("VRB", 10), (90, None), (90, -1)])
def test_unusable_forecast_wind_has_no_prediction(direction, speed):
    assert predict_landing_approach(direction, speed) is None


def test_25lr_considers_both_parallel_ends():
    # At this wind 25L exceeds 7 kt tailwind, while 25R remains below it.
    assert predict_landing_approach(90, 7.5) == "25LR"
    assert predict_landing_approach(90, 8) == "07LR"
