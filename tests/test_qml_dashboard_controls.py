"""Run the real QML page methods and display API through asynchronous races."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("script", ["dashboard_controls.cjs", "display_runtime.cjs"])
def test_dashboard_production_controls(script: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(root / "tests/qml" / script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
