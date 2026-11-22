"""C100X-specific Notify adapter checks, not a hardware activation claim."""

import importlib.util
import os
import subprocess
import sys

import pytest
from test_c100x_qml_adapter import ROOT, builder, strip_device_source
from test_native_routing_firmware_restore import FIRMWARE_ROOT, original


def test_alert_adapter_uses_verified_stock_screen_api_and_no_guessed_sound(tmp_path):
    original("c100x-1.5.8")
    firmware = FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino"
    lib = (firmware / "lib/BtObjects/libbtobjects.so").read_bytes()
    for name in (b"simulateClick", b"screensaverInterval", b"stateChangedInt", b"disableState"):
        assert name in lib
    stock = (firmware / "bin/gui/skins/default/SoftApPage.qml").read_text()
    assert "global.screenState.disableState(ScreenState.Normal)" in stock
    builder.build(tmp_path)
    page = (tmp_path / "C300XAlerts.qml").read_text()
    for forbidden in ("global.beep", "startBeep", "AudioState", "audioAccess", "Microsemi", "import Bt"):
        assert forbidden not in page
    assert "command.sound_duration === 0" in page
    assert "root.vendorScreen.simulateClick()" in page
    assert "root.vendorScreen.disableState(c100xHost.normalState)" in page
    assert (tmp_path / "js/c300x_alerts.js").read_text() == strip_device_source(
        (ROOT / "device_qml/js/c300x_alerts.js").read_text())


def test_alert_wake_focus_ack_and_call_preemption_in_host_qt5(tmp_path):
    if importlib.util.find_spec("PyQt5") is None:
        pytest.skip("Optional host PyQt5 absent; use explicit offline runtime PYTHONPATH")
    source = tmp_path / "source"
    builder.build(source)
    result = subprocess.run([
        sys.executable, str(ROOT / "tests/fixtures/c100x_alert_probe.py"), str(source), str(tmp_path / "screenshots"),
    ], env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
       capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_alert_builder_rejects_changed_shared_safety_contract():
    source = (ROOT / "device_qml/C300XAlerts.qml").read_text()
    for anchor in ("property bool blocked: true", "if (stopped || Alerts.runtimeFor(root)) return",
                   "valid = !!Alerts.validate(command, new Date().getTime())"):
        with pytest.raises(ValueError, match="Shared alert contract changed"):
            builder.adapt_alerts(source.replace(anchor, "changed"))
