"""Drive real generated controls using the original keymap, with offline IO."""

import json
import sys
from pathlib import Path

from c100x_memory_reply import MemoryReply
from c100x_probe_vendor import provide
from PyQt5.QtCore import QEvent, Qt, QUrl
from PyQt5.QtGui import QGuiApplication, QKeyEvent
from PyQt5.QtNetwork import QNetworkAccessManager
from PyQt5.QtQml import (
    QQmlComponent,
    QQmlEngine,
    QQmlExpression,
    QQmlNetworkAccessManagerFactory,
)
from PyQt5.QtQuick import QQuickView
from PyQt5.QtTest import QTest


class OfflineNetwork(QNetworkAccessManager):
    def createRequest(self, operation, request, outgoing=None):
        return MemoryReply(self, operation, request, {})


class OfflineFactory(QQmlNetworkAccessManagerFactory):
    def create(self, parent):
        return OfflineNetwork(parent)


source = Path(sys.argv[1])
keys = json.loads(sys.argv[2])
assert all(key in keys for key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Return))
assert Qt.Key_Back not in keys and Qt.Key_Escape not in keys
app = QGuiApplication([])
engine = QQmlEngine()
vendor = provide(engine, source)
factory = OfflineFactory()
engine.setNetworkAccessManagerFactory(factory)
errors = []
engine.warnings.connect(lambda entries: errors.extend(error.toString() for error in entries
    if "Implicitly defined onFoo properties in Connections are deprecated" not in error.toString()))
component = QQmlComponent(engine)
url = QUrl.fromLocalFile(str(source / "NumericKeys.qml"))
component.setData(Path(__file__).with_suffix(".qml").read_bytes(), url)
root = component.create()
assert root is not None, [error.toString() for error in component.errors()]
view = QQuickView(engine, None)
view.setContent(url, component, root)
view.resize(800, 480)
view.show()
assert QTest.qWaitForWindowExposed(view)


def evaluate(code):
    expression = QQmlExpression(QQmlEngine.contextForObject(root), root, code)
    result, undefined = expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    return result.toVariant() if hasattr(result, "toVariant") else result


def press(key):
    assert key in keys
    app.sendEvent(view, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
    app.sendEvent(view, QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))


def repeat_return():
    app.sendEvent(view, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "", True, 1))


evaluate("selectSlider()")
press(Qt.Key_Return)
press(Qt.Key_Down)
assert evaluate("state().preview === 22 && state().editing && submissions === 0")
repeat_return()
assert evaluate("state().editing && submissions === 0"), "a held Return must not commit"
press(Qt.Key_Return)
assert evaluate('submissions === 1 && submittedValue === "22" && !state().editing && !state().interaction')
assert evaluate("slider.keyboardConfirming === undefined"), "the Cancel/Apply prompt is gone"

press(Qt.Key_Return)
press(Qt.Key_Up)
assert evaluate("state().editing && state().preview === 21 && submissions === 1")
evaluate("pressedKeys = []; releasedKeys = []")
reserved = [key for key in keys if key not in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Return)]
for key in reserved:
    press(key)
assert evaluate("pressedKeys") == reserved
assert evaluate("releasedKeys") == reserved
assert evaluate("submissions === 1 && state().editing")
# A call or a hidden page ends an edit without sending it.
evaluate("c100xHost.blocked = true")
assert evaluate("!state().editing && state().preview === 21.5 && !state().interaction && submissions === 1")
evaluate("c100xHost.blocked = false; selectSlider()")
press(Qt.Key_Return)
press(Qt.Key_Down)
evaluate("page.visible = false")
assert evaluate("!state().editing && submissions === 1")
evaluate('page.visible = true; detail.control = {kind:"number", command:"temperature", min:5, max:6, step:10, value:5}; selectSlider()')
press(Qt.Key_Return)
assert evaluate("state().editing && submissions === 1"), "single-step range bypassed editing"
press(Qt.Key_Return)
assert evaluate('submissions === 2 && submittedValue === "5"'), "single-step value was not sent once"
press(Qt.Key_Return)
press(Qt.Key_Down)
evaluate("detail.enabled = false")
assert evaluate("!state().editing && !state().interaction && submissions === 2")
assert not errors, errors
sys.stdout.write("stock-key edit and commit, repeats, reserved keys and preemption: passed\n")
view.close()
