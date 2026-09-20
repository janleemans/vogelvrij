import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "collect-forever.py"
spec = importlib.util.spec_from_file_location("collect_forever", SCRIPT)
collector = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = collector
spec.loader.exec_module(collector)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "oops"])
def test_rejects_invalid_intervals(value):
    with pytest.raises(Exception, match="interval must be a positive"):
        collector.positive_seconds(value)


def test_schedule_skips_missed_slots_without_drifting():
    assert collector.next_slot(100, 60, 105) == 160
    assert collector.next_slot(100, 60, 160) == 220
    assert collector.next_slot(100, 3600, 7400) == 10900


@pytest.mark.parametrize("flag,value", [("--lat", "nan"), ("--lon", "181"),
                                         ("--radius-nm", "0"),
                                         ("--flight-interval", "inf")])
def test_invalid_configuration_exits_before_scheduling(flag, value):
    result = subprocess.run([sys.executable, str(SCRIPT), flag, value],
                            capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode == 2


def test_starts_all_three_with_requested_defaults_and_exits_on_term(tmp_path):
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    script = script_dir / SCRIPT.name
    script.write_bytes(SCRIPT.read_bytes())
    log = tmp_path / "calls.log"
    for name in ("vogelvrij-collect", "vogelvrij-collect-wind", "vogelvrij-collect-taf"):
        stub = tmp_path / name
        ending = 'kill -TERM "$PPID"\n' if name.endswith("-taf") else ""
        stub.write_text(
            f'#!/bin/sh\nprintf "%s:%s\\n" "{name}" "$*" >> "$VOGELVRIJ_TEST_LOG"\n'
            + ending,
            encoding="utf-8",
        )
        stub.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env["PATH"]
    env["VOGELVRIJ_TEST_LOG"] = str(log)

    result = subprocess.run([sys.executable, str(script)], env=env, capture_output=True,
                            text=True, timeout=5, check=False)

    assert result.returncode == 0
    assert log.read_text(encoding="utf-8").splitlines() == [
        "vogelvrij-collect:--lat 50.900167 --lon 4.46 --radius-nm 15",
        "vogelvrij-collect-wind:",
        "vogelvrij-collect-taf:",
    ]
