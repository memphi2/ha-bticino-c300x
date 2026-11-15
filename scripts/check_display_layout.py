#!/usr/bin/env python3
"""Local Qt6-adapted smoke/layout checks, NOT Qt4 or hardware validation.

Run with an optional PySide6 interpreter::

    /path/to/qt-python scripts/check_display_layout.py --check

Only temporary copies receive QtQuick import and image substitutions. Vendor
text/mouse components and the detail host are mocks, following the standalone
energy harness pattern without importing its worker-owned implementation.
No HA, device, network, firmware, or production-file writes are needed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ("C300XPageNavigation", "C300XAgenda", "C300XLeaveHome", "C300XDetailControl")
VIEWPORTS = {"native": (800, 480, 748, 300), "short": (800, 480, 748, 230),
             "narrow": (480, 480, 428, 300)}
LONG = "Very long household label - garage, upstairs and garden equipment " * 3


def adapt_qml(source: str) -> str:
    """Preserve production expressions, changing only unsupported imports."""
    source, count = re.subn(r"(?m)^import QtQuick 1\.1\s*$", "import QtQuick 2.15", source)
    if count != 1:
        raise ValueError("Expected exactly one QtQuick 1.1 import")
    return re.sub(r"(?m)^import Components(?:\.Styles)? 1\.0\s*\n", "", source)


def fixtures() -> list[dict]:
    cases = []

    def add(component, name, **properties):
        cases.append({"component": component, "name": name, "properties": properties})

    for stress in (False, True):
        name = "long" if stress else "normal"
        label = LONG if stress else "Household"
        add(COMPONENTS[0], name, links=[{"index": index, "title": label + " " + title}
                                      for index, title in zip((7, 2, 11, 5),
                                                             ("Agenda", "Energy", "Departure", "Lights"), strict=True)])
        add(COMPONENTS[1], name, agenda={"events": [
            {"summary": label + f" appointment {i}", "when": "Tomorrow 10:30 - 12:00",
             "calendar": label} for i in range(8)]})
        add(COMPONENTS[2], name, leaveHome={
            "checks": [{"name": label + " windows", "state_label": label if stress else "Closed", "color": "#58d68d"},
                       {"name": label + " lights", "state_label": "Off", "color": "#c7d0d9"}],
            "alarm": {"name": label + " alarm", "state_label": "Disarmed", "available": True},
            "actions": [{"entity_id": "scene.departure", "name": label + " departure"},
                        {"entity_id": "script.lights_off", "name": label + " lights off"}],
            "confirm_label": "Confirm departure" if not stress else LONG,
            "cancel_label": "Cancel" if not stress else LONG,
            "empty_text": "No checks configured"}, busy=False, online=True)
        for kind in ("button", "boolean", "number", "choice"):
            control = {"kind": kind, "command": label, "value": True if kind == "boolean" else 20}
            if kind == "number":
                control.update(min=0, max=100, step=5, unit="%", presets=[
                    {"value": value, "label": label if stress else str(value)} for value in (0, 25, 75, 100)])
            if kind == "choice":
                control.update(options=["one", "two", "three", "four"], value="two",
                               labels=[label + f" option {i}" for i in range(4)])
            add(COMPONENTS[3], kind + "-" + name, control=control)
    add(COMPONENTS[1], "empty", agenda={"events": [], "empty_text": "No upcoming appointments"})
    add(COMPONENTS[1], "error", agenda={"events": [], "error": LONG})
    add(COMPONENTS[2], "empty", leaveHome={"checks": [], "actions": [], "empty_text": "No checks configured"})
    add(COMPONENTS[3], "swatches", paletteTab=True, control={
        "kind": "choice", "command": "color", "options": ["red", "green", "blue", "white"],
        "labels": [LONG, "Green", "Blue", "White"], "swatches": ["#ff0000", "#00ff00", "#0000ff", "#ffffff"],
        "value": "green"})
    add(COMPONENTS[3], "number-unset", control={"kind": "number", "command": "Brightness", "value": None,
                                               "min": 0, "max": 100, "step": 5})
    return cases


def intersection(a, b):
    x, y = max(a[0], b[0]), max(a[1], b[1])
    return [x, y, max(0, min(a[0] + a[2], b[0] + b[2]) - x),
            max(0, min(a[1] + a[3], b[1] + b[3]) - y)]


def contains(outer, inner, tolerance=1):
    return (inner[0] >= outer[0] - tolerance and inner[1] >= outer[1] - tolerance
            and inner[0] + inner[2] <= outer[0] + outer[2] + tolerance
            and inner[1] + inner[3] <= outer[1] + outer[3] + tolerance)


def layout_issues(texts, bounds):
    """Use clipped visible ink for overlap, but raw ink for own-box overflow."""
    issues = []
    for text in texts:
        if min(text["box"][2:]) < 0:
            issues.append({"kind": "negative_text_box", "id": text["id"]})
        if not contains(text["box"], text["raw_ink"]):
            issues.append({"kind": "text_overflow", "id": text["id"], "text": text["text"]})
        if not contains(bounds, text["ink"]):
            issues.append({"kind": "outside_viewport", "id": text["id"]})
    for index, first in enumerate(texts):
        for second in texts[index + 1:]:
            overlap = intersection(first["ink"], second["ink"])
            if min(overlap[2:]) > 1:
                issues.append({"kind": "text_overlap", "ids": [first["id"], second["id"]]})
    return issues


HOST = """
    property bool interactionActive: false
    function uiText(key) { return String(key) }
    function controlLabel(c) { return uiText(c.command) }
    function controlValueUnset(c) { return c.value === null || c.value === undefined }
    function numberText(c, value) { return String(value) + (c.unit ? " " + c.unit : "") }
    function controlValue(c) { return controlValueUnset(c) ? "?" : numberText(c, c.value) }
    function controlLastStep(c) { return Math.floor((c.max - c.min) / c.step + 0.000000001) }
    function optionLabel(c, option, position) { return c.labels ? String(c.labels[position]) : String(option) }
    property variant eventLog: []
    function record(name, value) { eventLog = eventLog.concat([{signal: name, value: value}]) }
"""


def frame_qml(fixture, viewport):
    width, height, content_width, content_height = viewport
    component = fixture["component"]
    props = "\n".join(f"{key}: ({json.dumps(value)})" for key, value in fixture["properties"].items())
    handlers = {
        COMPONENTS[0]: 'onSelected: function(pageIndex) { frame.record("selected", pageIndex) }',
        COMPONENTS[1]: "",
        COMPONENTS[2]: 'onActionRequested: function(item) { frame.record("actionRequested", item.entity_id) }\n'
                       'onAlarmRequested: frame.record("alarmRequested", null)',
        COMPONENTS[3]: 'hostPage: frame\nonSubmitted: function(value) { frame.record("submitted", value) }\n'
                       'onAdjusted: function(direction) { frame.record("adjusted", direction) }\n'
                       'onRefreshRequested: frame.record("refreshRequested", null)',
    }
    target = f'{component} {{ id: target; objectName: "target"; width: {content_width}\n{props}\n{handlers[component]}\n'
    if component in COMPONENTS[1:3]:
        target += f"height: {content_height}\n"
    target += "}"
    # Detail rows belong in a scrolling parent, as in HomeAssistant.qml.
    if component == COMPONENTS[3]:
        target = f'Flickable {{ objectName: "detailScroll"; anchors.fill: parent; clip: true; contentHeight: target.height; {target} }}'
    return f'''import QtQuick 2.15
Rectangle {{
    id: frame; width: {width}; height: {height}; color: "#123f65"
    {HOST}
    Item {{ objectName: "viewport"; x: 26; y: 94; width: {content_width}; height: {content_height}
        {target}
    }}
}}
'''


def render(args):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_QUICK_BACKEND"] = "software"
    os.environ["QT_SCALE_FACTOR"] = "1"
    from PySide6.QtCore import (
        QPointF,
        QRectF,
        Qt,
        QUrl,
        qInstallMessageHandler,
        qVersion,
    )
    from PySide6.QtGui import QColor, QFontInfo, QGuiApplication, QImage
    from PySide6.QtQml import QQmlEngine
    from PySide6.QtQuick import QQuickItem, QQuickView
    from PySide6.QtTest import QTest

    app = QGuiApplication.instance() or QGuiApplication([])
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(
        {"type": str(kind), "message": message, "file": context.file, "line": context.line}))
    selected_fixtures = [case for case in fixtures() if case["component"] in args.components]
    sources = {name: (args.qml_dir / (name + ".qml")).read_bytes() for name in args.components}
    report = {"scope": "Qt6 adaptation only; NOT Qt4/hardware validation", "qt": qVersion(),
              "renderer": "offscreen/software", "mocks": ["UbuntuLightText", "BeepingMouseArea", "button images", "detail hostPage"],
              "viewports": VIEWPORTS, "cases": [], "issues": [],
              "command": [sys.executable, *sys.argv],
              "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "production_files": {str(args.qml_dir / (name + ".qml")): hashlib.sha256(data).hexdigest()
                                   for name, data in sources.items()},
              "fixtures_sha256": hashlib.sha256(json.dumps(selected_fixtures, sort_keys=True).encode()).hexdigest()}

    def settle(ms=30):
        app.processEvents()
        QTest.qWait(ms)
        app.processEvents()

    def walk(item):
        yield item
        for child in item.childItems():
            yield from walk(child)

    def named(root, name):
        for item in walk(root):
            context = QQmlEngine.contextForObject(item)
            if item.objectName() == name or (context and context.nameForObject(item) == name):
                return item
        raise AssertionError(f"Missing QML item: {name}")

    def rectangle(rect):
        return [rect.x(), rect.y(), rect.width(), rect.height()]

    try:
        with tempfile.TemporaryDirectory(prefix="c300x-display-layout-") as temp:
            directory = Path(temp)
            for name, data in sources.items():
                source = adapt_qml(data.decode())
                (args.output / "sources").mkdir(exist_ok=True)
                (args.output / "sources" / (name + ".qml")).write_bytes(data)
                for asset in set(re.findall(r'"(images/[^"\n]+\.svg)"', source)):
                    relative = str(Path(asset).with_suffix(".png"))
                    target = directory / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    picture = QImage(16, 16, QImage.Format_ARGB32)
                    picture.fill(QColor("#397ba3" if "_p.svg" in asset else "#24547b" if "list_btn" in asset else "#19476b"))
                    if not picture.save(str(target)):
                        raise RuntimeError(f"Cannot save mock image {target}")
                    source = source.replace(asset, relative)
                (directory / (name + ".qml")).write_text(source)
            (directory / "UbuntuLightText.qml").write_text(
                'import QtQuick 2.15\nText { textFormat: Text.PlainText; font.family: "Ubuntu"; font.weight: Font.Light }\n')
            (directory / "BeepingMouseArea.qml").write_text('import QtQuick 2.15\nMouseArea {}\n')
            for fixture in selected_fixtures:
                for viewport_name in args.viewports:
                    viewport = VIEWPORTS[viewport_name]
                    start_messages = len(messages)
                    case = {"component": fixture["component"], "fixture": fixture["name"], "viewport": viewport_name,
                            "snapshots": [], "checks": [], "issues": []}
                    report["cases"].append(case)
                    window = QQuickView()
                    frame_path = directory / "Frame.qml"
                    frame_path.write_text(frame_qml(fixture, viewport))
                    window.setSource(QUrl.fromLocalFile(str(frame_path)))
                    try:
                        if window.status() == QQuickView.Error:
                            raise RuntimeError("\n".join(error.toString() for error in window.errors()))
                        frame = window.rootObject()
                        component = frame.findChild(QQuickItem, "target")
                        area = frame.findChild(QQuickItem, "viewport")
                        window.show()
                        settle()
                        # Retain Python wrappers while QML exposes these objects to JS.
                        _item_wrappers = list(walk(frame))
                        engine = window.engine()
                        engine.globalObject().setProperty("probe", engine.newQObject(frame))
                        enums = engine.evaluate("(function(t) { return {a:+t.horizontalAlignment, v:+t.verticalAlignment}; })")

                        def event_log(engine=engine):
                            return json.loads(engine.evaluate("JSON.stringify(probe.eventLog)").toString())

                        def check(name, actual, expected, case=case):
                            case["checks"].append({"name": name, "actual": actual, "expected": expected, "passed": actual == expected})
                            if actual != expected:
                                case["issues"].append({"kind": "interaction", "check": name, "actual": actual, "expected": expected})

                        def click(item, window=window):
                            point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
                            if not (0 <= point.x() < window.width() and 0 <= point.y() < window.height()):
                                raise AssertionError("Click outside window")
                            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
                            settle()

                        def snapshot(state, area=area, engine=engine, enums=enums,
                                     window=window, fixture=fixture, viewport_name=viewport_name,
                                     viewport=viewport, case=case):
                            texts = []

                            def visit(node, clips, path):
                                if not node.isVisible() or node.opacity() <= 0:
                                    return
                                box = rectangle(node.mapRectToItem(area, QRectF(0, 0, node.width(), node.height())))
                                if node.clip():
                                    clips = [*clips, box]
                                text = node.property("text")
                                if isinstance(text, str) and text:
                                    width = float(node.property("contentWidth") or node.property("paintedWidth") or 0)
                                    height = float(node.property("contentHeight") or node.property("paintedHeight") or 0)
                                    alignment = enums.call([engine.newQObject(node)]).toVariant()
                                    x = node.width() - width if alignment["a"] == 2 else (node.width() - width) / 2 if alignment["a"] == 4 else 0
                                    y = node.height() - height if alignment["v"] == 64 else (node.height() - height) / 2 if alignment["v"] == 128 else 0
                                    raw = rectangle(node.mapRectToItem(area, QRectF(x, y, width, height)))
                                    ink = raw
                                    for clip in clips:
                                        ink = intersection(ink, clip)
                                    if min(ink[2:]) > 0:
                                        info = QFontInfo(node.property("font"))
                                        texts.append({"id": path, "text": text, "box": box, "raw_ink": raw, "ink": ink,
                                                      "truncated": bool(node.property("truncated")),
                                                      "font": {"family": info.family(), "pixels": info.pixelSize()}})
                                for index, child in enumerate(node.childItems()):
                                    visit(child, clips, f"{path}/{index}")

                            visit(area, [], "viewport")
                            issues = layout_issues(texts, [0, 0, viewport[2], viewport[3]])
                            shot = window.grabWindow()
                            filename = f'{fixture["component"]}-{fixture["name"]}-{viewport_name}-{state}.png'
                            path = args.output / filename
                            if shot.isNull() or not shot.save(str(path)):
                                raise RuntimeError(f"Screenshot failed: {path}")
                            crop = shot.copy(26, 94, viewport[2], viewport[3])
                            colors = {crop.pixel(x, y) for x in range(0, crop.width(), 2) for y in range(0, crop.height(), 2)}
                            # Frame chrome cannot make a blank target pass; require text and actual white text pixels.
                            light_pixels = sum(crop.pixelColor(x, y).lightness() > 170
                                               for x in range(0, crop.width(), 2) for y in range(0, crop.height(), 2))
                            if len(colors) < 3 or light_pixels < 5 or not texts:
                                issues.append({"kind": "blank_component"})
                            case["snapshots"].append({"state": state, "screenshot": str(path),
                                                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                                      "sampled_colors": len(colors), "light_pixels": light_pixels,
                                                      "texts": texts, "issues": issues})
                            case["issues"].extend({**issue, "state": state} for issue in issues)
                            return hashlib.sha256(path.read_bytes()).hexdigest()

                        initial_image = snapshot("initial")
                        if fixture["component"] == COMPONENTS[0]:
                            buttons = [item for item in walk(component)
                                       if "BeepingMouseArea" in item.metaObject().className()]
                            check("navigation button count", len(buttons), len(fixture["properties"]["links"]))
                            for index, button in enumerate(buttons):
                                before = len(event_log())
                                point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
                                QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point)
                                settle()
                                pressed_image = snapshot(f"pressed-{index}")
                                check(f"pressed navigation pixels change {index}", pressed_image != initial_image, True)
                                QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, point)
                                settle()
                                check(f"selected once {index}", event_log()[before:],
                                      [{"signal": "selected", "value": fixture["properties"]["links"][index]["index"]}])
                                selected_image = snapshot(f"selected-{index}")
                                check(f"released navigation pixels reset {index}", selected_image, initial_image)
                        elif fixture["component"] == COMPONENTS[2] and fixture["name"] != "empty":
                            button = named(component, "actionMouse")
                            action = fixture["properties"]["leaveHome"]["actions"][0]["entity_id"]
                            click(button)
                            check("first tap only arms", event_log(), [])
                            check("pending confirmation", component.property("pendingActionId"), action)
                            confirm_image = snapshot("departure-confirm")
                            check("confirmation pixels change", confirm_image != initial_image, True)
                            if viewport_name == "native" and fixture["name"] == "normal":
                                # Real production timeout, not a shortened/adapted timer.
                                settle(8250)
                                check("timeout never executes", event_log(), [])
                                check("timeout clears confirmation", component.property("pendingActionId"), "")
                                snapshot("confirmation-expired")
                                click(button)
                            click(button)
                            check("second tap executes exactly once", event_log(), [{"signal": "actionRequested", "value": action}])
                            check("confirmation cleared", component.property("pendingActionId"), "")
                            confirmed_image = snapshot("departure-confirmed")
                            check("confirmed pixels reset", confirmed_image, initial_image)
                            before = event_log()
                            click(button)
                            cancel_text = next(item for item in walk(component)
                                               if item.isVisible() and item.property("text") == fixture["properties"]["leaveHome"]["cancel_label"]
                                               and item.property("font").pixelSize() == 18)
                            cancel = next(item for item in cancel_text.parentItem().childItems()
                                          if "BeepingMouseArea" in item.metaObject().className())
                            click(cancel)
                            check("cancel never executes", event_log(), before)
                            check("cancel clears confirmation", component.property("pendingActionId"), "")
                            snapshot("departure-cancelled")
                            for prop, disabled, restored in (("busy", True, False), ("online", False, True)):
                                before = event_log()
                                click(button)
                                component.setProperty(prop, disabled)
                                settle()
                                check(prop + " clears confirmation", component.property("pendingActionId"), "")
                                click(button)
                                click(button)
                                check(prop + " blocks action", event_log(), before)
                                snapshot(prop)
                                component.setProperty(prop, restored)
                                settle()
                            alarm = named(component, "alarmMouse")
                            before = len(event_log())
                            click(alarm)
                            check("alarm emits once", event_log()[before:], [{"signal": "alarmRequested", "value": None}])
                        for scroller in list(walk(component)) + [area.findChild(QQuickItem, "detailScroll")]:
                            if scroller is not None and scroller.property("contentHeight") is not None:
                                overflow = float(scroller.property("contentHeight")) - scroller.height()
                                if overflow > 1:
                                    scroller.setProperty("contentY", overflow)
                                    settle()
                                    snapshot("scrolled-bottom")
                        case["events"] = event_log()
                    except (RuntimeError, AssertionError, TypeError, ValueError, AttributeError, StopIteration) as error:
                        case["issues"].append({"kind": "harness_or_load_error", "message": str(error)})
                    finally:
                        window.close()
                        window.deleteLater()
                        settle()
                        _item_wrappers = []
                        case["diagnostics"] = messages[start_messages:]
                        case["issues"].extend({"kind": "qml_diagnostic", **message} for message in case["diagnostics"])
    finally:
        qInstallMessageHandler(previous)
    for name, original in sources.items():
        path = args.qml_dir / (name + ".qml")
        if path.read_bytes() != original:
            report["issues"].append({"kind": "source_changed_during_run", "path": str(path)})
    report["diagnostics"] = messages
    report["issue_count"] = len(report["issues"]) + sum(len(case["issues"]) for case in report["cases"])
    report["passed"] = report["issue_count"] == 0
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qml-dir", type=Path, default=ROOT / "device_qml")
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts/display-2.5.0")
    parser.add_argument("--components", nargs="+", choices=COMPONENTS, default=list(COMPONENTS))
    parser.add_argument("--viewports", nargs="+", choices=VIEWPORTS, default=list(VIEWPORTS))
    parser.add_argument("--check", action="store_true", help="Exit nonzero for layout, interaction or QML failures")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.qml_dir = args.qml_dir.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    report = render(args)
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f'{len(report["cases"])} cases, {report["issue_count"]} issues; {args.output / "report.json"}')  # noqa: T201
    return int(args.check and not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
