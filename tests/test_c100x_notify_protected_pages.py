"""Notify uses the vendor page guard, independently of the core bridge."""

import importlib.util
import os
import shutil
import subprocess
import sys

import pytest
from test_c100x_qml_adapter import ROOT, builder
from test_native_routing_firmware_restore import FIRMWARE_ROOT, original


def test_notify_protected_pages_with_actual_hook_and_bridge(tmp_path):
    if importlib.util.find_spec("PyQt5") is None:
        pytest.skip("Optional host PyQt5 absent; not a hardware acceptance test")
    source = tmp_path / "source"
    builder.build(source)
    original("c100x-1.5.8")
    (tmp_path / "images").mkdir()
    shutil.copy2(FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino/bin/gui/skins/default/images/key.svg",
                 tmp_path / "images/key.svg")
    result = subprocess.run(
        [sys.executable, str(ROOT / "tests/fixtures/c100x_protected_pages_probe.py"), str(source)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
