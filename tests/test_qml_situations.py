"""Run source/runtime contracts without a Qt6 or device dependency."""

import subprocess
from pathlib import Path


def test_situations_are_passive_and_reset_when_navigating():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["node", str(root / "tests/qml/situations.cjs")], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
