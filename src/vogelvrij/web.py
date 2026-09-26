"""Small read-only public page backed by detected flight movements."""

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
from datetime import datetime, time, timedelta, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vogelvrij.database import make_engine
from vogelvrij.map_history import TEMPLATE as HISTORY_TEMPLATE
from vogelvrij.map_history import load_recent_runs
from vogelvrij.map_page import render_html
from vogelvrij.models import CollectionRun, FlightMovement, TafForecast, WindObservation
from vogelvrij.runway_prediction import predict_landing_approach
from vogelvrij.taf import timestamp
from vogelvrij.weather import WIND_SOURCE, stored_wind_values

BRUSSELS = ZoneInfo("Europe/Brussels")
CORRIDORS = ("07LR", "25LR", "01", "19")
# Nominal magnetic headings inferred from the runway designators. The 07/25
# cards combine parallel runways and do not identify a specific runway end.
RUNWAY_HEADINGS = {"07LR": 70, "25LR": 250, "01": 10, "19": 190}
TAILWIND_LIMITS = {"07LR": 3, "25LR": 7, "01": 3, "19": 3}
NO_WIND_COMPONENTS = "Windcomponenten niet beschikbaar."
WIND_LIGHT_LABELS = {
    "green": "Onder de ingestelde winddrempels",
    "unknown": "Geen windmeting beschikbaar",
}
TEMPLATE = files("vogelvrij").joinpath("templates/public_page.html")
SCRIPT = files("vogelvrij").joinpath("templates/public_page.js")
PAGE_CSP = (
    "default-src 'none'; img-src https://bruegelvogelvrij.be; "
    "style-src 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
    "frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
MAP_FALLBACK_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'; base-uri 'none'"
)


def web_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("web port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("web port must be between 1 and 65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the read-only public flight page")
    parser.add_argument("--host", default=os.environ.get("VOGELVRIJ_WEB_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=web_port,
        default=os.environ.get("VOGELVRIJ_WEB_PORT", 8766),
    )
    return parser


def map_csp(nonce: str) -> str:
    """Separate policy for the Maps JavaScript API document inside the iframe."""
    return (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}' 'strict-dynamic' https: 'unsafe-eval' blob:; "
        f"style-src 'nonce-{nonce}' https://fonts.googleapis.com; "
        "img-src 'self' https://*.googleapis.com https://*.gstatic.com "
        "https://*.google.com https://*.googleusercontent.com data:; "
        "connect-src 'self' https://*.googleapis.com https://*.google.com "
        "https://*.gstatic.com data: blob:; "
        "font-src https://fonts.gstatic.com; frame-src https://*.google.com; "
        "worker-src blob:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
    )


def today_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Return half-open local-day bounds as UTC instants, including DST transitions."""
    local_date = now.astimezone(BRUSSELS).date()
    start = datetime.combine(local_date, time.min, BRUSSELS)
    end = datetime.combine(local_date + timedelta(days=1), time.min, BRUSSELS)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def movement_data(session: Session, now: datetime) -> tuple[dict[str, int], list[FlightMovement]]:
    start, end = today_bounds(now)
    counts = dict.fromkeys(CORRIDORS, 0)
    query = (
        select(FlightMovement.approach_corridor, func.count())
        .where(FlightMovement.created_at >= start, FlightMovement.created_at < end)
        .group_by(FlightMovement.approach_corridor)
    )
    for corridor, count in session.execute(query):
        if corridor in counts:
            counts[corridor] = count
    recent = session.scalars(
        select(FlightMovement)
        .order_by(FlightMovement.created_at.desc(), FlightMovement.id.desc())
        .limit(10)
    ).all()
    return counts, recent


def history_data(session: Session, now: datetime) -> dict:
    """Seven Belgian days, newest first, and 24 UTC hours labelled in Belgian time."""
    today = now.astimezone(BRUSSELS).date()
    first_day = today - timedelta(days=6)
    first_instant = datetime.combine(first_day, time.min, BRUSSELS).astimezone(timezone.utc)
    current_hour = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    first_hour = current_hour - timedelta(hours=23)
    days = []
    for offset in range(6, -1, -1):
        day = first_day + timedelta(days=offset)
        days.append({
            "date": day.isoformat(), "label": day.strftime("%d/%m"),
            "counts": dict.fromkeys(CORRIDORS, 0), "total": 0, "runs": 0,
        })
    hours = []
    for offset in range(24):
        instant = first_hour + timedelta(hours=offset)
        local = instant.astimezone(BRUSSELS)
        hours.append({
            "start": instant.isoformat(),
            "label": local.strftime("%d/%m %H:00 %Z"),
            "counts": dict.fromkeys(CORRIDORS, 0), "total": 0, "runs": 0,
        })
    day_lookup = {day["date"]: day for day in days}
    hour_lookup = {hour["start"]: hour for hour in hours}
    movement_hour = func.date_trunc("hour", func.timezone("UTC", FlightMovement.created_at))
    movements = session.execute(
        select(movement_hour, FlightMovement.approach_corridor, func.count()).where(
            FlightMovement.created_at >= first_instant, FlightMovement.created_at <= now
        ).group_by(movement_hour, FlightMovement.approach_corridor)
    )
    for utc_hour, corridor, count in movements:
        if corridor not in CORRIDORS:
            continue
        instant = utc_hour.replace(tzinfo=timezone.utc)
        day = day_lookup[instant.astimezone(BRUSSELS).date().isoformat()]
        day["counts"][corridor] += count
        day["total"] += count
        hour = hour_lookup.get(instant.isoformat())
        if hour is not None:
            hour["counts"][corridor] += count
            hour["total"] += count
    run_hour = func.date_trunc("hour", func.timezone("UTC", CollectionRun.requested_at))
    runs = session.execute(
        select(run_hour, func.count()).where(
            CollectionRun.requested_at >= first_instant, CollectionRun.requested_at <= now
        ).group_by(run_hour)
    )
    for utc_hour, count in runs:
        instant = utc_hour.replace(tzinfo=timezone.utc)
        day_lookup[instant.astimezone(BRUSSELS).date().isoformat()]["runs"] += count
        hour = hour_lookup.get(instant.isoformat())
        if hour is not None:
            hour["runs"] += count
    return {"days": days, "hours": hours}


def latest_run_id(session: Session) -> int | None:
    return session.scalar(select(CollectionRun.id).order_by(CollectionRun.id.desc()).limit(1))


def latest_wind(session: Session) -> WindObservation | None:
    return session.scalars(
        select(WindObservation)
        .where(WindObservation.source == WIND_SOURCE)
        .order_by(WindObservation.observed_at.desc(), WindObservation.id.desc())
        .limit(1)
    ).first()


def latest_taf(session: Session, now: datetime) -> TafForecast | None:
    current = session.scalars(
        select(TafForecast)
        .where(TafForecast.station == "EBBR", TafForecast.valid_from <= now,
               TafForecast.valid_to > now)
        .order_by(TafForecast.issued_at.desc(), TafForecast.id.desc())
        .limit(1)
    ).first()
    if current is not None:
        return current
    return session.scalars(
        select(TafForecast)
        .where(TafForecast.station == "EBBR")
        .order_by(TafForecast.issued_at.desc(), TafForecast.id.desc())
        .limit(1)
    ).first()


def local_time(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(BRUSSELS).strftime("%d/%m/%Y %H:%M")


def display(value: str | None) -> str:
    return escape(value.strip()) if value and value.strip() else "—"


def plain(value: str | None) -> str:
    return value.strip() if value and value.strip() else "—"


def altitude(value: int | None) -> str:
    return f"{value} ft" if value is not None else "—"


def theoretical_runway_cell(corridor: str | None, expected: str | None) -> str:
    """Color only a known theoretical approach, without implying a confirmed landing."""
    value = display(expected)
    if not corridor or not corridor.strip() or not expected or not expected.strip():
        return f"<td>{value}</td>"
    if corridor.strip() == expected.strip():
        return (
            '<td class="theoretical-runway-match" '
            'title="Komt overeen met de gedetecteerde baan">' + value + "</td>"
        )
    return (
        '<td class="theoretical-runway-mismatch" '
        'title="Wijkt af van de gedetecteerde baan">' + value + "</td>"
    )


def movement_rows(recent: list[FlightMovement]) -> list[list[str]]:
    return [
        [
            plain(movement.callsign),
            plain(movement.approach_corridor),
            plain(movement.expected_approach),
            altitude(movement.faf_altitude_ft),
            local_time(movement.first_observed_at),
            local_time(movement.last_observed_at),
        ]
        for movement in recent
    ]


def wind_display(wind: WindObservation | None) -> dict | None:
    if wind is None:
        return None
    direction, speed, gust = stored_wind_values(wind)
    approach = predict_landing_approach(direction, speed, gust)
    lights = {
        corridor: wind_light(direction, speed, heading, TAILWIND_LIMITS[corridor])
        for corridor, heading in RUNWAY_HEADINGS.items()
    }
    return {
        "direction": f"{direction:g}°",
        "speed": f"{speed:g} kt",
        "bearing": (wind.direction_degrees + 180) % 360,
        "observed": local_time(wind.observed_at),
        "approach": approach or "Geen betrouwbare voorspelling",
        "components": {
            corridor: wind_component(direction, speed, heading)
            for corridor, heading in RUNWAY_HEADINGS.items()
        },
        "lights": lights,
        "light_labels": {
            corridor: wind_light_label(corridor, status)
            for corridor, status in lights.items()
        },
    }


def _wind_component_values(
    direction: float, speed: float, runway_heading: float
) -> tuple[float, float]:
    alpha = math.radians(abs(direction - runway_heading))
    headwind = speed * math.cos(alpha)
    crosswind = abs(speed * math.sin(alpha))
    return headwind, crosswind


def wind_component(direction: float, speed: float, runway_heading: float) -> str:
    """Display estimated along-runway and unsigned crosswind components, in knots."""
    headwind, crosswind = _wind_component_values(direction, speed, runway_heading)
    along_label = "Tegenwind" if headwind >= 0 else "Rugwind"
    return f"{along_label} {abs(headwind):.1f} kt · Zijwind {crosswind:.1f} kt"


def wind_light(
    direction: float, speed: float, runway_heading: float, tailwind_limit: float
) -> str:
    """Flag raw components before rounding, including the AIP's 3 kt boundary."""
    headwind, crosswind = _wind_component_values(direction, speed, runway_heading)
    tailwind_exceeded = (
        headwind < -tailwind_limit if tailwind_limit == 3 else headwind <= -tailwind_limit
    )
    return "red" if tailwind_exceeded or crosswind >= 20 else "green"


def wind_light_label(corridor: str, status: str) -> str:
    if status == "red":
        tailwind_label = (
            "meer dan 3 kt" if TAILWIND_LIMITS[corridor] == 3 else "minstens 7 kt"
        )
        return (
            f"Drempel bereikt: rugwind {tailwind_label} "
            "of zijwind minstens 20 kt"
        )
    return WIND_LIGHT_LABELS[status]


def forecast_display(taf: TafForecast | None, now: datetime) -> dict | None:
    """Return only display fields; missing TEMPO wind never resets prevailing wind."""
    if taf is None:
        return None
    raw = taf.raw_data if isinstance(taf.raw_data, dict) else {}
    groups = raw.get("fcsts")
    if not isinstance(groups, list):
        return None
    periods = []
    prevailing_approach = None
    for group in groups:
        if not isinstance(group, dict):
            continue
        direction, speed, gust = (group.get(key) for key in ("wdir", "wspd", "wgst"))
        if (
            isinstance(direction, bool) or not isinstance(direction, (int, float))
            or not math.isfinite(direction) or not 0 <= direction <= 360
            or isinstance(speed, bool) or not isinstance(speed, (int, float))
            or not math.isfinite(speed) or speed < 0
        ):
            continue
        if (
            isinstance(gust, bool) or not isinstance(gust, (int, float))
            or not math.isfinite(gust) or gust < 0
        ):
            gust = None
        try:
            start = timestamp(group.get("timeFrom"))
            end = timestamp(group.get("timeTo"))
            change = group.get("fcstChange")
            transition_end = timestamp(group.get("timeBec")) if change == "BECMG" else None
        except ValueError:
            continue
        if end <= start or (change == "BECMG" and not start < transition_end <= end):
            continue
        approach = predict_landing_approach(direction, speed, gust)
        details = {
            "direction": f"{direction:g}°",
            "speed": f"{speed:g} kt" + (f" · stoten {gust:g} kt" if gust is not None else ""),
            "bearing": (direction + 180) % 360,
        }
        if change == "BECMG":
            transition_approach = (
                f"{prevailing_approach} → {approach}"
                if prevailing_approach and approach and prevailing_approach != approach
                else approach if prevailing_approach == approach else None
            )
            periods.append({
                **details, "kind": "transition", "label": "Geleidelijke overgang",
                "from": local_time(start), "to": local_time(transition_end),
                "approach": transition_approach or "Geen betrouwbare voorspelling",
                "approach_label": "Mogelijke naderingsbaan",
            })
            start = transition_end
        elif change in ("TEMPO", "PROB", "PROB30", "PROB40"):
            periods.append({
                **details, "kind": "temporary", "label": "Tijdelijk mogelijk",
                "from": local_time(start), "to": local_time(end),
                "approach": approach or "Geen betrouwbare voorspelling",
                "approach_label": "Mogelijke naderingsbaan",
            })
            continue
        if start < end:
            periods.append({
                **details, "kind": "prevailing", "label": "Verwacht",
                "from": local_time(start), "to": local_time(end),
                "approach": approach or "Geen betrouwbare voorspelling",
                "approach_label": "Verwachte naderingsbaan",
            })
        prevailing_approach = approach
    return {
        "id": taf.id,
        "status": (
            "upcoming" if now < taf.valid_from else "expired" if now >= taf.valid_to else "current"
        ),
        "status_label": (
            "Nog niet geldig" if now < taf.valid_from
            else "Verlopen" if now >= taf.valid_to else "Actueel"
        ),
        "issued": local_time(taf.issued_at),
        "valid": f"{local_time(taf.valid_from)} – {local_time(taf.valid_to)}",
        "periods": periods,
    }


def forecast_cards(periods: list[dict]) -> str:
    return "".join(
        '<article class="forecast-period forecast-' + escape(period["kind"]) + '">'
        '<span class="forecast-period-label">' + escape(period["label"]) + '</span>'
        '<span class="forecast-time">' + escape(period["from"]) + ' – '
        + escape(period["to"]) + '</span>'
        '<span class="forecast-wind"><span class="forecast-arrow" aria-hidden="true" '
        f'style="transform:rotate({period["bearing"]:g}deg)">↑</span>'
        '<span><strong>Wind uit ' + escape(period["direction"]) + '</strong>'
        '<small>' + escape(period["speed"]) + '</small></span></span>'
        '<span class="forecast-approach"><small>' + escape(period["approach_label"])
        + '</small><strong>' + escape(period["approach"]) + '</strong></span></article>'
        for period in periods
    )


def history_bars(counts: dict[str, int], total: int, scale: int, vertical: bool = False) -> str:
    if not total:
        return ""
    return "".join(
        f'<span class="history-segment corridor-{corridor.lower()}" '
        f'style="{("height" if vertical else "width")}:{count / scale * 100:.3f}%"></span>'
        for corridor in CORRIDORS
        if (count := counts[corridor])
    )


def history_markup(history: dict) -> tuple[str, str]:
    days = history["days"]
    hours = history["hours"]
    day_scale = max((day["total"] for day in days), default=0) or 1
    hour_scale = max((hour["total"] for hour in hours), default=0) or 1
    daily = "".join(
        '<div class="daily-row">'
        f'<time datetime="{day["date"]}">{day["label"]}</time>'
        f'<span class="daily-bar" aria-hidden="true">'
        f'{history_bars(day["counts"], day["total"], day_scale)}</span>'
        f'<strong>{day["total"]}</strong>'
        '<span class="daily-detail">'
        + " · ".join(f"{corridor}: {day['counts'][corridor]}" for corridor in CORRIDORS)
        + f' · meetrondes: {day["runs"]}</span></div>'
        for day in days
    )
    def hour_markup(hour: dict) -> str:
        detail = (
            f'{hour["label"]}: {hour["total"]} detecties, {hour["runs"]} meetrondes; '
            + ", ".join(f"{corridor} {hour['counts'][corridor]}" for corridor in CORRIDORS)
        )
        return (
            '<div class="hour-column" '
            f'role="img" aria-label="{detail}" title="{detail}">'
            '<span class="hour-bar" aria-hidden="true">'
            f'{history_bars(hour["counts"], hour["total"], hour_scale, vertical=True)}'
            f'</span><span class="hour-total" aria-hidden="true">{hour["total"]}</span>'
            f'<span class="hour-label">{hour["label"][:5]}<br>{hour["label"][6:11]}</span>'
            '</div>'
        )

    hourly = "".join(hour_markup(hour) for hour in hours)
    return daily, hourly


def snapshot(
    counts: dict[str, int],
    recent: list[FlightMovement],
    now: datetime,
    map_run_id: int | None = None,
    wind: WindObservation | None = None,
    taf: TafForecast | None = None,
    history: dict | None = None,
) -> dict:
    local_now = now.astimezone(BRUSSELS)
    return {
        "date": local_now.strftime("%d/%m/%Y"),
        "updated": local_now.strftime("%H:%M"),
        "counts": counts,
        "rows": movement_rows(recent),
        "map_run_id": map_run_id,
        "wind": wind_display(wind),
        "forecast": forecast_display(taf, now),
        "history": history,
    }


def render_page(
    counts: dict[str, int],
    recent: list[FlightMovement],
    now: datetime,
    wind: WindObservation | None = None,
    taf: TafForecast | None = None,
    history: dict | None = None,
) -> str:
    if recent:
        rows = "\n".join(
            "<tr>"
            f"<td>{display(movement.callsign)}</td>"
            f"<td>{display(movement.approach_corridor)}</td>"
            f"{theoretical_runway_cell(movement.approach_corridor, movement.expected_approach)}"
            f"<td>{altitude(movement.faf_altitude_ft)}</td>"
            f"<td><time>{local_time(movement.first_observed_at)}</time></td>"
            f"<td><time>{local_time(movement.last_observed_at)}</time></td>"
            "</tr>"
            for movement in recent
        )
    else:
        rows = '<tr><td colspan="6" class="empty">Nog geen bewegingen geregistreerd.</td></tr>'
    template = TEMPLATE.read_text(encoding="utf-8")
    wind_values = wind_display(wind)
    components = wind_values["components"] if wind_values else {}
    lights = wind_values["lights"] if wind_values else {}
    light_labels = wind_values["light_labels"] if wind_values else {}
    unknown_label = WIND_LIGHT_LABELS["unknown"]
    forecast = forecast_display(taf, now)
    daily, hourly = history_markup(history) if history else ("", "")
    return (
        template.replace("{{DATE}}", now.astimezone(BRUSSELS).strftime("%d/%m/%Y"))
        .replace("{{UPDATED}}", now.astimezone(BRUSSELS).strftime("%H:%M"))
        .replace("{{COUNT_07LR}}", str(counts["07LR"]))
        .replace("{{COUNT_25LR}}", str(counts["25LR"]))
        .replace("{{COUNT_01}}", str(counts["01"]))
        .replace("{{COUNT_19}}", str(counts["19"]))
        .replace("{{WIND_CONTENT_HIDDEN}}", "" if wind_values else "hidden")
        .replace("{{WIND_EMPTY_HIDDEN}}", "hidden" if wind_values else "")
        .replace("{{WIND_DIRECTION}}", wind_values["direction"] if wind_values else "—")
        .replace("{{WIND_SPEED}}", wind_values["speed"] if wind_values else "—")
        .replace("{{WIND_OBSERVED}}", wind_values["observed"] if wind_values else "—")
        .replace("{{WIND_APPROACH}}", wind_values["approach"] if wind_values else "—")
        .replace("{{WIND_APPROACH_HIDDEN}}", "" if wind_values else "hidden")
        .replace("{{WIND_BEARING}}", f"{wind_values['bearing']:g}" if wind_values else "0")
        .replace("{{WIND_COMPONENT_07LR}}", components.get("07LR", NO_WIND_COMPONENTS))
        .replace("{{WIND_COMPONENT_25LR}}", components.get("25LR", NO_WIND_COMPONENTS))
        .replace("{{WIND_COMPONENT_01}}", components.get("01", NO_WIND_COMPONENTS))
        .replace("{{WIND_COMPONENT_19}}", components.get("19", NO_WIND_COMPONENTS))
        .replace("{{WIND_LIGHT_07LR}}", lights.get("07LR", "unknown"))
        .replace("{{WIND_LIGHT_25LR}}", lights.get("25LR", "unknown"))
        .replace("{{WIND_LIGHT_01}}", lights.get("01", "unknown"))
        .replace("{{WIND_LIGHT_19}}", lights.get("19", "unknown"))
        .replace("{{WIND_LIGHT_LABEL_07LR}}", light_labels.get("07LR", unknown_label))
        .replace("{{WIND_LIGHT_LABEL_25LR}}", light_labels.get("25LR", unknown_label))
        .replace("{{WIND_LIGHT_LABEL_01}}", light_labels.get("01", unknown_label))
        .replace("{{WIND_LIGHT_LABEL_19}}", light_labels.get("19", unknown_label))
        .replace("{{FORECAST_ID}}", str(forecast["id"]) if forecast else "")
        .replace(
            "{{FORECAST_CONTENT_HIDDEN}}", "" if forecast and forecast["periods"] else "hidden"
        )
        .replace("{{FORECAST_EMPTY_HIDDEN}}", "hidden" if forecast and forecast["periods"] else "")
        .replace("{{FORECAST_ISSUED}}", forecast["issued"] if forecast else "—")
        .replace("{{FORECAST_VALID}}", forecast["valid"] if forecast else "—")
        .replace("{{FORECAST_STATUS}}", forecast["status_label"] if forecast else "—")
        .replace("{{FORECAST_PERIODS}}", forecast_cards(forecast["periods"]) if forecast else "")
        .replace("{{HISTORY_DAILY}}", daily)
        .replace("{{HISTORY_HOURLY}}", hourly)
        .replace("{{ROWS}}", rows)
    )


def make_handler(engine):
    class PublicPageHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/public_page.js":
                self.send_body(SCRIPT.read_bytes(), "text/javascript; charset=utf-8")
                return
            if path == "/maps/history":
                self.serve_history_map()
                return
            if path not in ("/", "/index.html", "/api/movements"):
                self.send_error(404)
                return
            try:
                now = datetime.now(timezone.utc)
                with Session(engine) as session:
                    counts, recent = movement_data(session, now)
                    map_run_id = latest_run_id(session)
                    wind = latest_wind(session)
                    taf = latest_taf(session, now)
                    history = history_data(session, now)
                if path == "/api/movements":
                    body = json.dumps(
                        snapshot(counts, recent, now, map_run_id, wind, taf, history),
                        ensure_ascii=False,
                    ).encode("utf-8")
                    content_type = "application/json; charset=utf-8"
                else:
                    body = render_page(counts, recent, now, wind, taf, history).encode("utf-8")
                    content_type = "text/html; charset=utf-8"
            except Exception:
                self.log_error("Could not read flight movement data")
                self.send_error(503, "Movement data is temporarily unavailable")
                return
            self.send_body(body, content_type)

        def serve_history_map(self) -> None:
            api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
            if not api_key:
                self.send_map_unavailable("Google Maps is nog niet geconfigureerd.")
                return
            try:
                with Session(engine) as session:
                    data = load_recent_runs(session)
                nonce = secrets.token_urlsafe(24)
                body = render_html(
                    data, api_key, template_path=HISTORY_TEMPLATE, nonce=nonce
                ).encode("utf-8")
            except ValueError:
                self.send_map_unavailable("Nog geen meetrondes beschikbaar voor de kaart.")
                return
            except Exception:
                self.log_error("Could not render history map")
                self.send_map_unavailable("De kaart is tijdelijk niet beschikbaar.")
                return
            self.send_body(body, "text/html; charset=utf-8", csp=map_csp(nonce))

        def send_map_unavailable(self, message: str) -> None:
            body = (
                '<!doctype html><html lang="nl"><meta charset="utf-8">'
                '<title>Kaart niet beschikbaar</title>'
                '<style>body{font:16px Arial,sans-serif;color:#173044;background:#eef3f7;'
                'margin:0;padding:32px}</style>'
                f"<p>{escape(message)}</p></html>"
            ).encode()
            self.send_body(body, "text/html; charset=utf-8", status=503, csp=MAP_FALLBACK_CSP)

        def send_body(
            self, body: bytes, content_type: str, *, status: int = 200, csp: str = PAGE_CSP
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", csp)
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.end_headers()
            self.wfile.write(body)

    return PublicPageHandler


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    engine = make_engine()
    with ThreadingHTTPServer((args.host, args.port), make_handler(engine)) as server:
        print(f"Serving Vogelvrij at http://{args.host}:{args.port}/")
        server.serve_forever()


if __name__ == "__main__":
    main()
