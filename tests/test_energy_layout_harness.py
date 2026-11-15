"""Local renderer checks; PySide6 stays optional and outside HA requirements."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_energy_layout.py"
SPEC = importlib.util.spec_from_file_location("energy_layout_harness", SCRIPT)
assert SPEC and SPEC.loader
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


def test_import_adapter_preserves_layout_expressions():
    body = 'Item { width: 728; height: bodyHeight; property string value: "Text" }\n'
    original = 'import QtQuick 1.1\nimport Components 1.0\nimport Components.Styles 1.0\n' + body
    assert HARNESS.adapt_qml(original) == 'import QtQuick 2.15\n' + body
    with pytest.raises(ValueError, match="exactly one"):
        HARNESS.adapt_qml('import QtQuick 2.15\n' + body)


def text_box(name, x, width=20, painted=None, elide=3):
    return {"id": name, "text": name, "box": [x, 0, width, 20],
            "ink": [x, 0, width if painted is None else painted, 20],
            "elide": elide, "wrap": 0}


def test_geometry_finds_overflow_and_overlap_without_flagging_elision():
    assert HARNESS.layout_issues([text_box("a", 0), text_box("b", 30)], [0, 0, 100, 50]) == []
    issues = HARNESS.layout_issues([text_box("a", 0, painted=40), text_box("b", 30)], [0, 0, 100, 50])
    assert {issue["kind"] for issue in issues} == {"text_overflow", "text_overlap"}
    assert HARNESS.layout_issues([text_box("elided", 0, elide=1)], [0, 0, 100, 50]) == []
    assert HARNESS.layout_issues([text_box("outside", 95)], [0, 0, 100, 50])[0]["kind"] == "outside_component"


def test_power_fixtures_use_backend_aggregation_and_one_isolated_dot(monkeypatch):
    from custom_components.bticino_c300x import dashboard_energy_power as backend

    aggregate = backend.power_history_from_statistics
    calls = []

    def record(*args):
        calls.append(args)
        return aggregate(*args)

    monkeypatch.setattr(backend, "power_history_from_statistics", record)
    fixtures = HARNESS.make_fixtures()
    assert len(calls) == len(fixtures) == 8
    for fixture in fixtures:
        power = fixture["energy"]["power"]
        assert power["revision"]
        assert len(power["series"]) == 4
        assert len(power["axis"]["ticks"]) <= 5
        for series in power["series"]:
            points = series["points"]
            assert len(points) == 96
            assert all(point is None or isinstance(point, float) for point in points)
            assert series["dots"] == [{"x": round(42.5 / 96, 6), "y": points[42]}]
            assert points[42] is not None
            assert all(points[index] is None for index in (40, 41, 43, 44))
            assert points[39] is not None and points[45] is not None


def qt_python():
    interpreter = os.environ.get("C300X_QML_PYTHON")
    if not interpreter:
        if importlib.util.find_spec("PySide6") is None:
            pytest.skip("Optional PySide6 absent; set C300X_QML_PYTHON for the local renderer")
        interpreter = sys.executable
    return interpreter


@pytest.mark.parametrize("overlap", [False, True])
def test_offscreen_renderer_ignores_hidden_text_but_catches_visible_overlap(tmp_path, overlap):
    interpreter = qt_python()
    source = tmp_path / "C300XEnergy.qml"
    source.write_text('''import QtQuick 1.1
import Components 1.0
import Components.Styles 1.0
Item {
    property variant energy: ({})
    property string view: ""
    property string shown: "today"
    property int tabHeight: 0
    UbuntuLightText { x: 0; y: 0; text: "Visible value"; font.pixelSize: 18; color: "white" }
    UbuntuLightText { x: SECOND_X; y: 0; text: "Second value"; font.pixelSize: 18; color: "white" }
    Item { visible: false
        UbuntuLightText { x: -30; y: 0; text: "Hidden overlap and out-of-bounds"; font.pixelSize: 36 } }
}
'''.replace("SECOND_X", "0" if overlap else "300"))
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_text(json.dumps([{"name": "normal", "language": "en", "title": "Energy",
                                    "energy": {"views": [{"id": "today", "label": "Today"}]}}]))
    result = subprocess.run([interpreter, str(SCRIPT), "--qml", str(source), "--fixtures", str(fixtures),
                             "--output", str(tmp_path / "output"), "--heights", "230", "--tabs", "single", "--check"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == int(overlap), result.stdout + result.stderr
    report = json.loads((tmp_path / "output/report.json").read_text())
    assert len(report["cases"]) == 1
    case = report["cases"][0]
    assert [item["text"] for item in case["texts"]] == ["Visible value", "Second value"]
    assert case["sampled_colors"] >= 3
    assert {issue["kind"] for issue in case["issues"]} == ({"text_overlap"} if overlap else set())
    assert Path(case["screenshot"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("hide_dots", [False, True])
def test_power_pixel_probe_detects_missing_isolated_dots(tmp_path, hide_dots):
    interpreter = qt_python()
    fixtures = [fixture for fixture in HARNESS.make_fixtures()
                if fixture["language"] == "en" and fixture["name"] == "normal"]
    payload = tmp_path / "fixtures.json"
    payload.write_text(json.dumps(fixtures))
    source = (SCRIPT.parents[1] / "device_qml/C300XEnergy.qml").read_text()
    assert source.count("model: curve.dots") == 1
    # Mutate only a temporary copy: a green report must depend on real dots.
    if hide_dots:
        source = source.replace("model: curve.dots", "model: []")
    qml = tmp_path / "C300XEnergy.qml"
    qml.write_text(source)
    result = subprocess.run([interpreter, str(SCRIPT), "--qml", str(qml), "--fixtures", str(payload),
                             "--views", "power", "--heights", "230", "--tabs", "multi",
                             "--output", str(tmp_path / "output"), "--check"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == int(hide_dots), result.stdout + result.stderr
    report = json.loads((tmp_path / "output/report.json").read_text())
    case = report["cases"][0]
    assert {issue["kind"] for issue in case["issues"]} == ({"power_dot_missing"} if hide_dots else set())
    assert all(dot["visible"] is not hide_dots for dot in case["power_pixels"]["dots"])
    assert all(gap["clear"] for gap in case["power_pixels"]["gaps"])
    assert all(segment["visible"] for segment in case["power_pixels"]["segments"])
