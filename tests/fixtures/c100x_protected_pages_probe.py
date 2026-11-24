"""Real generated hook/bridge/alert guard with mocked vendor IO, no network."""

import json
import sys
from pathlib import Path

from c100x_memory_reply import MemoryReply
from PyQt5.QtCore import QObject, QUrl, pyqtProperty
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtNetwork import QNetworkAccessManager
from PyQt5.QtQml import (
    QQmlComponent,
    QQmlEngine,
    QQmlExpression,
    QQmlNetworkAccessManagerFactory,
)


class OfflineNetwork(QNetworkAccessManager):
    def createRequest(self, operation, request, outgoing=None):
        return MemoryReply(self, operation, request, {})


class OfflineFactory(QQmlNetworkAccessManagerFactory):
    def create(self, parent):
        return OfflineNetwork(parent)


class Enums(QObject):
    @pyqtProperty(int, constant=True)
    def Normal(self):
        return 1

    @pyqtProperty(int, constant=True)
    def ScreenOff(self):
        return 0

    @pyqtProperty(int, constant=True)
    def RingtoneMute(self):
        return 17

    @pyqtProperty(int, constant=True)
    def Commissioned(self):
        return 3


app = QGuiApplication([])
engine = QQmlEngine()
factory = OfflineFactory()
engine.setNetworkAccessManagerFactory(factory)
enums = Enums()
for name in ("AudioState", "ScreenState", "Commissioning"):
    engine.rootContext().setContextProperty(name, enums)
errors = []
engine.warnings.connect(lambda entries: errors.extend(error.toString() for error in entries
    if "Implicitly defined onFoo properties in Connections are deprecated" not in error.toString()))
source = Path(sys.argv[1])
document = Path(__file__).with_suffix(".qml").read_bytes().replace(
    b"@MAIN_HOOK@", (source / "hooks/main.inc").read_bytes().replace(b"@RELEASE@", b"."))
component = QQmlComponent(engine)
component.setData(document, QUrl.fromLocalFile(str(source / "ProtectedPages.qml")))
root = component.create()
assert root is not None, [error.toString() for error in component.errors()]


def evaluate(code):
    expression = QQmlExpression(QQmlEngine.contextForObject(root), root, code)
    result, undefined = expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    return result.toVariant() if hasattr(result, "toVariant") else result


serial = 0


def receive():
    global serial
    serial += 1
    now = evaluate("Date.now()")
    command = {"id": f"{serial:032x}", "revision": f"{serial:032x}", "notification_id": "test",
               "severity": "warning", "title": "Test", "message": "Test", "wake_duration": 10, "sound_duration": 0,
               "expires_in": 300, "remaining_ms": 5000, "expires": now + 5000, "message_expires": now + 300000}
    return evaluate(f"receive({json.dumps(command)})")


assert evaluate("c100xHost.pageStack === mainStackView"), "hook context did not resolve vendor stack"
assert evaluate("state().blocked"), "uninitialized vendor stack must block"
evaluate("showHome()")
assert evaluate("!c100xHost.alertsBlocked && !c100xAlerts.item.blocked")
assert receive()
assert evaluate("state().notice && state().clicks === 1")
evaluate("showVendor()")
assert evaluate("state().blocked && !state().notice && !state().coreBlocked")
clicks = evaluate("state().clicks")
assert not receive() and evaluate("state().clicks") == clicks
evaluate("showHome()")
assert evaluate("!state().blocked && !state().notice"), "protected notice must not resume"
evaluate("home.regulationState(true)")
assert evaluate("state().blocked && !state().coreBlocked")
assert not receive()
evaluate("home.regulationState(false)")
assert evaluate("!state().blocked")

for name, allowed in (("HomeAssistant.qml", True), ("Alarm.qml", False)):
    evaluate(f"showAdapter({json.dumps(name)})")
    assert evaluate("state().blocked") is not allowed, (name, evaluate("state()"))
    assert receive() is allowed, name
    evaluate("c100xAlerts.item.preempt()")
evaluate('showAdapter("HomeAssistant.qml")')
assert receive()
assert not errors, errors
evaluate('adapter.item.pageName = "unknown.qml"')
assert evaluate("state().blocked && !state().notice"), "unknown page failed open"
assert all("unknown.qml" in error for error in errors), errors
errors.clear()
evaluate("showHome(); mainStackView.currentItem = null")
assert evaluate("state().blocked")
evaluate("showHome(); vendorSettings.visible = true; mainStackView.currentItem = vendorSettings")
assert evaluate("state().blocked"), "unknown root page failed open at depth one"
evaluate("showHome()")
for guard in ("eventManager.callInProgress", "eventManager.callActive", "global.networkInfo.isSoftAp", "global.blockKeyboard"):
    evaluate(f"{guard} = true")
    assert evaluate("state().blocked && state().coreBlocked")
    assert not receive()
    evaluate(f"{guard} = false")
evaluate("global.commissioningStatus = 2")
assert evaluate("state().blocked")
evaluate("global.commissioningStatus = 3; c100xHost.pageStack = null")
assert evaluate("state().blocked && !state().coreBlocked")
assert not receive()
assert not errors, errors
sys.stdout.write("protected pages, unknown pages, regulation, guards and no deferred notices: passed\n")
