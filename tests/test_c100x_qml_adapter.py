"""Focused page conversion and isolated Qt5 checks, not device acceptance."""

import hashlib
import importlib.util
import json
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


# Spanish on the C100X. The adapter's own text table (c100x_text.js) takes the
# language the bridge reads from Qt.locale(); the converted pages use the
# shared c300x_i18n.js with the same value.
C100X_STATUS_LABELS = {
    "en": "Status messages", "de": "Statusmeldungen", "it": "Messaggi di stato",
    "fr": "Messages d'état", "es": "Mensajes de estado",
}


def test_the_c100x_text_table_speaks_spanish_for_every_spanish_locale_name():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node evaluates the device script")
    names = ["es", "es_ES", "es-MX", "ES_es", "de_DE", "it_IT", "fr_FR", "en_US", "C", "", "pt_BR"]
    script = (
        "const fs = require('fs');\n"
        "const source = fs.readFileSync(process.argv[1], 'utf8').replace('.pragma library', '');\n"
        "const label = new Function(source + '\\nreturn label')();\n"
        f"const names = {json.dumps(names)};\n"
        "console.log(JSON.stringify(names.map(name => [label(name, 'status'), label(name, 'unknown_key')])));\n"
    )
    result = subprocess.run([node, "-e", script, str(ROOT / "device_qml/c100x/js/c100x_text.js")],
                            capture_output=True, text=True, check=True, timeout=10)
    labels = dict(zip(names, (tuple(pair) for pair in json.loads(result.stdout)), strict=True))
    for name in ("es", "es_ES", "es-MX", "ES_es"):
        assert labels[name] == (C100X_STATUS_LABELS["es"], "unknown_key"), name
    for name, code in (("de_DE", "de"), ("it_IT", "it"), ("fr_FR", "fr"), ("en_US", "en")):
        assert labels[name][0] == C100X_STATUS_LABELS[code], name
    # The C locale (no LANG) and unknown languages read English.
    for name in ("C", "", "pt_BR"):
        assert labels[name][0] == C100X_STATUS_LABELS["en"], name


@pytest.mark.parametrize("lang,expected", [
    ("es_ES.UTF-8", "es"), ("de_DE.UTF-8", "de"), ("it_IT.UTF-8", "it"), ("fr_FR.UTF-8", "fr"),
    ("en_GB.UTF-8", "en"), (None, "en"),
])
def test_the_bridge_takes_the_display_language_from_the_qt_locale(tmp_path, lang, expected):
    """Qt.locale() follows LANG; the 1.5.8 display starts without one (None: the C locale)."""
    if importlib.util.find_spec("PyQt5") is None:
        pytest.skip("Optional host PyQt5 absent")
    source = tmp_path / "c100x"
    builder.build(source)
    (source / "LanguageProbe.qml").write_text(
        'import QtQuick 2.7\nimport "js/c100x_text.js" as Labels\nimport "js/c300x_i18n.js" as I18n\n'
        "Item {\n    property alias c100xHost: bridge\n    C100XBridge { id: bridge }\n"
        '    readonly property string label: Labels.label(bridge.language, "status")\n'
        "    readonly property string shared: I18n.language(bridge.language)\n}\n")
    code = '''import json, sys
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtQml import QQmlComponent, QQmlEngine
app = QGuiApplication([])
engine = QQmlEngine()
component = QQmlComponent(engine, QUrl.fromLocalFile(sys.argv[1]))
item = component.create()
assert item is not None, [error.toString() for error in component.errors()]
bridge = item.property("c100xHost")
print(json.dumps([bridge.property("language"), item.property("label"), item.property("shared")]))
'''
    env = {key: value for key, value in os.environ.items() if not key.startswith(("LANG", "LC_"))}
    if lang:
        env["LANG"] = lang
    result = subprocess.run([sys.executable, "-c", code, str(source / "LanguageProbe.qml")],
                            env={**env, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    name, label, shared = json.loads(result.stdout.strip().splitlines()[-1])
    assert name == (lang.split(".")[0] if lang else "C")
    assert (label, shared) == (C100X_STATUS_LABELS[expected], expected)
