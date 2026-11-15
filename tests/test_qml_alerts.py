"""Exercise authored alert logic without claiming Qt/firmware hardware proof."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("script", ["alerts.cjs", "alerts_qml.cjs"])
def test_native_alert_logic(script: str) -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", str(root / "tests/qml" / script)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
