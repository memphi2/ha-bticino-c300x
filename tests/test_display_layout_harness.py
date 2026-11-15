"""Focused local-only verifier tests; Qt stays outside integration dependencies."""

import hashlib
import importlib.util
import json
import os
import re
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


def test_api_transport_mock_preserves_production_queue():
    source = (SCRIPT.parents[1] / "device_qml/js/c300x_ha.js").read_text()
    adapted = HARNESS.mock_api_transport(source)
    injected = "function XMLHttpRequest() { return new mockTransport.constructor() }\n"
    assert adapted.replace(injected, "", 1) == source
    assert adapted.count(injected) == 1
    with pytest.raises(ValueError, match="shared API"):
        HARNESS.mock_api_transport("function example() {}")


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
    assert len([fixture for fixture in fixtures if fixture["component"] in HARNESS.COMPONENTS[:4]]) * 3 == 57
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


def run_harness(tmp_path, component, source, scenarios=()):
    qml = tmp_path / (component + ".qml")
    qml.write_text(source)
    dependencies = {}
    if component == "C300XAlerts":
        (tmp_path / "js").mkdir()
        for name in ("c300x_alerts.js", "c300x_i18n.js", "c300x_ha.js"):
            dependency = tmp_path / "js" / name
            body = (SCRIPT.parents[1] / "device_qml/js" / name).read_bytes()
            dependency.write_bytes(body)
            dependencies[dependency] = body
    result = subprocess.run([qt_python(), str(SCRIPT), "--qml-dir", str(tmp_path),
                             "--components", component, "--viewports", "narrow",
                             "--output", str(tmp_path / "output"), "--check",
                             *(["--scenarios", *scenarios] if scenarios else [])],
                            capture_output=True, text=True, timeout=120)
    report_path = tmp_path / "output/report.json"
    if not report_path.is_file():
        raise AssertionError(
            f"Harness produced no report (exit {result.returncode}): {report_path}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    report = json.loads(report_path.read_text())
    assert report["production_files"][str(qml)] == hashlib.sha256(source.encode()).hexdigest()
    assert qml.read_text() == source
    for dependency, body in dependencies.items():
        assert report["production_files"][str(dependency)] == hashlib.sha256(body).hexdigest()
        assert dependency.read_bytes() == body
        assert (tmp_path / "output/sources" / dependency.relative_to(tmp_path)).read_bytes() == body
    return result, report


def test_harness_startup_failure_reports_subprocess_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setenv("C300X_QML_PYTHON", sys.executable)
    result = subprocess.CompletedProcess([], 1, stdout="startup marker", stderr="Unreviewed Connections handler")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result)
    with pytest.raises(AssertionError, match="Harness produced no report") as error:
        run_harness(tmp_path, "C300XPageNavigation", "import QtQuick 1.1\nItem {}")
    assert "exit 1" in str(error.value)
    assert "stdout:\nstartup marker" in str(error.value)
    assert "stderr:\nUnreviewed Connections handler" in str(error.value)


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


def test_alert_import_adapter_preserves_vendor_imports_and_production_body():
    source = (SCRIPT.parents[1] / "device_qml/C300XAlerts.qml").read_text()
    adapted = HARNESS.adapt_qml(source)
    body = re.search(r"(?m)^        onStateChangedInt: (.+)$", source).group(1)
    modern = re.search(r"(?m)^        function onStateChangedInt\(\) \{ (.+) \}$", adapted).group(1)
    assert modern == body
    restored = adapted.replace(f"function onStateChangedInt() {{ {modern} }}", f"onStateChangedInt: {body}")
    mouse_body = re.search(r"        onPressed: \{\n(.*?)\n        \}", source, re.S).group(1)
    modern_mouse = re.search(r"        onPressed: function\(mouse\) \{\n(.*?)\n        \}", adapted, re.S).group(1)
    assert modern_mouse == mouse_body
    restored = restored.replace("onPressed: function(mouse) {", "onPressed: {")
    assert restored == source.replace("import QtQuick 1.1", "import QtQuick 2.15", 1)
    assert 'import BtClass 1.0' in adapted
    assert 'import "js/c300x_alerts.js" as Alerts' in adapted


@pytest.mark.parametrize(("old", "new"), [
    ("root.screenChanged()", "root.screenChanged(1)"),
    ("onStateChangedInt:", "onStateChanged:"),
    ("target: global.screenState", "target: global.audioState"),
    ("        onStateChangedInt:", "    onStateChangedInt:"),
])
def test_connection_adapter_rejects_unreviewed_handlers(old, new):
    source = (SCRIPT.parents[1] / "device_qml/C300XAlerts.qml").read_text()
    assert old in source
    with pytest.raises(ValueError, match="Unreviewed Connections handler"):
        HARNESS.adapt_qml(source.replace(old, new))


def test_connection_adapter_rejects_additional_connections():
    source = (SCRIPT.parents[1] / "device_qml/C300XAlerts.qml").read_text()
    with pytest.raises(ValueError, match="Unreviewed Connections handler"):
        HARNESS.adapt_qml(source + '\nConnections { target: null; onUnknown: {} }\n')


@pytest.mark.parametrize(("old", "new"), [
    ("mouse.accepted = false", "mouse.accepted = true"),
    ("            root.userInteraction()\n", "            root.acknowledge()\n"),
    ("enabled: !!root.notice && !root.blocked", "enabled: !!root.notice"),
])
def test_mouse_adapter_rejects_unreviewed_bodies(old, new):
    source = (SCRIPT.parents[1] / "device_qml/C300XAlerts.qml").read_text()
    assert old in source
    with pytest.raises(ValueError, match="Unreviewed mouse handler"):
        HARNESS.adapt_qml(source.replace(old, new))


def test_shared_window_keeps_real_confirmation_timer_after_navigation(tmp_path):
    result = subprocess.run([qt_python(), str(SCRIPT), "--components", "C300XPageNavigation", "C300XLeaveHome",
                             "--scenarios", "normal", "--viewports", "native", "--check",
                             "--output", str(tmp_path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    assert len(report["cases"]) == 2 and report["passed"]
    checks = {check["name"]: check for check in report["cases"][1]["checks"]}
    assert checks["timeout never executes"]["passed"]
    assert checks["timeout clears confirmation"]["passed"]


@pytest.mark.parametrize("fault", ["none", "wrong_palette", "click_through", "broken_scroll",
                                    "ignore_blocked", "qml_error", "network_fallback"])
def test_alerts_mock_transport_pixels_and_interactions(tmp_path, fault):
    component = "C300XAlerts"
    source = (SCRIPT.parents[1] / "device_qml" / (component + ".qml")).read_text()
    replacements = {
        "wrong_palette": ('color: "#176196"', 'color: "#a00000"'),
        "click_through": ('onClicked: root.acknowledge()',
                          'propagateComposedEvents: true; onClicked: { root.acknowledge(); mouse.accepted = false }'),
        "broken_scroll": ('id: messageScroll', 'id: messageScroll; interactive: false'),
        "ignore_blocked": ('function preempt() {\n        abortPoll()', 'function preempt() {\n        /* broken abort */'),
        "qml_error": ('Component.onCompleted: initialize()',
                      'Component.onCompleted: { initialize(); missingSmokeFunction() }'),
        "network_fallback": ('Component.onCompleted: initialize()',
                             'Component.onCompleted: { initialize(); var r = new (Function("return XMLHttpRequest")())(); '
                             'r.open("GET", "http://127.0.0.1:8090/never-connect"); r.send() }'),
    }
    if fault != "none":
        old, new = replacements[fault]
        assert old in source
        source = source.replace(old, new, 1)
    result, report = run_harness(tmp_path, component, source, () if fault == "none" else ("info-long",))
    assert result.returncode == int(fault != "none"), result.stdout + result.stderr
    kinds = {issue["kind"] for case in report["cases"] for issue in case["issues"]}
    failed = {check["name"] for case in report["cases"] for check in case["checks"] if not check["passed"]}
    expected = {"wrong_palette": "native blue panel", "click_through": "ack touch never clicks underlying",
                "broken_scroll": "long message drag moves", "ignore_blocked": "callActive-True aborts poll"}
    if fault in expected:
        assert expected[fault] in failed
    elif fault == "network_fallback":
        assert "network_denied" in kinds
        assert any(case["network_attempts"] == ["http://127.0.0.1:8090/never-connect"] for case in report["cases"])
    elif fault == "qml_error":
        assert "qml_diagnostic" in kinds
    else:
        assert report["passed"] and not kinds and not failed
        assert len(report["cases"]) == 6
        for case in report["cases"]:
            assert not case["network_attempts"]
            assert not case["diagnostics"]
            assert "adaptation_warnings" not in case
            requests = case["mock_requests"]
            assert len([request for request in requests if "/homeassistant?" in request["url"]]) == 1
            assert len([request for request in requests if "/ui/alerts/next" in request["url"]]) == 14
            assert all(request["method"] == "GET" for request in requests)
            states = {shot["state"] for shot in case["snapshots"]}
            assert {"acknowledged", "blocked-callActive-True", "blocked-activePage-alarm", "blocked-visible-False"} <= states
            if case["fixture"].endswith("-long"):
                assert {"long-top", "long-bottom"} <= states
        qml = str(tmp_path / (component + ".qml"))
        assert report["adapted_files"][qml] == hashlib.sha256(HARNESS.adapt_qml(source).encode()).hexdigest()
        assert report["adapted_files"][qml] != report["production_files"][qml]
