"""Host Qt5 alert IO/focus test; all XHRs are intercepted, never sent to a host."""

import json
from pathlib import Path
import sys

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtNetwork import QNetworkAccessManager
from PyQt5.QtQml import QQmlComponent, QQmlEngine, QQmlExpression, QQmlNetworkAccessManagerFactory
from PyQt5.QtQuick import QQuickView
from PyQt5.QtTest import QTest
from c100x_memory_reply import MemoryReply

pending = []
requests = []
ack_ok = False
replies = []


class OfflineNetwork(QNetworkAccessManager):
    def createRequest(self, operation, request, outgoing=None):
        url = request.url().toString()
        requests.append(url)
        reply = {}
        if "/ui/alerts/next" in url and pending:
            reply = pending.pop(0)
        if "/homeassistant?" in url:
            reply = {"ok": ack_ok}
        response = MemoryReply(self, operation, request, reply)
        replies.append(response)
        return response


class OfflineFactory(QQmlNetworkAccessManagerFactory):
    def create(self, parent):
        return OfflineNetwork(parent)


app = QGuiApplication([])
engine = QQmlEngine()
factory = OfflineFactory()
engine.setNetworkAccessManagerFactory(factory)
errors = []
engine.warnings.connect(lambda entries: errors.extend(error.toString() for error in entries
    if "Implicitly defined onFoo properties in Connections are deprecated" not in error.toString()))
source, output = map(Path, sys.argv[1:3])
component = QQmlComponent(engine)
url = QUrl.fromLocalFile(str(source / "AlertProbe.qml"))
component.setData(Path(__file__).with_suffix(".qml").read_bytes(), url)
root = component.create()
assert root is not None, [error.toString() for error in component.errors()]
view = QQuickView(engine, None)
view.resize(800, 480)
view.setContent(url, component, root)
host = root.property("c100xHost")
host.setProperty("focusWindow", view)
view.show()
assert QTest.qWaitForWindowExposed(view)


def evaluate(code):
    expression = QQmlExpression(QQmlEngine.contextForObject(root), root, code)
    result, undefined = expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    return result.toVariant() if hasattr(result, "toVariant") else result


serial = 0


def command(wake=1, sound=0):
    global serial
    serial += 1
    now = evaluate("new Date().getTime()")
    return {"id": f"{serial:032x}", "revision": f"{serial:032x}", "notification_id": "test",
            "severity": "warning", "title": "Notification with a longer title for the native display",
            "message": "A long message requires physical-key scrolling. " * 10,
            "wake_duration": wake, "sound_duration": sound, "expires_in": 300, "remaining_ms": 5000,
            "expires": now + 5000, "message_expires": now + 300000}


def receive(wake=1):
    evaluate("resume()")
    assert evaluate(f"receive({json.dumps(command(wake))})")
    QTest.qWait(20)


QTest.qWait(30)
assert evaluate("alerts.screenReady && !alerts.blocked")
receive()
assert evaluate("screen.state === 1 && screen.clicks === 1")
assert view.activeFocusItem().metaObject().className().startswith("C100XAlertKeys")
evaluate("for (var i = 0; i < 4; i++) alerts.tick()")
assert evaluate("screen.state === 0 && screen.releases === 1"), "owned wake did not expire"
evaluate("alerts.preempt()")
assert view.activeFocusItem().objectName() == "vendorFocus"

receive(10)
QTest.keyClick(view, Qt.Key_Down)
assert evaluate('alerts.children[0].scroll.contentY > 0'), "message is not key-scrollable"
for _ in range(30):
    QTest.keyClick(view, Qt.Key_Down)
assert evaluate('alerts.children[0].scroll.contentY <= alerts.children[0].scroll.contentHeight - alerts.children[0].scroll.height')
for _ in range(30):
    QTest.keyClick(view, Qt.Key_Up)
assert evaluate('alerts.children[0].scroll.contentY === 0')
reserved = [Qt.Key_C, Qt.Key_H, *range(Qt.Key_1, Qt.Key_8 + 1)]
for key in reserved:
    QTest.keyClick(view, key)
assert evaluate("vendorKeys") == reserved

output.mkdir()
capture = root.grabToImage()
QTest.qWait(100)
image = capture.image()
assert not image.isNull() and image.save(str(output / "notify.png"))
assert len({image.pixel(x, y) for x in range(30, 770, 4) for y in range(50, 430, 4)}) > 3

QTest.keyClick(view, Qt.Key_Return)
QTest.qWait(100)
assert evaluate("alerts.ackFailed && !!alerts.notice && !alerts.acknowledging")
ack_ok = True
QTest.keyClick(view, Qt.Key_Return)
QTest.qWait(100)
assert evaluate("alerts.notice === null && !alerts.acknowledging")
assert view.activeFocusItem().objectName() == "vendorFocus"
assert len([url for url in requests if "/homeassistant?" in url]) == 2

receive()
releases = evaluate("screen.releases")
evaluate("startCall(); alerts.tick()")
assert evaluate("alerts.notice === null && screen.state === 2")
assert evaluate("screen.releases") == releases, "call-owned screen must not be released"
assert view.activeFocusItem().objectName() == "callFocus", "preemption stole call focus"

evaluate("resume(); screen.transition(0)")
receive(1)
QTest.keyClick(view, Qt.Key_Down)
evaluate("for (var i = 0; i < 5; i++) alerts.tick()")
assert evaluate("screen.state === 1"), "user-owned wake must not be released"
evaluate("alerts.preempt()")

# Exercise the real XHR callback. Unsupported sound is rejected, not silently
# reported as successful, and the same transport still accepts silent alerts.
pending.append(command(sound=1))
evaluate("poll()")
QTest.qWait(100)
assert not pending and evaluate("alerts.notice === null")
pending.append(command(sound=0))
evaluate("poll()")
QTest.qWait(100)
assert not pending and evaluate("!!alerts.notice")
evaluate("startCall()")
assert evaluate("alerts.notice === null && !alerts.soundReady()")
view.close()
assert not errors, errors
print(json.dumps({"requests_intercepted": len(requests), "reserved_keys": len(reserved), "errors": errors}))
