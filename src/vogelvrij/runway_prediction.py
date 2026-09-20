"""Indicative EBBR landing approach from forecast wind alone.

True runway bearings come from Belgian AIP EBBR AD 2.12. Wind criteria come
from EBBR AD 2.20 §4.2.2–4.2.3. This is not an ATC runway assignment model.
"""

from __future__ import annotations

import math
from typing import Optional

# Parallel runway ends differ by a few degrees; either end can qualify its group.
TRUE_HEADINGS = {
    "25LR": (249.89, 245.35),
    "19": (194.43,),
    "07LR": (69.89, 65.35),
    "01": (14.43,),
}
CROSSWIND_LIMIT = 20.0


def _usable_number(value: object, minimum: float, maximum: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and minimum <= value <= maximum
    )


def _wind_components(direction: float, speed: float, heading: float) -> tuple[float, float]:
    angle = math.radians((direction - heading) % 360)
    headwind = speed * math.cos(angle)
    crosswind = abs(speed * math.sin(angle))
    return max(0.0, -headwind), crosswind


def predict_landing_approach(
    direction: object, speed: object, gust: object = None
) -> Optional[str]:
    """Choose the preferred wind-feasible group, or None when wind is insufficient.

    A 7 kt tailwind or 20 kt crosswind rules out 25LR. On alternatives, exactly
    3 kt tailwind remains allowed per the AIP; greater than 3 kt rules it out.
    Gust speed, if reported, is the conservative speed for both components.
    """
    if not _usable_number(direction, 0, 360) or not _usable_number(speed, 0, math.inf):
        return None
    wind_speed = float(speed)
    if _usable_number(gust, 0, math.inf):
        wind_speed = max(wind_speed, float(gust))

    def eligible(heading: float, tailwind_limit: float, inclusive: bool) -> bool:
        tailwind, crosswind = _wind_components(float(direction), wind_speed, heading)
        tailwind_ok = tailwind <= tailwind_limit if inclusive else tailwind < tailwind_limit
        return tailwind_ok and crosswind < CROSSWIND_LIMIT

    if any(eligible(heading, 7, False) for heading in TRUE_HEADINGS["25LR"]):
        return "25LR"

    candidates = []
    for group in ("19", "07LR", "01"):
        for heading in TRUE_HEADINGS[group]:
            if eligible(heading, 3, True):
                distance = abs((float(direction) - heading + 180) % 360 - 180)
                candidates.append((distance, group))
    return min(candidates)[1] if candidates else None
