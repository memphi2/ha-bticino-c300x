"""Render the real C100X adapter at stock logical size; never contact a service."""

import json
import sys
from pathlib import Path

from PyQt5 import sip
from PyQt5.QtCore import QObject, QRectF, Qt, QUrl, pyqtProperty, pyqtSlot
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtQml import (
    QQmlComponent,
    QQmlEngine,
    QQmlExpression,
    QQmlNetworkAccessManagerFactory,
)
from PyQt5.QtQuick import QQuickView
from PyQt5.QtTest import QTest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from check_display_layout import HOST, fixtures, intersection, layout_issues  # noqa: E402
from check_energy_layout import make_fixtures  # noqa: E402


class OfflineNetwork(QNetworkAccessManager):
    def createRequest(self, operation, request, outgoing=None):
        return super().createRequest(self.GetOperation, QNetworkRequest(QUrl("data:application/json,{}")))


class OfflineFactory(QQmlNetworkAccessManagerFactory):
    def create(self, parent):
        return OfflineNetwork(parent)


class Host(QObject):
    @pyqtProperty(bool, constant=True)
    def blocked(self):
        return False

    @pyqtProperty(str, constant=True)
    def language(self):
        return "en"

    @pyqtProperty(QObject, constant=True)
    def preferences(self):
        return self

    @pyqtProperty(bool, constant=True)
    def feedbackEnabled(self):
        return True

    @pyqtSlot()
    def load(self):
        pass


app = QGuiApplication([])
engine = QQmlEngine()
factory = OfflineFactory()
engine.setNetworkAccessManagerFactory(factory)
host = Host()
engine.rootContext().setContextProperty("c100xHost", host)
warnings = []
engine.warnings.connect(lambda entries: warnings.extend(error.toString() for error in entries
    if "Implicitly defined onFoo properties in Connections are deprecated" not in error.toString()))
source, output = map(Path, sys.argv[1:3])
output.mkdir(parents=True, exist_ok=True)


def evaluate(item, code):
    expression = QQmlExpression(engine.rootContext(), item, code)
    value, undefined = expression.evaluate()
    if expression.hasError():
        raise AssertionError(expression.error().toString())
    return value.toVariant() if hasattr(value, "toVariant") else value


def rectangle(value):
    return [value.x(), value.y(), value.width(), value.height()]


def inspect(root):
    texts = []

    def visit(node, clips, path):
        if not node.isVisible() or node.opacity() == 0:
            return
        box = rectangle(node.mapRectToItem(root, QRectF(0, 0, node.width(), node.height())))
        if node.clip():
            clips = [*clips, box]
        value = node.property("text")
        if isinstance(value, str) and value:
            width = float(node.property("contentWidth") or node.property("paintedWidth") or 0)
            height = float(node.property("contentHeight") or node.property("paintedHeight") or 0)
            alignment = evaluate(node, "({a: horizontalAlignment, v: verticalAlignment})")
            x = node.width() - width if alignment["a"] == 2 else (node.width() - width) / 2 if alignment["a"] == 4 else 0
            y = node.height() - height if alignment["v"] == 64 else (node.height() - height) / 2 if alignment["v"] == 128 else 0
            raw = rectangle(node.mapRectToItem(root, QRectF(x, y, width, height)))
            ink = raw
            for clip in clips:
                ink = intersection(ink, clip)
            if min(ink[2:]) > 0:
                texts.append({"id": path, "text": value, "box": box, "raw_ink": raw, "ink": ink})
        for index, child in enumerate(node.childItems()):
            visit(child, clips, f"{path}/{index}")

    visit(root, [[0, 0, 800, 480]], "page")
    return texts, layout_issues(texts, [0, 0, 800, 480])


cases = [case for case in fixtures() if case["component"] != "C300XAlerts"]
for energy in make_fixtures(include_consumers=True):
    for view in ("now", "today", "power", "consumers", "balance"):
        cases.append({"component": "C300XEnergy", "name": f'{energy["language"]}-{energy["name"]}-{view}',
                      "properties": {"energy": energy["energy"], "view": view}})
report = {"scope": "host Qt5 adapter at 800x480; not firmware/hardware proof", "cases": [], "issues": []}
for case in cases:
    name = case["component"]
    props = "\n".join(f"{key}: ({json.dumps(value)})" for key, value in case["properties"].items())
    handlers = ""
    if name == "C300XDetailControl":
        handlers = "hostPage: frame; onSubmitted: frame.record('submitted', value); onAdjusted: frame.record('adjusted', direction)"
    target = f'{name} {{ id: target; objectName: "target"; width: 748; {props}\n{handlers}\n'
    if name != "C300XDetailControl" and name != "C300XPageNavigation":
        target += "height: 380\n"
    target += "}"
    if name == "C300XDetailControl":
        target = 'C100XScroll { width: 748; height: 380; clip: true; contentHeight: target.height; ' + target + ' }'
    document = f'''import QtQuick 2.7
FocusScope {{ id: frame; width: 800; height: 480; focus: true; {HOST}
    property var vendorKeys: []
    Keys.onPressed: {{ vendorKeys = vendorKeys.concat([event.key]); event.accepted = true }}
    function actionCount() {{ var a=[]; page.actions(page,a); return a.length }}
    function selectedIndex() {{ var a=[]; page.actions(page,a); return a.indexOf(page.selectedAction) }}
    C100XPage {{ id: page; anchors.fill: parent; focus: true; headerLabel: "{name}"
        Item {{ x: 26; y: 70; width: 748; height: 380; {target} }}
    }}
}}
'''
    component = QQmlComponent(engine)
    url = QUrl.fromLocalFile(str(source / "VisualProbe.qml"))
    component.setData(document.encode(), url)
    item = component.create()
    if item is None:
        raise AssertionError([error.toString() for error in component.errors()])
    view = QQuickView(engine, None)
    view.resize(800, 480)
    view.setContent(url, component, item)
    view.show()
    item.forceActiveFocus()
    assert QTest.qWaitForWindowExposed(view)
    QTest.qWait(50)
    texts, issues = inspect(item)
    shot = view.grabWindow()
    if shot.isNull():
        capture = item.grabToImage()
        for _ in range(20):
            QTest.qWait(20)
            shot = capture.image()
            if not shot.isNull():
                break
    filename = f'{name}-{case["name"]}.png'
    assert not shot.isNull() and shot.save(str(output / filename))
    colors = {shot.pixel(x, y) for x in range(26, 774, 4) for y in range(70, 450, 4)}
    if len(colors) < 3:
        issues.append({"kind": "blank_content"})
    total = evaluate(item, "actionCount()")
    # Actual key events, not just direct calls to the navigation helper.
    reached = set()
    for _ in range(total + 1):
        QTest.keyClick(view, Qt.Key_Down)
        reached.add(evaluate(item, "selectedIndex()"))
    if reached != set(range(total)):
        issues.append({"kind": "unreachable_actions", "expected": total, "reached": sorted(reached)})
    if evaluate(item, "vendorKeys.length") != 0:
        issues.append({"kind": "navigation_key_escaped"})
    reserved = [Qt.Key_C, Qt.Key_H, *range(Qt.Key_1, Qt.Key_8 + 1)]
    for key in reserved:
        QTest.keyClick(view, key)
    if evaluate(item, "vendorKeys") != reserved:
        issues.append({"kind": "vendor_key_swallowed"})
    report["cases"].append({"component": name, "scenario": case["name"], "screenshot": filename,
                            "texts": len(texts), "actions": total, "issues": issues})
    report["issues"].extend({"case": filename, **issue} for issue in issues)
    view.close()
    sip.delete(view)
    app.processEvents()
report["warnings"] = warnings
(output / "report.json").write_text(json.dumps(report, indent=2))
sys.stdout.write(json.dumps({"cases": len(cases), "issues": report["issues"], "warnings": warnings}, indent=2) + "\n")
sys.exit(bool(report["issues"] or warnings))
