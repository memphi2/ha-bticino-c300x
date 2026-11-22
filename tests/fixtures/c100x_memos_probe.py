"""Real generated memo UI and GET transport, with an in-memory backend only."""

import json
import sys
from pathlib import Path

from c100x_memory_reply import MemoryReply
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtNetwork import QNetworkAccessManager
from PyQt5.QtQml import (
    QQmlComponent,
    QQmlEngine,
    QQmlExpression,
    QQmlNetworkAccessManagerFactory,
)
from PyQt5.QtQuick import QQuickView
from PyQt5.QtTest import QTest

entries = [{"id": f"text/memo_{index}", "kind": "text", "has_text": True,
            "text": ("<b>plain text</b> &\n" * 30)[:512],
            "date": "22/11/2026 20:00", "read": False, "text_truncated": False} for index in range(1, 65)]
requests, replies, errors = [], [], []


class OfflineNetwork(QNetworkAccessManager):
    def createRequest(self, operation, request, outgoing=None):
        requests.append((operation, request.url().toString()))
        reply = MemoryReply(self, operation, request, {"ok": True, "available": True, "memos": entries})
        replies.append(reply)
        return reply


class OfflineFactory(QQmlNetworkAccessManagerFactory):
    def create(self, parent):
        return OfflineNetwork(parent)


app = QGuiApplication([])
engine = QQmlEngine()
factory = OfflineFactory()
engine.setNetworkAccessManagerFactory(factory)
engine.warnings.connect(lambda values: errors.extend(value.toString() for value in values
    if "Implicitly defined onFoo properties in Connections are deprecated" not in value.toString()))
source, output = map(Path, sys.argv[1:3])
component = QQmlComponent(engine)
url = QUrl.fromLocalFile(str(source / "MemoProbe.qml"))
component.setData(b'''import QtQuick 2.7
FocusScope {
    id: frame
    width: 800; height: 480; focus: true
    property QtObject c100xHost: QtObject { property bool blocked: false; property string language: "de" }
    property alias memo: memo
    property var vendorKeys: []
    Keys.onPressed: { vendorKeys = vendorKeys.concat([event.key]); event.accepted = true }
    C100XMemos { id: memo; anchors.fill: parent; focus: true }
    function selectLast() { memo.resetInput(); for (var i = 0; i < 67; i++) memo.move(1) }
}''', url)
root = component.create()
assert root is not None, [error.toString() for error in component.errors()]
view = QQuickView(engine, None)
view.resize(800, 480)
view.setContent(url, component, root)
view.show()
assert QTest.qWaitForWindowExposed(view)


def evaluate(code):
    expression = QQmlExpression(QQmlEngine.contextForObject(root), root, code)
    result, undefined = expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    return result.toVariant() if hasattr(result, "toVariant") else result


QTest.qWait(100)
assert evaluate("memo.entries.length === 64 && !memo.failed && !memo.busy")
# Back, refresh, scroll frame, then 64 entry actions. Last entry must be revealed.
for _ in range(67):
    QTest.keyClick(view, Qt.Key_Down)
QTest.keyClick(view, Qt.Key_Return)
assert evaluate('memo.selectedMemo.id === "text/memo_64"')
assert evaluate("memo.selectedMemo.text.indexOf('<b>plain text</b>') >= 0")
QTest.qWait(50)
for _ in range(3):
    QTest.keyClick(view, Qt.Key_Down)
QTest.keyClick(view, Qt.Key_Return)
QTest.keyClick(view, Qt.Key_Down)
assert evaluate('memo.selectedAction.keyboardEditing && memo.selectedAction.contentY > 0'), evaluate(
    '(function(){var a=[]; memo.actions(memo,a); return a.map(function(i){return {name:i.objectName, h:i.height, ch:i.contentHeight, y:i.contentY, edit:i.keyboardEditing}})})()')
output.mkdir()
capture = root.grabToImage()
QTest.qWait(80)
image = capture.image()
assert not image.isNull() and image.save(str(output / "memo.png"))
assert len({image.pixel(x, y) for x in range(24, 775, 4) for y in range(110, 450, 4)}) > 3
QTest.keyClick(view, Qt.Key_Escape)
assert evaluate("!!memo.selectedMemo && !memo.selectedAction.keyboardEditing")
QTest.keyClick(view, Qt.Key_Escape)
assert evaluate("memo.selectedMemo === null")
reserved = [Qt.Key_C, Qt.Key_H, *range(Qt.Key_1, Qt.Key_8 + 1)]
for key in reserved:
    QTest.keyClick(view, key)
assert evaluate("vendorKeys") == reserved
evaluate("c100xHost.blocked = true")
assert evaluate("memo.entries.length === 0 && !memo.busy && memo.selectedMemo === null")
assert requests == [(QNetworkAccessManager.GetOperation, "http://127.0.0.1:8090/ui/memos")]
view.close()
assert not errors, errors
sys.stdout.write(json.dumps({"text_entries": 64, "requests": len(requests), "errors": errors}) + "\n")
