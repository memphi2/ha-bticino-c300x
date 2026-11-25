#!/usr/bin/env python3
"""Local Qt6-adapted smoke/layout checks, NOT Qt4 or hardware validation.

Run with an optional PySide6 interpreter::

    /path/to/qt-python scripts/check_display_layout.py --check

Only temporary copies receive QtQuick import and image substitutions. Vendor
text/mouse components and the detail host are mocks, following the standalone
energy harness pattern without importing its worker-owned implementation.
Reviewed Alerts Connections and mouse-handler declarations receive Qt6 syntax,
preserving their bodies.
No HA, device, network, firmware, or production-file writes are needed.
Alerts use context-injected JS XHR and a fail-closed network manager. Parent
call/page guards are simulated inputs, not proof of stock GUI integration.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ("C300XPageNavigation", "C300XAgenda", "C300XLeaveHome", "C300XDetailControl", "C300XAlerts", "C300XEnergy", "C300XSituations", "C300XOptionalPages")
VIEWPORTS = {"native": (800, 480, 748, 300), "short": (800, 480, 748, 230),
             "narrow": (480, 480, 428, 300)}
LONG = "Very long household label - garage, upstairs and garden equipment " * 3
ALERT_CONNECTIONS = """    Connections {
        target: global.screenState
        onStateChangedInt: root.screenChanged()
    }"""
ALERT_CONNECTIONS_QT6 = """    Connections {
        target: global.screenState
        function onStateChangedInt() { root.screenChanged() }
    }"""
OPTIONAL_CONNECTIONS = """    Connections {
        target: leaveHomeLoader.item
        onActionRequested: root.actionRequested(item)
        onAlarmRequested: root.alarmRequested()
    }"""
OPTIONAL_CONNECTIONS_QT6 = """    Connections {
        target: leaveHomeLoader.item
        function onActionRequested(item) { root.actionRequested(item) }
        function onAlarmRequested() { root.alarmRequested() }
    }"""
ALERT_MOUSE = """    MouseArea {
        anchors.fill: parent
        enabled: !!root.notice && !root.blocked
        onPressed: {
            root.userInteraction()
            mouse.accepted = false
        }
    }"""
ALERT_MOUSE_QT6 = ALERT_MOUSE.replace("onPressed: {", "onPressed: function(mouse) {")


def adapt_qml(source: str) -> str:
    """Adapt imports and reviewed Qt4 handler declarations, never their bodies."""
    source, count = re.subn(r"(?m)^import QtQuick 1\.1\s*$", "import QtQuick 2.15", source)
    if count != 1:
        raise ValueError("Expected exactly one QtQuick 1.1 import")
    if re.search(r"\bConnections\s*\{", source):
        reviewed = [(ALERT_CONNECTIONS, ALERT_CONNECTIONS_QT6), (OPTIONAL_CONNECTIONS, OPTIONAL_CONNECTIONS_QT6)]
        matches = [(old, new) for old, new in reviewed if source.count(old) == 1]
        if len(matches) != 1 or len(re.findall(r"\bConnections\s*\{", source)) != 1:
            raise ValueError("Unreviewed Connections handler: expected an exact reviewed block")
        source = source.replace(*matches[0], 1)
    if "mouse.accepted" in source:
        if source.count(ALERT_MOUSE) != 1:
            raise ValueError("Unreviewed mouse handler: expected the exact Alerts pass-through block")
        source = source.replace(ALERT_MOUSE, ALERT_MOUSE_QT6, 1)
    return re.sub(r"(?m)^import Components(?:\.Styles)? 1\.0\s*\n", "", source)


def mock_api_transport(source: str) -> str:
    """Inject only the shared script's XHR constructor, preserving queue logic."""
    if not source.startswith(".pragma library\n"):
        raise ValueError("Expected shared API script")
    return source.replace(".pragma library\n", ".pragma library\n"
                          "function XMLHttpRequest() { return new mockTransport.constructor() }\n", 1)


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
        # The favourites bar: the same component as one row of four buttons,
        # the third one marked as the current page.
        add(COMPONENTS[0], name + "-bar", bar=True, columns=4, current=11,
            links=[{"index": index, "title": label + " " + title}
                   for index, title in zip((7, 2, 11, -1),
                                          ("Home", "Energy", "Climate", "More"), strict=True)])
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
    for severity in ("info", "warning", "error"):
        for stress in (False, True):
            cases.append({"component": "C300XAlerts", "name": severity + ("-long" if stress else "-normal"),
                          "properties": {"acknowledgeLabel": "Acknowledge"},
                          "alert": {"severity": severity, "title": LONG[:80] if stress else "Household notification",
                                    "message": ("First line. " + LONG * 3)[:480] + " END OF MESSAGE" if stress else "Garage door is open."}})
    names = ["Durchlauferhitzer", "Wallbox", "Waermepumpe", "Backofen", "Waschmaschine",
             "Geschirrspueler", "Arbeitszimmer", "Kuehlschrank", "Netzwerk", "Standby"]
    colors = ["#f44336", "#009688", "#ff9800", "#9c27b0", "#2196f3",
              "#4caf50", "#e91e63", "#673ab7", "#00bcd4", "#607d8b"]
    normal = [22000, 11000, 2450, 1450, 620, 410, 210, 95, 62, 10]
    for scenario, values in {
        "consumers-normal": normal, "consumers-long": normal, "consumers-zero": [0] * 10,
        "consumers-unknown": [100, 20, 0, None, None], "consumers-identical": [15] * 10,
        "consumers-fractional": [0.9, 0.5, 0.4, 0.3, 0.25, 0.2, 0.1, 0.05, 0.01, 0.005],
        "consumers-extreme": [sys.float_info.max, 1.2345678901234567e200, 1e21, 999999999999999900000.0,
                              1e10, 1e-10, 1e-100, 1e-300, 5e-324, 0],
        "consumers-empty": [],
    }.items():
        items = [{"entity_id": f"sensor.consumer_{index:02}", "label": LONG if scenario == "consumers-long" else names[index],
                  "watts": value, "value": "--" if value is None else
                  (str(round(value)) if value < 1e21 else str(value)) + " W", "color": colors[index]}
                 for index, value in enumerate(values)]
        add("C300XEnergy", scenario, view="consumers", energy={
            "views": [{"id": key, "label": label} for key, label in
                      (("now", "Jetzt"), ("today", "Heute"), ("power", "Leistung"), ("consumers", "Verbraucher"), ("balance", "Bilanz"))],
            "consumers": {"items": list(reversed(items)), "unit": "W", "empty_text": "No available consumers",
                          "status": "Some consumers are unavailable" if scenario == "consumers-unknown" else ""}})
    for scenario, checks, empty in (
        ("normal", [{"name": "Kitchen window", "state_label": "Open", "color": "#ff6b6b"},
                    {"name": "Garage door", "state_label": "Unknown", "color": "#ffd166"}], ""),
        ("long", [{"name": LONG, "state_label": LONG, "color": "#ffd166"} for _ in range(24)], ""),
        ("clear", [], "No active issues in selected entities"),
        ("empty", [], "No entities selected"),
    ):
        payload = {"checks": checks, "empty_text": empty}
        add("C300XSituations", scenario, situations=payload)
        add("C300XOptionalPages", "situations-" + scenario, situations=payload, situationsVisible=True)
    add("C300XOptionalPages", "agenda", agendaVisible=True, agenda={"events": [], "empty_text": "No upcoming appointments"})
    add("C300XOptionalPages", "leave", leaveHomeVisible=True, leaveHome={"checks": [], "empty_text": "No checks configured"})
    add("C300XOptionalPages", "transitions", situationsVisible=True,
        situations={"checks": [{"name": "Window", "state_label": "Unknown", "color": "#ffd166"}]},
        agenda={"events": [], "empty_text": "No appointments"},
        leaveHome={"checks": [], "empty_text": "No checks configured", "actions": []},
        energy={"views": [{"id": "consumers", "label": "Consumers"}],
                "consumers": {"items": [], "empty_text": "No consumers"}})
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


MOCK_XHR = """
(function() {
    var requests = [], log = [], ackStatus = 200, ackBody = '{"ok":true}';
    function MockXHR() { this.readyState = 0; this.status = 0; this.responseText = ""; this.headers = {} }
    MockXHR.DONE = 4;
    MockXHR.prototype.open = function(method, url) { this.method = method; this.url = url; this.readyState = 1 };
    MockXHR.prototype.setRequestHeader = function(key, value) { this.headers[key] = value };
    MockXHR.prototype.send = function() {
        log.push({method: this.method, url: this.url, headers: this.headers}); requests.push(this);
        if (this.url.indexOf("/homeassistant?") >= 0 && ackStatus !== null) this.respond(ackStatus, ackBody);
    };
    MockXHR.prototype.abort = function() { this.aborted = true };
    MockXHR.prototype.respond = function(status, body) {
        this.status = status; this.responseText = body; this.readyState = 4;
        if (this.onreadystatechange) this.onreadystatechange();
    };
    function pending() {
        return requests.filter(function(r) { return !r.aborted && r.readyState !== 4 && r.url.indexOf("/ui/alerts/next") >= 0 });
    }
    return {constructor: MockXHR, log: log, pending: pending,
        ackResponse: function(status, body) { ackStatus = status; ackBody = JSON.stringify(body) },
        capture: function() { var r = pending()[0]; if (!r) throw new Error("No pending mock resident GET");
                              return {request: r, callback: r.onreadystatechange} },
        stale: function(saved, command) {
            saved.request.status = 200; saved.request.responseText = JSON.stringify(command); saved.request.readyState = 4;
            saved.callback();
        },
        deliver: function(command) {
            var r = pending()[0]; if (!r) throw new Error("No pending mock resident GET");
            r.respond(200, JSON.stringify(command)); return true;
        }};
})()
"""


ALERT_HOST = """
    property variant trsl: QtObject { property string language: "en" }
    property bool callActive: false
    property bool ringing: false
    property bool guiReady: true
    property string activePage: "home"
    property int underlyingClicks: 0
    property int wakeCalls: 0
    property int beepCalls: 0
    property int releaseCalls: 0
    property alias alertTarget: target
    property variant global: QtObject {
        property variant screenState: QtObject {
            property int state: 2
            property int screensaverInterval: 20000
            signal stateChangedInt(int oldState, int newState)
            function simulateClick() { frame.wakeCalls++ }
            function disableState(value) { frame.releaseCalls++ }
        }
        property variant audioState: QtObject {
            property int state: 0
            property bool audioAccess: false
            function isStateEnabled(value) { return true }
            function enableState(value) {}
            function disableState(value) {}
        }
        function beep() { frame.beepCalls++ }
    }
"""


def write_alert_mocks(directory):
    """Define only local vendor enum imports; production QML/JS stay intact."""
    for module, version, types in (
        ("BtClass", "1.0", {"ScreenState": "ScreenOff = 0, Freeze = 1, Normal = 2",
                            "AudioState": "Idle = 0, Beep = 1, Ringtone = 2, Call = 3, RingtoneMute = 4"}),
        ("BtObjects", "2.0", {"MockVendor": "Unused = 0"}),
    ):
        target = directory / module
        target.mkdir()
        (target / "qmldir").write_text(f"module {module}\n" + "".join(
            f"{name} {version} {name}.qml\n" for name in types))
        for name, enums in types.items():
            (target / (name + ".qml")).write_text(f"import QtQuick 2.15\nQtObject {{ enum Values {{ {enums} }} }}\n")


def frame_qml(fixture, viewport):
    width, height, content_width, content_height = viewport
    component = fixture["component"]
    props = "\n".join(f"{key}: ({json.dumps(value)})" for key, value in fixture["properties"].items())
    if component == "C300XAlerts":
        # Native alerts cover the screen; short/narrow variants additionally stress the panel.
        alert_width = width if width == 800 and content_height == 300 else content_width
        alert_height = height if width == 800 and content_height == 300 else content_height
        return f'''import QtQuick 2.15
Rectangle {{
    id: frame; width: {width}; height: {height}; color: "#123f65"
    {HOST}
    {ALERT_HOST}
    Item {{ objectName: "viewport"; anchors.centerIn: parent; width: {alert_width}; height: {alert_height}
        Rectangle {{ anchors.fill: parent; color: "#123f65"
            MouseArea {{ objectName: "underlying"; anchors.fill: parent; onClicked: frame.underlyingClicks++ }}
        }}
        C300XAlerts {{ id: target; objectName: "target"; anchors.fill: parent; z: 1000
            blocked: frame.callActive || frame.ringing || !frame.guiReady || (frame.activePage !== "home" && frame.activePage !== "ha")
            {props}
        }}
    }}
}}
'''
    handlers = {
        COMPONENTS[0]: 'onSelected: function(pageIndex) { frame.record("selected", pageIndex) }',
        COMPONENTS[1]: "",
        COMPONENTS[2]: 'onActionRequested: function(item) { frame.record("actionRequested", item.entity_id) }\n'
                       'onAlarmRequested: frame.record("alarmRequested", null)',
        COMPONENTS[3]: 'hostPage: frame\nonSubmitted: function(value) { frame.record("submitted", value) }\n'
                       'onAdjusted: function(direction) { frame.record("adjusted", direction) }\n'
                       'onRefreshRequested: frame.record("refreshRequested", null)',
        "C300XEnergy": "",
        "C300XSituations": "",
        "C300XOptionalPages": 'onActionRequested: function(item) { frame.record("actionRequested", item.entity_id) }\n'
                              'onAlarmRequested: frame.record("alarmRequested", null)',
    }
    target = f'{component} {{ id: target; objectName: "target"; width: {content_width}\n{props}\n{handlers[component]}\n'
    if component in COMPONENTS[1:3] or component in ("C300XEnergy", "C300XSituations", "C300XOptionalPages"):
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


@contextmanager
def animation_clock():
    """Keep Qt's real-time animation clock ticking even for static offscreen scenes."""
    from PySide6.QtCore import QVariantAnimation

    # QML Timers are pause animations. With no active animation, Qt can use an
    # 8000 ms CoarseTimer whose deadline is rounded by hundreds of milliseconds.
    # Keep normal animation ticks, without changing QML intervals or advancing
    # simulated time. This value is not connected to any visual item.
    clock = QVariantAnimation()
    clock.setStartValue(0.0)
    clock.setEndValue(1.0)
    clock.setDuration(1000)
    clock.setLoopCount(-1)
    clock.start()
    try:
        yield clock
    finally:
        clock.stop()


def render(args):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_QUICK_BACKEND"] = "software"
    os.environ["QT_SCALE_FACTOR"] = "1"
    from PySide6.QtCore import (
        QCoreApplication,
        QElapsedTimer,
        QEvent,
        QIODevice,
        QObject,
        QPointF,
        QRectF,
        Qt,
        QTimer,
        QUrl,
        qInstallMessageHandler,
        qVersion,
    )
    from PySide6.QtGui import QColor, QFontInfo, QGuiApplication, QImage
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply
    from PySide6.QtQml import QQmlEngine, QQmlNetworkAccessManagerFactory
    from PySide6.QtQuick import QQuickItem, QQuickView
    from PySide6.QtTest import QTest

    app = QGuiApplication.instance() or QGuiApplication([])

    class DeniedReply(QNetworkReply):
        def __init__(self, manager, operation, request):
            super().__init__(manager)
            self.setOperation(operation)
            self.setRequest(request)
            self.setUrl(request.url())
            self.open(QIODevice.ReadOnly)
            self.setError(QNetworkReply.ContentAccessDenied, "Offscreen verifier forbids network I/O")
            self.setFinished(True)
            QTimer.singleShot(0, self.finished.emit)

        def abort(self):
            pass

        def readData(self, _size):
            return b""

    class OfflineManager(QNetworkAccessManager):
        def __init__(self, parent, attempts):
            super().__init__(parent)
            self.attempts = attempts

        def createRequest(self, operation, request, outgoing=None):
            if request.url().scheme() not in ("file", "qrc", "data"):
                self.attempts.append(request.url().toString())
                return DeniedReply(self, operation, request)
            return super().createRequest(operation, request, outgoing)

    class OfflineFactory(QQmlNetworkAccessManagerFactory):
        def __init__(self, attempts):
            super().__init__()
            self.attempts = attempts

        def create(self, parent):
            return OfflineManager(parent, self.attempts)

    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(
        {"type": str(kind), "message": message, "file": context.file, "line": context.line}))
    selected_fixtures = [case for case in fixtures() if case["component"] in args.components
                         and (not args.scenarios or case["name"] in args.scenarios)]
    if not selected_fixtures:
        raise ValueError("No fixtures selected")
    sources = {name + ".qml": (args.qml_dir / (name + ".qml")).read_bytes() for name in args.components}
    if "C300XAlerts" in args.components:
        sources["js/c300x_alerts.js"] = (args.qml_dir / "js/c300x_alerts.js").read_bytes()
        sources["js/c300x_i18n.js"] = (args.qml_dir / "js/c300x_i18n.js").read_bytes()
        sources["js/c300x_ha.js"] = (args.qml_dir / "js/c300x_ha.js").read_bytes()
    source_paths = {name: args.qml_dir / name for name in sources}
    pending = list(sources.values())
    while pending:
        body = pending.pop().decode()
        dependencies = {name + ".qml" for name in re.findall(r"\b(C300X[A-Z]\w*)\b", body)}
        dependencies.update(re.findall(r'import "(js/c300x_energy\w*\.js)"', body))
        for name in sorted(dependencies - sources.keys()):
            candidate = args.qml_dir / name
            source_paths[name] = candidate if candidate.is_file() else ROOT / "device_qml" / name
            sources[name] = source_paths[name].read_bytes()
            pending.append(sources[name])
    report = {"scope": "Qt6 adaptation only; NOT Qt4/hardware validation", "qt": qVersion(),
              "renderer": "offscreen/software", "mocks": ["UbuntuLightText", "BeepingMouseArea", "button images", "detail hostPage"],
              "viewports": VIEWPORTS, "cases": [], "issues": [],
              "command": [sys.executable, *sys.argv],
              "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "adapted_files": {},
              "production_files": {str(source_paths[name]): hashlib.sha256(data).hexdigest()
                                   for name, data in sources.items()},
              "fixtures_sha256": hashlib.sha256(json.dumps(selected_fixtures, sort_keys=True).encode()).hexdigest()}
    report["network_policy"] = "Context mock XHR before construction; nonlocal QNAM requests denied before transport"
    if "C300XAlerts" in args.components:
        report["mocks"] += ["BtClass/ScreenState/AudioState enums", "global", "parent call/page guards", "resident XHR"]

    def settle(ms=30):
        app.processEvents()
        QTest.qWait(ms)
        app.processEvents()

    def wait_until(predicate, timeout):
        clock = QElapsedTimer()
        clock.start()
        while not predicate() and clock.elapsed() < timeout:
            settle(50)

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
        with animation_clock(), tempfile.TemporaryDirectory(prefix="c300x-display-layout-") as temp:
            directory = Path(temp)
            write_alert_mocks(directory)
            for name, data in sources.items():
                source = adapt_qml(data.decode()) if name.endswith(".qml") else data.decode()
                if name == "js/c300x_ha.js":
                    source = mock_api_transport(source)
                (args.output / "sources" / name).parent.mkdir(parents=True, exist_ok=True)
                (args.output / "sources" / name).write_bytes(data)
                for asset in set(re.findall(r'"(images/[^"\n]+\.svg)"', source)):
                    relative = str(Path(asset).with_suffix(".png"))
                    target = directory / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    picture = QImage(16, 16, QImage.Format_ARGB32)
                    picture.fill(QColor("#397ba3" if "_p.svg" in asset else "#24547b" if "list_btn" in asset else "#19476b"))
                    if not picture.save(str(target)):
                        raise RuntimeError(f"Cannot save mock image {target}")
                    source = source.replace(asset, relative)
                (directory / name).parent.mkdir(parents=True, exist_ok=True)
                (directory / name).write_text(source)
                report["adapted_files"][str(source_paths[name])] = hashlib.sha256(source.encode()).hexdigest()
            (directory / "UbuntuLightText.qml").write_text(
                'import QtQuick 2.15\nText { textFormat: Text.PlainText; font.family: "Ubuntu"; font.weight: Font.Light }\n')
            (directory / "BeepingMouseArea.qml").write_text('import QtQuick 2.15\nMouseArea {}\n')
            for index, (fixture, view) in enumerate(
                ((fixture, view) for fixture in selected_fixtures for view in args.viewports), start=1
            ):
                (directory / f"Frame{index}.qml").write_text(frame_qml(fixture, VIEWPORTS[view]))
            # Reuse the type registry: repeatedly destroying engines can leave
            # stale dynamic QQuickItem wrappers in PySide6's type cache.
            engine = QQmlEngine()
            network_attempts = []
            factory = OfflineFactory(network_attempts)
            engine.setNetworkAccessManagerFactory(factory)
            engine.addImportPath(str(directory))
            window = QQuickView(engine, None)
            for fixture in selected_fixtures:
                for viewport_name in args.viewports:
                    viewport = VIEWPORTS[viewport_name]
                    start_messages = len(messages)
                    case = {"component": fixture["component"], "fixture": fixture["name"], "viewport": viewport_name,
                            "snapshots": [], "checks": [], "issues": []}
                    report["cases"].append(case)
                    start_attempts = len(network_attempts)
                    if fixture["component"] == "C300XAlerts":
                        transport = engine.evaluate(MOCK_XHR)
                        if transport.isError():
                            raise RuntimeError(transport.toString())
                        engine.globalObject().setProperty("mockTransport", transport)
                        engine.rootContext().setContextProperty("XMLHttpRequest", transport.property("constructor"))
                    frame_path = directory / f"Frame{len(report['cases'])}.qml"
                    window.setSource(QUrl.fromLocalFile(str(frame_path)))
                    try:
                        if window.status() == QQuickView.Error:
                            raise RuntimeError("\n".join(error.toString() for error in window.errors()))
                        frame = window.rootObject()
                        component = frame.findChild(QQuickItem, "target")
                        area = frame.findChild(QQuickItem, "viewport")
                        window.show()
                        settle()
                        case["content_rect"] = [area.x(), area.y(), area.width(), area.height()]
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

                        def snapshot(state, expect_blank=False, area=area, engine=engine, enums=enums,
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
                            issues = layout_issues(texts, [0, 0, area.width(), area.height()])
                            shot = window.grabWindow()
                            filename = f'{fixture["component"]}-{fixture["name"]}-{viewport_name}-{state}.png'
                            path = args.output / filename
                            if shot.isNull() or not shot.save(str(path)):
                                raise RuntimeError(f"Screenshot failed: {path}")
                            origin = area.mapToScene(QPointF(0, 0))
                            crop = shot.copy(round(origin.x()), round(origin.y()), round(area.width()), round(area.height()))
                            colors = {crop.pixel(x, y) for x in range(0, crop.width(), 2) for y in range(0, crop.height(), 2)}
                            # Frame chrome cannot make a blank target pass; require text and actual white text pixels.
                            light_pixels = sum(crop.pixelColor(x, y).lightness() > 170
                                               for x in range(0, crop.width(), 2) for y in range(0, crop.height(), 2))
                            if expect_blank and (texts or light_pixels or len(colors) != 1):
                                issues.append({"kind": "unexpected_overlay"})
                            elif not expect_blank and (len(colors) < 3 or light_pixels < 5 or not texts):
                                issues.append({"kind": "blank_component"})
                            case["snapshots"].append({"state": state, "screenshot": str(path),
                                                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                                      "sampled_colors": len(colors), "light_pixels": light_pixels,
                                                      "texts": texts, "issues": issues})
                            case["issues"].extend({**issue, "state": state} for issue in issues)
                            return hashlib.sha256(path.read_bytes()).hexdigest()

                        initial_image = snapshot("initial", expect_blank=fixture["component"] == "C300XAlerts")
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
                        elif fixture["component"] == "C300XOptionalPages" and fixture["name"] == "transitions":
                            flags = ("energyVisible", "agendaVisible", "leaveHomeVisible", "situationsVisible")
                            for target in ("agendaVisible", "leaveHomeVisible", "energyVisible", "situationsVisible"):
                                for flag in flags:
                                    component.setProperty(flag, flag == target)
                                settle()
                                snapshot(target)
                                check(target + " never executes on opening", event_log(), [])
                            for flag in flags:
                                component.setProperty(flag, False)
                            settle()
                            snapshot("all-hidden", expect_blank=True)
                        elif fixture["component"] == "C300XEnergy":
                            consumers = named(component, "energyConsumers")
                            rows = [item for item in walk(consumers) if item.objectName() == "consumerRow"]
                            expected = sorted(fixture["properties"]["energy"]["consumers"]["items"],
                                              key=lambda item: (item["watts"] is None, -(item["watts"] or 0), item["entity_id"]))[:10]
                            check("ranked consumers count", len(rows), len(expected))
                            columns = [item for item in walk(consumers) if item.objectName() == "consumerColumn"]
                            check("five per column", [len([row for row in walk(col) if row.objectName() == "consumerRow"])
                                                      for col in columns], [min(5, len(expected)), max(0, len(expected) - 5)])
                            for index, (row, entry) in enumerate(zip(rows, expected, strict=True)):
                                row_data = row.property("consumer")
                                if hasattr(row_data, "toVariant"):
                                    row_data = row_data.toVariant()
                                check(f"consumer identity {index}", row_data["entity_id"], entry["entity_id"])
                                value = named(row, "consumerValue")
                                check(f"display watts {index}", value.property("text"), entry["value"])
                                check(f"raw watts {index}", row_data["watts"], entry["watts"])
                                check(f"display watts never elided {index}", bool(value.property("truncated")), False)
                                bar = named(row, "consumerBar")
                                positive = entry["watts"] is not None and entry["watts"] > 0
                                check(f"positive bar {index}", bar.isVisible() and bar.width() > 0, positive)
                                if not positive:
                                    check(f"empty unknown or zero bar {index}", bar.width(), 0)
                                elif bar.width() >= 2:
                                    point = bar.mapToScene(QPointF(bar.width() / 2, 2)).toPoint()
                                    check(f"entity bar pixels {index}", window.grabWindow().pixelColor(point).name(), entry["color"])
                            engine.globalObject().setProperty("consumerProbe", engine.newQObject(consumers))
                            # Query the Timer as QObject; it is deliberately not a visual item.
                            timer = consumers.findChild(QObject, "consumersShrink")
                            check("no idle timer", timer.property("running"), False)
                            before = [engine.evaluate(f"JSON.stringify(consumerProbe.{side}Scale)").toString() for side in ("left", "right")]
                            component.setProperty("energy", copy.deepcopy(fixture["properties"]["energy"]))
                            settle()
                            check("identical refresh keeps scales", [engine.evaluate(f"JSON.stringify(consumerProbe.{side}Scale)").toString()
                                                                     for side in ("left", "right")], before)
                            check("identical refresh stays idle", timer.property("running"), False)
                            if fixture["name"] == "consumers-normal":
                                check("independent column scales", before[0] != before[1], True)
                            if fixture["name"] == "consumers-normal" and viewport_name == "native":
                                smaller = copy.deepcopy(fixture["properties"]["energy"])
                                for entry in smaller["consumers"]["items"]:
                                    entry["watts"] /= 1000
                                    entry["value"] = str(entry["watts"]) + " W"
                                component.setProperty("energy", smaller)
                                settle()
                                check("scale shrink scheduled", timer.property("running"), True)
                                old_high = json.loads(before[0])["high"]
                                check("scale does not immediately shrink", engine.evaluate("consumerProbe.leftScale.high").toNumber(), old_high)
                                wait_until(lambda timer=timer: not timer.property("running"), 15000)
                                check("delayed scale shrink", engine.evaluate("consumerProbe.leftScale.high").toNumber() < old_high, True)
                                check("no repeating shrink poll", timer.property("running"), False)
                                snapshot("scale-shrunk")
                            component.setProperty("view", "balance")
                            settle()
                            check("consumers unload on tab switch", any(item.objectName() == "energyConsumers" for item in walk(component)), False)
                            component.setProperty("view", "consumers")
                            settle()
                            component.setProperty("visible", False)
                            settle()
                            check("consumers unload when hidden", any(item.objectName() == "energyConsumers" for item in walk(component)), False)
                            component.setProperty("visible", True)
                            settle()
                        elif fixture["component"] == "C300XAlerts":
                            def js(expression, engine=engine):
                                value = engine.evaluate(expression)
                                if value.isError():
                                    raise RuntimeError(value.toString())
                                return value.toVariant()

                            def deliver(serial, stale=False, fixture=fixture, js=js):
                                command = {**fixture["alert"], "id": f"{serial:032x}", "notification_id": "smoke-alert",
                                           "revision": f"{serial:032x}", "wake_duration": 0, "sound_duration": 0,
                                           "expires_in": 60, "remaining_ms": 5000}
                                js("var command = " + json.dumps(command) + "; command.expires = Date.now() + 5000; "
                                   "command.message_expires = Date.now() + 60000; " +
                                   ("mockTransport.stale(savedPoll, command)" if stale else "mockTransport.deliver(command)"))
                                settle()

                            check("controller constructed", js("probe.alertTarget.canListen()"), True)
                            check("mock resident GET before construction completes", js("mockTransport.log"), [
                                {"method": "GET", "url": "http://127.0.0.1:8090/ui/alerts/next",
                                 "headers": {"X-C300X-GUI": "alerts-v1"}}])
                            panel = named(component, "panel")
                            scroll = named(component, "messageScroll")
                            ack = named(component, "acknowledgeMouse")
                            deliver(1)
                            check("alert shown", panel.isVisible(), True)
                            snapshot("severity-" + fixture["alert"]["severity"])
                            severity = fixture["alert"]["severity"]
                            label, accent = {"info": ("i  Info", "#68baff"), "warning": ("!  Warning", "#f1c40f"),
                                             "error": ("!  Error", "#ff6b6b")}[severity]
                            check("severity symbol and label", named(component, "severityLabel").property("text"), label)
                            check("acknowledgement label", any(text["text"] == fixture["properties"]["acknowledgeLabel"]
                                                              for text in case["snapshots"][-1]["texts"]), True)
                            # The look of the station's own popups: a sheet of half
                            # transparent white on 90 % black, which gives mid grey.
                            sheet = named(component, "sheet")
                            check("station popup sheet", [sheet.property("color").name(), sheet.property("opacity")],
                                  ["#ffffff", 0.5])
                            check("severity accent", component.property("accent").name(), accent)
                            shot = window.grabWindow()
                            grey = shot.pixelColor(panel.mapToScene(QPointF(5, 5)).toPoint())
                            check("grey panel pixels", 110 <= grey.red() <= 150 and
                                  max(grey.red(), grey.green(), grey.blue()) - min(grey.red(), grey.green(), grey.blue()) < 12, True)
                            # Severity is a small coloured marker; the box and its text keep their colours.
                            severity_item = named(component, "severityMark")
                            origin = severity_item.mapToScene(QPointF(0, 0)).toPoint()
                            colored = sum(shot.pixelColor(origin.x() + x, origin.y() + y).name() == accent
                                          for x in range(round(severity_item.width())) for y in range(round(severity_item.height())))
                            check("severity marker pixels", colored > 5, True)
                            check("severity marker stays small", severity_item.width() * severity_item.height() <= 200, True)
                            check("severity text is white", named(component, "severityLabel").property("color").name(), "#ffffff")
                            if fixture["name"].endswith("-long"):
                                check("long message scrollable", scroll.property("contentHeight") > scroll.height(), True)
                                first_image = snapshot("long-top")
                                start = scroll.mapToScene(QPointF(scroll.width() / 2, scroll.height() - 5)).toPoint()
                                end = scroll.mapToScene(QPointF(scroll.width() / 2, min(5, scroll.height() - 90))).toPoint()
                                QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
                                for step in range(1, 11):
                                    point = start + (end - start) * (step / 10)
                                    QTest.mouseMove(window, point, 15)
                                QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
                                settle(80)
                                check("long message drag moves", float(scroll.property("contentY")) > 0, True)
                                scroll.setProperty("contentY", float(scroll.property("contentHeight")) - scroll.height())
                                settle()
                                check("long message bottom pixels change", snapshot("long-bottom") != first_image, True)
                            check("message touches do not click underlying", frame.property("underlyingClicks"), 0)
                            click(ack)
                            check("ack hides overlay", panel.isVisible(), False)
                            check("ack touch never clicks underlying", frame.property("underlyingClicks"), 0)
                            check("ack screen refresh", frame.property("wakeCalls"), 1)
                            check("ack never disables screen", frame.property("releaseCalls"), 0)
                            check("silent alert never beeps", frame.property("beepCalls"), 0)
                            snapshot("acknowledged", expect_blank=True)
                            requests = js("mockTransport.log")
                            acknowledgements = [request for request in requests if "/homeassistant?" in request["url"]]
                            check("one acknowledgement request", len(acknowledgements), 1)
                            if acknowledgements:
                                query = parse_qs(urlsplit(acknowledgements[0]["url"]).query)
                                check("ack request target", {key: query.get(key) for key in ("domain", "service", "entities")},
                                      {"domain": ["c300x"], "service": ["toggle"], "entities": ["notification.smoke-alert"]})
                                check("ack request revision", json.loads(query["option"][0]), {"revision": f"{1:032x}", "action_id": None})
                            click(named(area, "underlying"))
                            check("underlying sentinel really works", frame.property("underlyingClicks"), 1)
                            # Protected roots retain only a presence GET; stale safe callbacks cannot deliver.
                            for serial, (prop, value, restore) in enumerate((
                                ("callActive", True, False), ("ringing", True, False), ("guiReady", False, True),
                                ("activePage", "alarm", "home"), ("activePage", "settings", "home"),
                                ("visible", False, True)), start=2):
                                deliver(serial * 2)
                                check(f"{prop}-{value} starts visible", panel.isVisible(), True)
                                js("var savedPoll = mockTransport.capture()")
                                guard_target = component if prop == "visible" else frame
                                guard_target.setProperty(prop, value)
                                settle(125)
                                check(f"{prop}-{value} blocked", js("probe.alertTarget.canListen()"), False)
                                check(f"{prop}-{value} connected", js("probe.alertTarget.canConnect()"), True)
                                check(f"{prop}-{value} preempts", panel.isVisible(), False)
                                check(f"{prop}-{value} aborts poll", js("savedPoll.request.aborted === true"), True)
                                check(f"{prop}-{value} one protected poll", js("mockTransport.pending().map(function(r) { "
                                      "return {method: r.method, url: r.url, headers: r.headers} })"), [
                                    {"method": "GET", "url": "http://127.0.0.1:8090/ui/alerts/next?protected=1",
                                     "headers": {"X-C300X-GUI": "alerts-v1"}}])
                                js("var protectedPoll = mockTransport.pending()[0]")
                                deliver(serial * 2 + 1, stale=True)
                                snapshot(f"blocked-{prop}-{value}", expect_blank=True)
                                check(f"{prop}-{value} suppresses incoming", panel.isVisible(), False)
                                check(f"{prop}-{value} stale preserves protected poll", js("mockTransport.pending()[0] === protectedPoll"), True)
                                guard_target.setProperty(prop, restore)
                                settle(125)
                                wait_until(lambda: js("mockTransport.pending().length") == 1, 1000)
                                check(f"{prop}-{value} resumes once", js("mockTransport.pending().length"), 1)
                                check(f"{prop}-{value} aborts protected poll", js("protectedPoll.aborted === true"), True)
                                check(f"{prop}-{value} restores safe URL", js("mockTransport.pending()[0].url"),
                                      "http://127.0.0.1:8090/ui/alerts/next")
                                js("var resumedPoll = mockTransport.pending()[0]")
                                deliver(serial * 2 + 1, stale=True)
                                check(f"{prop}-{value} stale preserves resumed poll", js("mockTransport.pending()[0] === resumedPoll"), True)
                                check(f"{prop}-{value} never replays", panel.isVisible(), False)
                            case["mock_requests"] = js("mockTransport.log")
                        scrollers = [] if fixture["component"] == "C300XAlerts" else list(walk(component)) + [area.findChild(QQuickItem, "detailScroll")]
                        for scroller in scrollers:
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
                        window.setSource(QUrl())
                        settle()
                        _item_wrappers = []
                        attempts = network_attempts[start_attempts:]
                        case["network_attempts"] = attempts
                        case["issues"].extend({"kind": "network_denied", "url": url} for url in attempts)
                        case["diagnostics"] = messages[start_messages:]
                        case["issues"].extend({"kind": "qml_diagnostic", **message} for message in case["diagnostics"])
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    finally:
        qInstallMessageHandler(previous)
    for name, original in sources.items():
        path = source_paths[name]
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
    parser.add_argument("--scenarios", nargs="+", help="Optional fixture names for focused regression probes")
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
