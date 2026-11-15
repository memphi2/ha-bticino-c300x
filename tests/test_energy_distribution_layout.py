"""Current-power distribution rendering and lazy QtQuick 1.1 module contract."""

import copy
import json
import subprocess

import pytest
from test_energy_layout_harness import HARNESS, SCRIPT, qt_python

ROOT = SCRIPT.parents[1]
QML = ROOT / "device_qml/C300XEnergyDistribution.qml"


def distribution_fixtures():
    from custom_components.bticino_c300x.dashboard_labels import (
        ENERGY_LABELS_BY_LANGUAGE,
    )

    fixtures = []
    for language, labels in ENERGY_LABELS_BY_LANGUAGE.items():
        distribution = {"left": [], "right": [], "complete": True, "status": "",
                        "unit": "W", "empty_text": labels["distribution_empty"]}
        for side, entries in (
            ("left", [("grid", 1000, "#80c7ff"), ("solar", 2000, "#ffe477"),
                      ("discharge", 500, "#7fffd4")]),
            ("right", [("home", 2200, "#ffa494"), ("export", 500, "#80c7ff"),
                       ("charge", 800, "#7fffd4")]),
        ):
            start = 0
            for name, watts, color in entries:
                distribution[side].append({"id": name, "label": labels[name], "value": f"{watts} W",
                                           "color": color, "start": start / 3500, "size": watts / 3500})
                start += watts
        for scenario in ("normal", "incomplete", "zero"):
            current = copy.deepcopy(distribution)
            if scenario == "incomplete":
                current["complete"] = False
                current["status"] = labels["distribution_incomplete"]
                current["left"][0]["value"] = None
                current["right"][0].pop("value")
            elif scenario == "zero":
                for node in current["left"] + current["right"]:
                    node.update(value="0 W", start=0, size=0)
            fixtures.append({"language": language, "name": scenario, "title": labels["title"], "energy": {
                "views": [{"id": name, "label": labels[name]}
                          for name in ("now", "today", "power", "distribution", "balance")],
                "distribution": current,
                "balance": [{"label": labels["home"], "value": "2.2 kWh"}],
            }})
    return fixtures


def test_distribution_stays_a_separate_bounded_qtquick1_module():
    source = QML.read_text()
    parent = (QML.parent / "C300XEnergy.qml").read_text()
    assert source.startswith("import QtQuick 1.1\n")
    assert len(source.splitlines()) < 200
    assert all(token not in source for token in ("Canvas", "QtQuick 2", "Shape", "<svg", "kWh", "Timer"))
    assert "value.slice(0, 3)" in source
    assert "model: root.complete && band.thickness > 0 ? 24 : 0" in source
    assert "t * t * (3 - 2 * t)" in source
    assert 'source: shown === "distribution" ? "C300XEnergyDistribution.qml" : ""' in parent
    assert 'target: distributionLoader.item' in parent
    assert 'property: "distribution"' in parent
    assert "font.pixelSize: root.views.length > 4 ? 16 : 18" in parent


def test_optional_production_fixtures_keep_existing_matrix_size():
    fixtures = HARNESS.make_fixtures(include_distribution=True)
    assert len(fixtures) == 8
    for fixture in fixtures:
        assert [view["id"] for view in fixture["energy"]["views"]] == [
            "now", "today", "power", "distribution", "balance",
        ]
        assert fixture["energy"]["distribution"]["unit"] == "W"


def test_distribution_geometry_pixels_unknowns_and_lazy_unload(tmp_path):
    fixtures = distribution_fixtures()
    payload = tmp_path / "fixtures.json"
    payload.write_text(json.dumps(fixtures))
    result = subprocess.run([
        qt_python(), str(SCRIPT), "--fixtures", str(payload), "--views", "distribution", "balance",
        "--scenarios", "normal", "incomplete", "zero", "--tabs", "multi", "single",
        "--output", str(tmp_path / "output"), "--check",
    ], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "output/report.json").read_text())
    assert not report["messages"]
    assert report["dependencies"][QML.name]
    assert len(report["cases"]) == 96
    for case in report["cases"]:
        checks = case["distribution_pixels"]
        texts = [item["text"] for item in case["texts"]]
        assert not case["issues"]
        if case["view"] != "distribution":
            assert checks["loaded"] == checks["slices"] == 0
            continue
        assert checks["loaded"] == 1
        assert all("kWh" not in text for text in texts)
        if "-normal-" in case["name"]:
            assert checks["slices"] == checks["checked_pixels"] == 144
        else:
            assert checks["slices"] == 0
        if "-incomplete-" in case["name"]:
            assert texts.count("--") == 2
            assert "2000 W" in texts
            expected = next(fixture["energy"]["distribution"]["status"] for fixture in fixtures
                            if fixture["language"] == case["name"].split("-")[0]
                            and fixture["name"] == "incomplete")
            assert expected in texts
        if case["tabs"] == "multi":
            tabs = [item for item in case["texts"] if item["box"][1] >= case["height"] - 40]
            assert len(tabs) == 5
            assert {item["font"]["pixels"] for item in tabs} == {16}, case["name"]


def test_distribution_probe_rejects_missing_ribbons(tmp_path):
    source = QML.read_text().replace("model: root.complete && band.thickness > 0 ? 24 : 0", "model: 0")
    (tmp_path / QML.name).write_text(source)
    parent = tmp_path / "C300XEnergy.qml"
    parent.write_text((QML.parent / parent.name).read_text())
    payload = tmp_path / "fixtures.json"
    payload.write_text(json.dumps([distribution_fixtures()[0]]))
    result = subprocess.run([
        qt_python(), str(SCRIPT), "--qml", str(parent), "--fixtures", str(payload),
        "--views", "distribution", "--tabs", "multi", "--heights", "230",
        "--output", str(tmp_path / "output"), "--check",
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads((tmp_path / "output/report.json").read_text())
    assert {issue["kind"] for issue in report["cases"][0]["issues"]} == {"distribution_slice_count"}


@pytest.mark.parametrize("distribution", [None, {}])
def test_missing_distribution_is_safe_during_loader_binding(tmp_path, distribution):
    fixture = distribution_fixtures()[0]
    fixture["energy"]["distribution"] = distribution
    payload = tmp_path / "fixtures.json"
    payload.write_text(json.dumps([fixture]))
    result = subprocess.run([
        qt_python(), str(SCRIPT), "--fixtures", str(payload), "--views", "distribution",
        "--tabs", "multi", "--heights", "230", "--output", str(tmp_path / "output"), "--check",
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "output/report.json").read_text())
    assert not report["messages"]
    assert report["cases"][0]["distribution_pixels"]["slices"] == 0
    assert "--" in [item["text"] for item in report["cases"][0]["texts"]]
