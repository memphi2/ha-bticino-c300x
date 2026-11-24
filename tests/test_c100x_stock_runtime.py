"""The adapter inside the original C100X main.qml on host Qt 5, driven by keys.

Optional: needs host PyQt5 and the private extracted firmware (never in the
repository). The agent is an in-memory reply table and every request URL is
recorded, so a request that could not reach the agent fails the scenario.
Host Qt 5.15 with vendor stand-ins is not the firmware runtime or a device.
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_scenario(name, tmp_path, firmware=True):
    if importlib.util.find_spec("PyQt5") is None:
        pytest.skip("Optional host PyQt5 absent; not a firmware-runtime test")
    from test_native_routing_firmware_restore import FIRMWARE_ROOT, original
    if firmware:
        original("c100x-1.5.8")
    skin = FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino/bin/gui/skins/default"
    result = subprocess.run(
        [sys.executable, str(ROOT / "tests/fixtures/c100x_stock_scenarios.py"), name, str(tmp_path), str(skin)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
             "QML_DISABLE_DISK_CACHE": "1", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"},
        capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr


def test_bridge_declares_the_agent_ui_listener():
    bridge = (ROOT / "device_qml/c100x/C100XBridge.qml").read_text()
    assert '    readonly property string uiBaseUrl: "http://127.0.0.1:8090"\n' in bridge
    # The agent refuses to activate the adapter on any other UI port.
    api = (ROOT / "native_agent/src/http_c100x_display_api.c").read_text()
    assert 'config->ui_port != 8090' in api and '"c100x_display_ui_port_unsupported"' in api


def test_bridge_requests_reach_the_agent_listener(tmp_path):
    run_scenario("bridge_urls", tmp_path)
