"""Focused page conversion and isolated Qt5 checks, not device acceptance."""

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from device_file_strip import strip_device_source  # noqa: E402

spec = importlib.util.spec_from_file_location("c100x_qml_builder", ROOT / "scripts/c100x_qml_builder.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_parity_inventory_is_complete_and_sources_are_separate(tmp_path):
    source = ROOT / "device_qml"
    before = {path: path.read_bytes() for path in source.glob("*.qml")}
    builder.build(tmp_path)
    # Hooks into C300X vendor files (EventManager, Settings tab), not pages.
    excluded_core = {"C300XRingerControl.qml", "C300XSettings.qml"}
    assert set(builder.PAGES) | excluded_core == {path.name for path in before}
    for name in builder.PAGES:
        generated = (tmp_path / name).read_text()
        assert "import QtQuick 2.7" in generated
        assert "import Components" not in generated
        assert "import QtQuick 1." not in generated
        assert "tabView" not in generated
    assert all(path.read_bytes() == content for path, content in before.items())
    for path in (source / "js").glob("*.js"):
        if path.name in builder.C300X_ONLY_SCRIPTS:
            assert not (tmp_path / "js" / path.name).exists()
        else:
            assert (tmp_path / "js" / path.name).read_text() == strip_device_source(path.read_text())


def test_c300x_popup_look_and_scroll_bars_are_not_taken_over(tmp_path):
    """The C300X popup is a touch window; the station's lists show arrows, not a bar."""
    builder.build(tmp_path / "c100x")
    notice = (tmp_path / "c100x/C300XAlerts.qml").read_text()
    for popup in ("opacity: 0.9", "opacity: 0.5", "Ubuntu", "Font.Light", "anchors.centerIn: parent"):
        assert popup not in notice, popup
    assert notice.count("visible: false") == 3
    for kept in ("anchors.fill: parent", '"../images/background.jpg"', 'objectName: "alertFocusBar"',
                 "height: 6; color: root.accent", "C100XScroll {"):
        assert kept in notice, kept
    for name in ("C300XAgenda.qml", "C300XLeaveHome.qml", "C300XSituations.qml"):
        page = (tmp_path / "c100x" / name).read_text()
        bar = page[page.index("anchors.right: parent.right\ny: list"):]
        assert bar[:bar.index("}")].count("visible: false") == 1, name
        assert "width: parent.width\nheight:" in page and "? 9 : 0" not in page, name
        assert "C100XList {" in page or "C100XScroll {" in page, name


def test_physical_keys_leave_vendor_actions_untouched():
    page = (ROOT / "device_qml/c100x/C100XPage.qml").read_text()
    for key in ("Key_Up", "Key_Down", "Key_Return"):
        assert key in page
    # The station's keymap has no back key: pages leave through their EXIT entry.
    for key in ("Key_Back", "Key_Escape", "Key_Call", "Key_Hangup", "Key_1", "Key_6", "Key_7"):
        assert key not in page
    assert '"../images/Exit.svg"' in page and "backClicked()" in page
    assert "event.accepted = false" in page
    assert "if (c100xHost.blocked) return" in page


def test_ringer_protocol_cancels_preemption_and_reports_actual_state():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the isolated protocol regression")
    subprocess.run([node, str(ROOT / "tests/fixtures/c100x_ringer_probe.js"),
                    str(ROOT / "device_qml/c100x/js/c100x_ringer.js")], check=True, timeout=10)


def test_mute_acks_the_flag_and_never_leaves_a_deferred_change():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the isolated mute regression")
    subprocess.run([node, str(ROOT / "tests/fixtures/c100x_mute_probe.js"),
                    str(ROOT / "device_qml/c100x/C100XBridge.qml")], check=True, timeout=10)


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


@pytest.mark.parametrize("damage", ["none", "missing", "syntax"])
def test_readiness_compiles_every_additional_page_and_rejects_broken_input(tmp_path, damage):
    if importlib.util.find_spec("PyQt5") is None:
        pytest.skip("Optional host PyQt5 absent")
    source = tmp_path / "c100x"
    builder.build(source)
    ready = (source / "C100XReady.qml").read_text()
    for page in set(builder.PAGES) - {"C300XAlerts.qml"}:
        assert f'"{page}"' in ready
    # An own entry, not merely a dependency of the HA dashboard.
    page = source / "C100XStatusItem.qml"
    if damage == "missing":
        page.unlink()
    elif damage == "syntax":
        page.write_text("import QtQuick 2.7\nItem { invalid syntax }\n")
    code = '''import sys
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtQml import QQmlComponent, QQmlEngine
app = QGuiApplication([])
engine = QQmlEngine()
component = QQmlComponent(engine, QUrl.fromLocalFile(sys.argv[1]))
item = component.create()
assert item is not None, component.errors()
assert item.property("ready") == (sys.argv[2] == "none")
'''
    result = subprocess.run([sys.executable, "-c", code, str(source / "C100XReady.qml"), damage],
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
                            capture_output=True, text=True, timeout=15)
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
