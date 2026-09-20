import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "collect-repeatedly.sh"


def _stub_commands(tmp_path):
    log = tmp_path / "calls.log"
    collector = tmp_path / "vogelvrij-collect"
    collector.write_text(
        '#!/bin/sh\nprintf "collect:%s\\n" "$*" >> "$VOGELVRIJ_TEST_LOG"\n',
        encoding="utf-8",
    )
    collector.chmod(0o755)
    sleeper = tmp_path / "sleep"
    sleeper.write_text(
        '#!/bin/sh\nprintf "sleep:%s\\n" "$1" >> "$VOGELVRIJ_TEST_LOG"\n',
        encoding="utf-8",
    )
    sleeper.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env["PATH"]
    env["VOGELVRIJ_TEST_LOG"] = str(log)
    return log, env


def test_runs_requested_count_and_sleeps_only_between_calls(tmp_path):
    log, env = _stub_commands(tmp_path)

    completed = subprocess.run(
        ["sh", str(SCRIPT), "0.25", "3", "--lat", "50.85", "--radius-nm", "25"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert log.read_text(encoding="utf-8").splitlines() == [
        "collect:--lat 50.85 --radius-nm 25",
        "sleep:0.25",
        "collect:--lat 50.85 --radius-nm 25",
        "sleep:0.25",
        "collect:--lat 50.85 --radius-nm 25",
    ]


@pytest.mark.parametrize(
    ("interval", "runs"),
    [("0", "3"), ("-1", "3"), ("abc", "3"), ("1", "0"), ("1", "2.5")],
)
def test_invalid_arguments_do_not_call_collector(tmp_path, interval, runs):
    log, env = _stub_commands(tmp_path)

    completed = subprocess.run(
        ["sh", str(SCRIPT), interval, runs],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "Usage:" in completed.stderr
    assert not log.exists()
