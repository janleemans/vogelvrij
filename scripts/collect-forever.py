#!/usr/bin/env python3
"""Run the three one-shot collectors continuously under a process supervisor."""

from __future__ import annotations

import argparse
import math
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Job:
    name: str
    command: list[str]
    interval: float
    next_due: float


def positive_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("interval must be a positive number of seconds") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("interval must be a positive finite number of seconds")
    return seconds


def command_path(name: str, project_dir: Path) -> str:
    local = project_dir / ".venv" / "bin" / name
    if local.is_file():
        return str(local)
    found = shutil.which(name)
    if found is None:
        raise FileNotFoundError(f"{name} not found; install the project in .venv or on PATH")
    return found


def next_slot(previous_due: float, interval: float, now: float) -> float:
    """Keep a steady cadence, skipping missed slots instead of catching up in a burst."""
    return previous_due + interval * max(1, math.floor((now - previous_due) / interval) + 1)


def run_job(job: Job, stop: threading.Event) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{stamp} starting {job.name}", flush=True)
    try:
        child = subprocess.Popen(job.command)
    except OSError as exc:
        print(f"{job.name} failed to start: {exc}", file=sys.stderr, flush=True)
        return

    while True:
        if stop.is_set():
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            return
        try:
            status = child.wait(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            continue
    if status:
        print(f"{job.name} failed with exit status {status}", file=sys.stderr, flush=True)
    else:
        print(f"{job.name} completed", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, default=50.900167)
    parser.add_argument("--lon", type=float, default=4.460000)
    parser.add_argument("--radius-nm", type=float, default=15)
    parser.add_argument("--flight-interval", type=positive_seconds, default=60,
                        help="seconds between flight collection starts (default: 60)")
    args = parser.parse_args()
    if not math.isfinite(args.lat) or not -90 <= args.lat <= 90:
        parser.error("--lat must be between -90 and 90")
    if not math.isfinite(args.lon) or not -180 <= args.lon <= 180:
        parser.error("--lon must be between -180 and 180")
    if not math.isfinite(args.radius_nm) or not 0 < args.radius_nm <= 250:
        parser.error("--radius-nm must be greater than 0 and no more than 250")
    project_dir = Path(__file__).resolve().parents[1]
    try:
        flights = command_path("vogelvrij-collect", project_dir)
        metar = command_path("vogelvrij-collect-wind", project_dir)
        taf = command_path("vogelvrij-collect-taf", project_dir)
    except FileNotFoundError as exc:
        parser.error(str(exc))

    now = time.monotonic()
    jobs = [
        Job("flights", [flights, "--lat", str(args.lat), "--lon", str(args.lon),
                        "--radius-nm", str(args.radius_nm)], args.flight_interval, now),
        Job("METAR", [metar], 3600, now),
        Job("TAF", [taf], 3600, now),
    ]
    stop = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stop.is_set():
        due = min(jobs, key=lambda job: job.next_due)
        if stop.wait(max(0, due.next_due - time.monotonic())):
            break
        run_job(due, stop)
        due.next_due = next_slot(due.next_due, due.interval, time.monotonic())
    return 0


if __name__ == "__main__":
    sys.exit(main())
