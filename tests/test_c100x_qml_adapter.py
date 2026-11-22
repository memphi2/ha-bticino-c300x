"""Focused page conversion and isolated Qt5 checks, not device acceptance."""

import importlib.util
import os
import subprocess
import sys
import shutil
import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("c100x_qml_builder", ROOT / "scripts/c100x_qml_builder.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_parity_inventory_is_complete_and_sources_are_separate(tmp_path):
    source = ROOT / "device_qml"
    before = {path: path.read_bytes() for path in source.glob("*.qml")}
    builder.build(tmp_path)
    excluded_core = {"C300XRingerControl.qml"}
    assert set(builder.PAGES) | excluded_core == {path.name for path in before}
    for name in builder.PAGES:
        generated = (tmp_path / name).read_text()
        assert "import QtQuick 2.7" in generated
        assert "import Components" not in generated
        assert "import QtQuick 1." not in generated
        assert "tabView" not in generated
    assert all(path.read_bytes() == content for path, content in before.items())
    for path in (source / "js").glob("*.js"):
        assert (tmp_path / "js" / path.name).read_bytes() == path.read_bytes()


def test_physical_keys_leave_vendor_actions_untouched():
    page = (ROOT / "device_qml/c100x/C100XPage.qml").read_text()
    for key in ("Key_Up", "Key_Down", "Key_Return", "Key_Back", "Key_Escape"):
        assert key in page
    for key in ("Key_Call", "Key_Hangup", "Key_1", "Key_6", "Key_7"):
        assert key not in page
    assert "event.accepted = false" in page
    assert "if (c100xHost.blocked) return" in page


def test_ringer_protocol_cancels_preemption_and_reports_actual_state():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the isolated protocol regression")
    subprocess.run([node, str(ROOT / "tests/fixtures/c100x_ringer_probe.js"),
                    str(ROOT / "device_qml/c100x/js/c100x_ringer.js")], check=True, timeout=10)


def test_bridge_contract_matches_original_vendor_sources():
    from test_native_routing_firmware_restore import FIRMWARE_ROOT, original
    original("c100x-1.5.8")
    source = FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino/bin/gui/skins/default"
    event = (source / "EventManager.qml").read_bytes()
    assert hashlib.sha256(event).hexdigest() == "3ca4b5e8c27c8c8b283d533106091072e25632bb090d414ee4c1d93f3a06b181"
    for name in (b"property bool callInProgress:", b"property bool callActive:"):
        assert name in event
    ringtone = (source / "Components/RingtoneItem.qml").read_text()
    for expression in ("global.audioState.isRingtoneMute", "enableState(AudioState.RingtoneMute)",
                       "disableState(AudioState.RingtoneMute)"):
        assert expression in ringtone
    assert 'prop: "beepEnabled"' in (source / "InstallerPage.qml").read_text()
    assert "Commissioning.Commissioned" in (source / "main.qml").read_text()


def test_pages_load_in_isolated_qt5(tmp_path):
    if importlib.util.find_spec("PyQt5") is None:
        pytest.skip("Optional host PyQt5 absent; this is not a firmware-runtime test")
    from test_native_routing_firmware_restore import FIRMWARE_ROOT, original
    original("c100x-1.5.8")
    source = tmp_path / "c100x"
    builder.build(source)
    (tmp_path / "images").mkdir()
    shutil.copy2(FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino/bin/gui/skins/default/images/key.svg",
                 tmp_path / "images/key.svg")
    result = subprocess.run([
        sys.executable, str(ROOT / "tests/fixtures/c100x_qml_probe.py"), str(source),
        *builder.PAGES,
    ], env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
            "C100X_STOCK_MAIN": str(FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino/bin/gui/skins/default/main.qml")},
       capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_page_layouts_and_hardware_key_focus_in_qt5(tmp_path):
    if importlib.util.find_spec("PyQt5") is None:
        pytest.skip("Optional host PyQt5 absent")
    source = tmp_path / "c100x"
    builder.build(source)
    result = subprocess.run([
        sys.executable, str(ROOT / "tests/fixtures/c100x_visual_probe.py"), str(source), str(tmp_path / "screenshots"),
    ], env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
       capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
