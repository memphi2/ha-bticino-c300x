"""Run production HA behavior separately from the fast module-stub tests."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("scenario", ["lifecycle", "soak", "recorder", "contract"])
def test_real_home_assistant_runtime(scenario):
    result = subprocess.run(
        [sys.executable, "tests/runtime_lab/run.py", "--scenario", scenario],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Detected code that" not in result.stderr, result.stderr
    assert "AttributeError:" not in result.stderr, result.stderr
    if scenario == "contract":
        result = subprocess.run(
            ["node", "tests/frontend/c300x_generated_contract.mjs"],
            input=result.stdout,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
