"""Run production HA behavior separately from the fast module-stub tests."""

import subprocess
import sys
from pathlib import Path


def test_real_home_assistant_lifecycle():
    result = subprocess.run(
        [sys.executable, "tests/runtime_lab/run.py"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
