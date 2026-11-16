"""Consumers replace the old flow chart with independently scaled live watts."""

import json
import os
import shutil
import subprocess

import pytest
from test_display_layout_harness import SCRIPT, qt_python

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
    paths = [os.environ.get("C300X_QT4_" + key) for key in ("QEMU", "ROOTFS", "PROBE", "IMPORTS")]
    if not all(paths):
        pytest.skip("Optional offline Qt4 ARM runtime requires C300X_QT4_QEMU/ROOTFS/PROBE/IMPORTS")
    qemu, rootfs, probe, imports = paths
    result = subprocess.run([
        qemu, "-L", rootfs, "-E", f"LD_LIBRARY_PATH={rootfs}/usr/lib:{rootfs}/lib",
        probe, str(ROOT / "tests/qml/energy_consumers_qt4.qml"), imports,
    ], env={**os.environ, "PROBE_CREATE": "1"}, capture_output=True, text=True, timeout=30)
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
    assert 'source: root.visible && shown === "consumers" ? "C300XEnergyConsumers.qml" : ""' in parent
    assert 'property: "consumers"' in parent
    assert 'color: Consumers.finite(row.consumer.watts) ? "white" : "#c7d0d9"' in source
    assert 'visible: Consumers.finite(row.consumer.watts) && row.consumer.watts > 0' in source
    for token in ("Canvas", "QtQuick 2", "XMLHttpRequest", "kWh", 'text: "log"'):
        assert token not in source


def test_consumers_current_geometry_pixels_scales_and_lazy_unload(tmp_path):
    result = subprocess.run([qt_python(), str(SCRIPT), "--components", "C300XEnergy", "--check",
                             "--output", str(tmp_path)], capture_output=True, text=True, timeout=90)
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
        assert checks["consumers unload when hidden"]["passed"]
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
