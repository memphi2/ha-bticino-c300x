"""Focused local-only verifier tests; Qt stays outside integration dependencies."""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_display_layout.py"
SPEC = importlib.util.spec_from_file_location("display_layout_harness", SCRIPT)
assert SPEC and SPEC.loader
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


def test_import_adapter_preserves_production_body():
    body = 'Item { width: parent.width; property variant payload: ({}) }\n'
    source = 'import QtQuick 1.1\nimport Components 1.0\nimport Components.Styles 1.0\n' + body
    assert HARNESS.adapt_qml(source) == 'import QtQuick 2.15\n' + body
    with pytest.raises(ValueError, match="exactly one"):
        HARNESS.adapt_qml('import QtQuick 2.15\n' + body)


def text_box(name="label", x=0, width=20, ink_width=20):
    return {"id": name, "text": name, "box": [x, 0, width, 20],
            "raw_ink": [x, 0, ink_width, 20], "ink": [x, 0, ink_width, 20]}


def test_geometry_detects_own_box_overflow_even_when_clipped():
    text = text_box(ink_width=40)
    text["ink"] = [0, 0, 20, 20]
    assert [issue["kind"] for issue in HARNESS.layout_issues([text], [0, 0, 100, 50])] == ["text_overflow"]


def test_geometry_uses_visible_ink_for_overlap_and_viewport_bounds():
    assert HARNESS.layout_issues([text_box(), text_box("second", x=30)], [0, 0, 100, 50]) == []
    assert HARNESS.layout_issues([text_box(), text_box("second", x=10)], [0, 0, 100, 50])[0]["kind"] == "text_overlap"
    assert HARNESS.layout_issues([text_box(x=95)], [0, 0, 100, 50])[0]["kind"] == "outside_viewport"
    scrolled = text_box()
    scrolled.update(box=[0, -10, 20, 20], raw_ink=[0, -10, 20, 20], ink=[0, 0, 20, 10])
    assert HARNESS.layout_issues([scrolled], [0, 0, 100, 50]) == []


def test_fixtures_cover_actual_contracts_and_three_viewports():
    fixtures = HARNESS.fixtures()
    assert {fixture["component"] for fixture in fixtures} == set(HARNESS.COMPONENTS)
    assert HARNESS.VIEWPORTS["native"] == (800, 480, 748, 300)
    assert len(HARNESS.VIEWPORTS) == 3
    assert HARNESS.VIEWPORTS["narrow"][2] < 748
    controls = [fixture["properties"]["control"] for fixture in fixtures if fixture["component"] == "C300XDetailControl"]
    assert {control["kind"] for control in controls} == {"boolean", "button", "number", "choice"}
    assert any(control.get("swatches") for control in controls)
    assert any(control["value"] is None for control in controls)
    for fixture in fixtures:
        wrapper = HARNESS.frame_qml(fixture, HARNESS.VIEWPORTS["native"])
        assert fixture["component"] in wrapper
        assert 'objectName: "viewport"' in wrapper


def qt_python():
    interpreter = os.environ.get("C300X_QML_PYTHON")
    if not interpreter:
        if importlib.util.find_spec("PySide6") is None:
            pytest.skip("Optional PySide6 absent; set C300X_QML_PYTHON")
        interpreter = sys.executable
    return interpreter


def run_harness(tmp_path, component, source):
    qml = tmp_path / (component + ".qml")
    qml.write_text(source)
    result = subprocess.run([qt_python(), str(SCRIPT), "--qml-dir", str(tmp_path),
                             "--components", component, "--viewports", "narrow",
                             "--output", str(tmp_path / "output"), "--check"],
                            capture_output=True, text=True, timeout=45)
    report = json.loads((tmp_path / "output/report.json").read_text())
    assert report["production_files"][str(qml)] == hashlib.sha256(source.encode()).hexdigest()
    assert qml.read_text() == source
    return result, report


@pytest.mark.parametrize("fault", ["none", "duplicate_signal", "blank", "qml_error", "overflow"])
def test_navigation_renderer_detects_regressions_in_temporary_sources(tmp_path, fault):
    component = "C300XPageNavigation"
    source = (SCRIPT.parents[1] / "device_qml" / (component + ".qml")).read_text()
    if fault == "duplicate_signal":
        old = "onClicked: navigation.selected(navigation.links[index].index)"
        assert old in source
        source = source.replace(old, "onClicked: { navigation.selected(navigation.links[index].index); navigation.selected(navigation.links[index].index) }")
    elif fault == "blank":
        source = source.replace("id: navigation", "id: navigation\n    opacity: 0")
    elif fault == "qml_error":
        source = source.replace("id: navigation", "id: navigation\n    Component.onCompleted: missingSmokeFunction()")
    elif fault == "overflow":
        source = source.replace("wrapMode: Text.Wrap", "wrapMode: Text.NoWrap").replace("elide: Text.ElideRight", "elide: Text.ElideNone")
    result, report = run_harness(tmp_path, component, source)
    assert result.returncode == int(fault != "none"), result.stdout + result.stderr
    kinds = {issue["kind"] for case in report["cases"] for issue in case["issues"]}
    expected = {"duplicate_signal": "interaction", "blank": "blank_component",
                "qml_error": "qml_diagnostic", "overflow": "text_overflow"}
    if fault != "none":
        assert expected[fault] in kinds
    else:
        assert not kinds
        for case in report["cases"]:
            assert len(case["events"]) == 4
            assert len(case["snapshots"]) == 9
            for shot in case["snapshots"]:
                assert Path(shot["screenshot"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("automatic", [False, True])
def test_leave_home_requires_second_click(tmp_path, automatic):
    component = "C300XLeaveHome"
    source = (SCRIPT.parents[1] / "device_qml" / (component + ".qml")).read_text()
    if automatic:
        old = "pendingActionId = item.entity_id"
        assert old in source
        source = source.replace(old, old + "\n            actionRequested(item)")
    result, report = run_harness(tmp_path, component, source)
    assert result.returncode == int(automatic), result.stdout + result.stderr
    failures = [check["name"] for case in report["cases"] for check in case["checks"] if not check["passed"]]
    assert ("first tap only arms" in failures) is automatic
    states = {shot["state"] for case in report["cases"] for shot in case["snapshots"]}
    assert {"departure-confirm", "departure-confirmed", "busy", "online"} <= states
