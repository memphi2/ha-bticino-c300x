"""Run production HA behavior separately from the fast module-stub tests."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("scenario", ["lifecycle", "soak"])
def test_real_home_assistant_runtime(scenario):
    result = subprocess.run(
        [sys.executable, "tests/runtime_lab/run.py", "--scenario", scenario],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
