"use strict";

const REFRESH_INTERVAL_MS = 30_000;
const countIds = { "07LR": "count-07lr", "25LR": "count-25lr", "01": "count-01", "19": "count-19" };
let refreshInProgress = false;
const mapFrame = document.getElementById("history-map");
const mapLoadedAt = document.getElementById("map-loaded-at");
const mapRefreshButton = document.getElementById("map-refresh-button");
const mapTimeFormatter = new Intl.DateTimeFormat("nl-BE", {
  timeZone: "Europe/Brussels", day: "2-digit", month: "2-digit", year: "numeric",
  hour: "2-digit", minute: "2-digit", second: "2-digit",
});

function markMapLoaded() {
  if (!mapFrame.contentDocument || mapFrame.contentDocument.URL === "about:blank") return;
  const loadedAt = new Date();
  mapLoadedAt.dateTime = loadedAt.toISOString();
  mapLoadedAt.textContent = mapTimeFormatter.format(loadedAt);
  mapRefreshButton.disabled = false;
  mapRefreshButton.textContent = "Kaart vernieuwen";
}

mapFrame.addEventListener("load", markMapLoaded);
if (mapFrame.contentDocument?.readyState === "complete" &&
    mapFrame.contentDocument.URL !== "about:blank") markMapLoaded();

mapRefreshButton.addEventListener("click", () => {
  mapRefreshButton.disabled = true;
  mapRefreshButton.textContent = "Kaart wordt vernieuwd…";
  mapFrame.src = `/maps/history?refresh=${Date.now()}`;
});

function updateRows(rows) {
  const body = document.getElementById("movement-rows");
  const fragment = document.createDocumentFragment();

  if (rows.length === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "empty";
    cell.textContent = "Nog geen bewegingen geregistreerd.";
    row.append(cell);
    fragment.append(row);
  } else {
    for (const values of rows) {
      const row = document.createElement("tr");
      for (const [index, value] of values.entries()) {
        const cell = document.createElement("td");
        cell.textContent = value;
        if (index === 2 && value !== "—" && values[1] !== "—") {
          const matches = value === values[1];
          cell.className = matches ? "theoretical-runway-match" : "theoretical-runway-mismatch";
          cell.title = matches ? "Komt overeen met de gedetecteerde baan" :
            "Wijkt af van de gedetecteerde baan";
        }
        row.append(cell);
      }
      fragment.append(row);
    }
  }
  body.replaceChildren(fragment);
}

function updateWind(wind) {
  const content = document.getElementById("wind-content");
  const empty = document.getElementById("wind-empty");
  for (const corridor of Object.keys(countIds)) {
    const component = wind && wind.components ? wind.components[corridor] : null;
    const id = corridor.toLowerCase();
    document.getElementById(`wind-components-${id}`).textContent =
      component || "Windcomponenten niet beschikbaar.";
    const light = document.getElementById(`wind-light-${id}`);
    const reportedStatus = wind && wind.lights ? wind.lights[corridor] : null;
    const status = reportedStatus === "red" || reportedStatus === "green" ? reportedStatus : "unknown";
    light.className = `wind-light wind-light-${status}`;
    light.setAttribute("aria-label", wind && wind.light_labels && wind.light_labels[corridor]
      ? wind.light_labels[corridor] : "Geen windmeting beschikbaar");
  }
  content.hidden = wind == null;
  empty.hidden = wind != null;
  document.getElementById("wind-approach-content").hidden = wind == null;
  if (wind == null) return;
  document.getElementById("wind-direction").textContent = wind.direction;
  document.getElementById("wind-speed").textContent = wind.speed;
  document.getElementById("wind-observed").textContent = wind.observed;
  document.getElementById("wind-approach").textContent = wind.approach;
  document.getElementById("wind-arrow").setAttribute("transform", `rotate(${wind.bearing} 50 50)`);
}

function updateForecast(forecast) {
  const section = document.getElementById("forecast-section");
  const hasForecast = forecast && Array.isArray(forecast.periods) && forecast.periods.length > 0;
  document.getElementById("forecast-meta").hidden = !hasForecast;
  document.getElementById("forecast-periods").hidden = !hasForecast;
  document.getElementById("forecast-empty").hidden = !!hasForecast;
  if (!hasForecast) {
    section.dataset.forecastId = "";
    document.getElementById("forecast-periods").replaceChildren();
    return;
  }
  document.getElementById("forecast-status").textContent = forecast.status_label;
  document.getElementById("forecast-issued").textContent = forecast.issued;
  document.getElementById("forecast-valid").textContent = forecast.valid;
  if (section.dataset.forecastId === String(forecast.id)) return;
  section.dataset.forecastId = String(forecast.id);
  const fragment = document.createDocumentFragment();
  for (const period of forecast.periods) {
    const card = document.createElement("article");
    const kind = ["prevailing", "transition", "temporary"].includes(period.kind) ? period.kind : "prevailing";
    card.className = `forecast-period forecast-${kind}`;
    const label = document.createElement("span");
    label.className = "forecast-period-label";
    label.textContent = period.label;
    const time = document.createElement("span");
    time.className = "forecast-time";
    time.textContent = `${period.from} – ${period.to}`;
    const wind = document.createElement("span");
    wind.className = "forecast-wind";
    const arrow = document.createElement("span");
    arrow.className = "forecast-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.style.transform = `rotate(${Number(period.bearing) || 0}deg)`;
    arrow.textContent = "↑";
    const details = document.createElement("span");
    const direction = document.createElement("strong");
    direction.textContent = `Wind uit ${period.direction}`;
    const speed = document.createElement("small");
    speed.textContent = period.speed;
    details.append(direction, speed);
    wind.append(arrow, details);
    const approach = document.createElement("span");
    approach.className = "forecast-approach";
    const approachLabel = document.createElement("small");
    approachLabel.textContent = period.approach_label;
    const approachValue = document.createElement("strong");
    approachValue.textContent = period.approach;
    approach.append(approachLabel, approachValue);
    card.append(label, time, wind, approach);
    fragment.append(card);
  }
  document.getElementById("forecast-periods").replaceChildren(fragment);
}

function historySegments(counts, scale, vertical) {
  const fragment = document.createDocumentFragment();
  for (const corridor of Object.keys(countIds)) {
    const count = Number(counts[corridor]) || 0;
    if (count <= 0) continue;
    const segment = document.createElement("span");
    segment.className = `history-segment corridor-${corridor.toLowerCase()}`;
    segment.style[vertical ? "height" : "width"] = `${count / scale * 100}%`;
    fragment.append(segment);
  }
  return fragment;
}

function updateHistory(history) {
  if (!history || !Array.isArray(history.days) || !Array.isArray(history.hours)) return;
  const daily = document.createDocumentFragment();
  const dayScale = Math.max(1, ...history.days.map(day => day.total));
  for (const day of history.days) {
    const row = document.createElement("div");
    row.className = "daily-row";
    const date = document.createElement("time");
    date.dateTime = day.date;
    date.textContent = day.label;
    const bar = document.createElement("span");
    bar.className = "daily-bar";
    bar.setAttribute("aria-hidden", "true");
    bar.append(historySegments(day.counts, dayScale, false));
    const total = document.createElement("strong");
    total.textContent = day.total;
    const detail = document.createElement("span");
    detail.className = "daily-detail";
    detail.textContent = Object.keys(countIds).map(corridor =>
      `${corridor}: ${day.counts[corridor]}`).join(" · ") + ` · meetrondes: ${day.runs}`;
    row.append(date, bar, total, detail);
    daily.append(row);
  }
  document.getElementById("history-daily").replaceChildren(daily);

  const hourly = document.createDocumentFragment();
  const hourScale = Math.max(1, ...history.hours.map(hour => hour.total));
  for (const hour of history.hours) {
    const column = document.createElement("div");
    column.className = "hour-column";
    column.setAttribute("role", "img");
    const label = `${hour.label}: ${hour.total} detecties, ${hour.runs} meetrondes; ` +
      Object.keys(countIds).map(corridor => `${corridor} ${hour.counts[corridor]}`).join(", ");
    column.setAttribute("aria-label", label);
    column.title = label;
    const tick = document.createElement("span");
    tick.className = "hour-label";
    tick.append(document.createTextNode(hour.label.slice(0, 5)), document.createElement("br"),
      document.createTextNode(hour.label.slice(6, 11)));
    const bar = document.createElement("span");
    bar.className = "hour-bar";
    bar.setAttribute("aria-hidden", "true");
    bar.append(historySegments(hour.counts, hourScale, true));
    const total = document.createElement("span");
    total.className = "hour-total";
    total.setAttribute("aria-hidden", "true");
    total.textContent = hour.total;
    column.append(bar, total, tick);
    hourly.append(column);
  }
  document.getElementById("history-hourly").replaceChildren(hourly);
}

async function refreshMovements() {
  if (refreshInProgress || document.hidden) return;
  refreshInProgress = true;
  const status = document.getElementById("refresh-status");

  try {
    const response = await fetch("/api/movements", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    for (const [corridor, id] of Object.entries(countIds)) {
      document.getElementById(id).textContent = data.counts[corridor];
    }
    document.getElementById("stats-date").textContent = data.date;
    document.getElementById("stats-updated").textContent = data.updated;
    updateRows(data.rows);
    updateWind(data.wind);
    updateForecast(data.forecast);
    updateHistory(data.history);
    status.hidden = true;
    status.textContent = "";
  } catch (error) {
    status.textContent = "Bijwerken mislukt. De laatst beschikbare gegevens blijven zichtbaar; we proberen het opnieuw.";
    status.hidden = false;
  } finally {
    refreshInProgress = false;
  }
}

window.setInterval(refreshMovements, REFRESH_INTERVAL_MS);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshMovements();
});
