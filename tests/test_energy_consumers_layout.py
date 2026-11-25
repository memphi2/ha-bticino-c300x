"""Consumers replace the old flow chart with independently scaled live watts."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from test_display_layout_harness import SCRIPT, qt_python

from scripts.setup_qt4_runtime import probe_command, runtime_paths

ROOT = SCRIPT.parents[1]
QML = ROOT / "device_qml/C300XEnergyConsumers.qml"


def test_consumers_js_contract_extremes_and_hysteresis():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for pure production JS checks")
    result = subprocess.run([node, str(ROOT / "tests/qml/energy_consumers.cjs")],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_consumers_qt4_runtime_labels():
    paths = runtime_paths()
    if paths is None:
        pytest.skip("Optional Qt 4 ARM runtime: run scripts/setup_qt4_runtime.py --sysroot PRIVATE_ROOTFS")
    result = subprocess.run(probe_command(paths, ROOT / "tests/qml/energy_consumers_qt4.qml"),
                            env={**os.environ, "PROBE_CREATE": "1"}, capture_output=True, text=True, timeout=30)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "C300X_CONSUMERS_QT4_PASS 214" in output, output


def test_consumers_is_lazy_qtquick1_without_idle_polling():
    source = QML.read_text()
    parent = (QML.parent / "C300XEnergy.qml").read_text()
    assert source.startswith("import QtQuick 1.1\n")
    assert len(source.splitlines()) < 200
    assert source.count("Timer {") == 1
    assert "repeat: false" in source
    # Loaded on the first visible use and kept while the tab is selected: the
    # page hides its content under its own lists, and a reload there would
    # build the view again and drop the held scales.
    assert 'source: root.consumersKept ? "C300XEnergyConsumers.qml" : ""' in parent
    assert 'consumersKept = shown === "consumers" && (visible || consumersKept)' in parent
    assert "root.visible &&" not in parent
    assert "property variant rows: Consumers.rows(current)" in source
    assert "if (!visible || !stale) return" in source
    assert 'property: "consumers"' in parent
    assert 'color: Consumers.finite(row.consumer.watts) ? "white" : "#c7d0d9"' in source
    assert 'visible: Consumers.finite(row.consumer.watts) && row.consumer.watts > 0' in source
    for token in ("Canvas", "QtQuick 2", "XMLHttpRequest", "kWh", 'text: "log"'):
        assert token not in source


def test_consumers_qt4_runtime_holds_a_refresh_under_an_overlay():
    """On the station's Qt 4.8: a hidden view keeps its rows and takes the newest data when shown."""
    import re
    import tempfile

    paths = runtime_paths()
    if paths is None:
        pytest.skip("Optional Qt 4 ARM runtime: run scripts/setup_qt4_runtime.py --sysroot PRIVATE_ROOTFS")
    # The emulator resolves no imports below /tmp, and Text needs a GUI the probe
    # does not open: the station's text type is replaced by a plain item.
    work = tempfile.mkdtemp(prefix="c300x-qt4-overlay-", dir="/var/tmp")
    try:
        work_path = Path(work)
        (work_path / "js").mkdir()
        (work_path / "imports/Components/Styles").mkdir(parents=True)
        (work_path / "imports/Components/qmldir").write_text("UbuntuLightText 1.0 UbuntuLightText.qml\n")
        (work_path / "imports/Components/UbuntuLightText.qml").write_text(
            "import QtQuick 1.1\nItem {\n" + "".join(
                f"    property {kind} {name}\n" for kind, name in (
                    ("string", "text"), ("int", "textFormat"), ("color", "color"), ("int", "horizontalAlignment"),
                    ("int", "verticalAlignment"), ("int", "elide"), ("int", "wrapMode"))) + "}\n")
        (work_path / "imports/Components/Styles/qmldir").write_text("Stub 1.0 Stub.qml\n")
        (work_path / "imports/Components/Styles/Stub.qml").write_text("import QtQuick 1.1\nQtObject { }\n")
        source = QML.read_text()
        (work_path / QML.name).write_text(re.sub(r"font\.[a-zA-Z]+: [^;\n]*(; |(?=\n))", "", source))
        shutil.copyfile(QML.parent / "js/c300x_energy_consumers.js", work_path / "js/c300x_energy_consumers.js")
        shutil.copyfile(ROOT / "tests/qml/energy_overlay_qt4.qml", work_path / "probe.qml")
        command = probe_command(paths, work_path / "probe.qml")
        command[-1] = str(work_path / "imports")
        result = subprocess.run(command, env={**os.environ, "PROBE_CREATE": "1"},
                                capture_output=True, text=True, timeout=60)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-600:]
    assert "C300X_OVERLAY_QT4_PASS 8" in output, output[-600:]


def test_consumers_current_geometry_pixels_scales_and_overlay(tmp_path):
    result = subprocess.run([qt_python(), str(SCRIPT), "--components", "C300XEnergy", "--check",
                             "--output", str(tmp_path)], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    assert len(report["cases"]) == 24
    assert not report["diagnostics"]
    assert str(QML) in report["production_files"]
    assert str(QML.parent / "js/c300x_energy_consumers.js") in report["production_files"]
    assert report["passed"]
    for case in report["cases"]:
        assert not case["issues"]
        checks = {check["name"]: check for check in case["checks"]}
        assert checks["no idle timer"]["passed"]
        assert checks["consumers unload on tab switch"]["passed"]
        for name in ("consumers stay loaded under an overlay", "refresh under an overlay is held back",
                     "no timer under an overlay", "same consumers view after the overlay",
                     "newest data after the overlay", "newest rows after the overlay"):
            assert checks[name]["passed"]
        assert ("scale survives the overlay" in checks) == (case["fixture"] == "consumers-normal")
        for shot in case["snapshots"]:
            for text in shot["texts"]:
                if text["text"].endswith(" W"):
                    assert len(text["text"]) <= 25
        assert not any(text["text"] == "log" for shot in case["snapshots"] for text in shot["texts"])


def test_consumers_probe_detects_invisible_positive_bars(tmp_path):
    (tmp_path / "C300XEnergy.qml").write_text((QML.parent / "C300XEnergy.qml").read_text())
    source = QML.read_text().replace("width: row.fraction * row.width", "width: 0")
    (tmp_path / QML.name).write_text(source)
    result = subprocess.run([qt_python(), str(SCRIPT), "--components", "C300XEnergy",
                             "--qml-dir", str(tmp_path), "--scenarios", "consumers-long", "--viewports", "narrow",
                             "--output", str(tmp_path / "out"), "--check"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads((tmp_path / "out/report.json").read_text())
    assert any(issue.get("check", "").startswith("positive bar") for issue in report["cases"][0]["issues"])
