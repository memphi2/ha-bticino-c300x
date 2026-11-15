"""Local chart taps, exact readouts and bounded native Energy presentation."""

import json
import os
import shutil
import subprocess

import pytest
from test_energy_layout_harness import HARNESS, SCRIPT, qt_python

ROOT = SCRIPT.parents[1]
QML = ROOT / "device_qml/C300XEnergy.qml"


def test_production_energy_javascript_and_payloads():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for production Energy JavaScript checks")
    result = subprocess.run(
        [node, str(ROOT / "tests/qml/energy_interaction.cjs")],
        input=json.dumps(HARNESS.make_fixtures()), capture_output=True, text=True, timeout=20,
        env={**os.environ, "TZ": "Pacific/Auckland"},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_energy_dependencies_and_readonly_qtquick1_contract():
    source = QML.read_text()
    dependencies = HARNESS.energy_dependencies(source, QML)
    assert set(dependencies) == {
        "C300XEnergyDistribution.qml", "C300XEnergyReadout.qml", "C300XEnergySums.qml", "js/c300x_energy.js",
    }
    assert len(source.splitlines()) <= 750
    for name, body in dependencies.items():
        assert len(body.splitlines()) < 200
        if name.endswith(".qml"):
            assert body.startswith("import QtQuick 1.1\n")
        for forbidden in ("XMLHttpRequest", "Timer {", "QtQuick 2", "Canvas", ".getHours(", "Api."):
            assert forbidden not in body


@pytest.mark.parametrize(("view", "index"), [("today", 0), ("today", 23), ("power", 42), ("power", 43), ("power", 95)])
def test_native_chart_click_readouts_geometry_and_dismissal(tmp_path, view, index):
    fixtures = HARNESS.make_fixtures()
    payload = tmp_path / "fixtures.json"
    payload.write_text(json.dumps(fixtures))
    result = subprocess.run([
        qt_python(), str(SCRIPT), "--fixtures", str(payload), "--views", view,
        "--inspect", str(index), "--output", str(tmp_path / "output"), "--check",
    ], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "output/report.json").read_text())
    assert not report["messages"]
    assert len(report["cases"]) == 32
    for case in report["cases"]:
        assert case["inspection"] == {"index": index, "same_payload_preserved": True, "dismissed": True}
        assert not case["issues"]
        title = (f"2026-11-15 {index // 4:02d}:{index % 4 * 15:02d} UTC+0000" if view == "power"
                 else f"{index:02d}:00 - {index + 1:02d}:00")
        assert any(item["text"] == title and not item["truncated"] for item in case["texts"])
        values = [item for item in case["texts"] if item["id"] == "sumValue"]
        assert len(values) == (4 if view == "power" else 5)
        assert all(not item["truncated"] for item in values)
        if view == "power" and index == 43:
            assert all(item["text"] == "--" for item in values)
        elif view == "power":
            assert all(item["text"].endswith("W") and "~" not in item["text"] for item in values)
        else:
            assert all(item["text"].endswith(" kWh") for item in values)
