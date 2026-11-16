"""Execute production departure confirmation functions without a device."""

import subprocess
from pathlib import Path


def test_leave_home_confirmation():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["node", str(root / "tests/qml/leave_home.cjs")], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
