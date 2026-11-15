"""Exercise authored alert logic without claiming Qt/firmware hardware proof."""

import importlib.util
import os
import subprocess
import sys
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


@pytest.mark.parametrize("mode,fault,error", [
    ("transport", "none", None),
    ("touch", "none", None),
    ("touch", "missing_observer", "user-owned Normal must survive alert expiry"),
    ("touch", "consumed_press", "outside press must pass through"),
])
def test_alert_engine_regression(mode: str, fault: str, error: str | None) -> None:
    interpreter = os.environ.get("C300X_QML_PYTHON")
    if not interpreter:
        if importlib.util.find_spec("PySide6") is None:
            pytest.skip("Optional PySide6 absent; set C300X_QML_PYTHON")
        interpreter = sys.executable
    script = Path(__file__).resolve().parent / "qml/alerts_engine.py"
    result = subprocess.run([interpreter, str(script), mode, fault],
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == (0 if error is None else 1), result.stdout + result.stderr
    if error is not None:
        assert error in result.stderr
