"""Qt5 host rendering probe. Vendor objects are not simulated as hardware proof."""

import json
import os
import sys
from pathlib import Path

from PyQt5 import sip
from PyQt5.QtCore import QObject, QUrl, pyqtProperty, pyqtSlot
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtQml import (
    QQmlComponent,
    QQmlEngine,
    QQmlExpression,
    QQmlNetworkAccessManagerFactory,
)


class OfflineNetwork(QNetworkAccessManager):
    def createRequest(self, operation, request, outgoing=None):
        # No host agent, Home Assistant, Internet or firmware service is contacted.
        return super().createRequest(self.GetOperation, QNetworkRequest(QUrl("data:application/json,{}")))


class OfflineFactory(QQmlNetworkAccessManagerFactory):
    def create(self, parent):
        return OfflineNetwork(parent)


class Preferences(QObject):
    @pyqtProperty(bool, constant=True)
    def feedbackEnabled(self):
        return True

    @pyqtSlot()
    def load(self):
        pass


class Host(QObject):
    def __init__(self):
        super().__init__()
        self.pref = Preferences(self)

    @pyqtProperty(bool, constant=True)
    def blocked(self):
        return False

    @pyqtProperty(str, constant=True)
    def language(self):
        return "en"

    @pyqtProperty(QObject, constant=True)
    def preferences(self):
        return self.pref


class VendorEnums(QObject):
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
host = Host()
engine.rootContext().setContextProperty("c100xHost", host)
enums = VendorEnums()
engine.rootContext().setContextProperty("AudioState", enums)
engine.rootContext().setContextProperty("Commissioning", enums)
engine.rootContext().setContextProperty("ScreenState", enums)
errors = []
engine.warnings.connect(lambda warnings: errors.extend(error.toString() for error in warnings
    if "Implicitly defined onFoo properties in Connections are deprecated" not in error.toString()))
source = Path(sys.argv[1])


def evaluate(item, script):
    expression = QQmlExpression(engine.rootContext(), item, script)
    value, undefined = expression.evaluate()
    if expression.hasError():
        errors.append(expression.error().toString())
    return None if undefined else value


for name in sys.argv[2:]:
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(source / name)))
    if component.isError():
        errors.extend(error.toString() for error in component.errors())
        continue
    item = component.create()
    if item is None:
        errors.extend(error.toString() for error in component.errors())
        continue
    item.setProperty("width", 800)
    item.setProperty("height", 480)
    if name in {"HomeAssistant.qml", "Alarm.qml"}:
        for script in ("move(1)", "move(1)", "move(-1)", "resetInput()"):
            evaluate(item, script)
    item.setProperty("visible", False)
    sip.delete(item)
    app.processEvents()

# Exercise the actual key-selection and edit protocol, including a clipped
# offscreen action and a numeric command that must not submit until confirmed.
component = QQmlComponent(engine)
component.setData(b'''
import QtQuick 2.7
C100XPage {
    id: page
    property int invoked: 0
    property int submitted: 0
    C100XScroll {
        id: scroller
        x: 10; y: 60; width: 780; height: 300
        contentWidth: width; contentHeight: 900; clip: true
        C100XAction {
            id: bottom
            objectName: "bottom"
            x: 10; y: 800; width: 100; height: 50
            onClicked: page.invoked++
        }
    }
    C100XAction {
        id: slider
        x: 20; y: 380; width: 400; height: 60
        keyboardSteps: 21
        onActionReleased: page.submitted++
    }
    function exercise() {
        move(1)
        if (!selectedAction) throw new Error("no first action")
        for (var i = 0; i < 8 && selectedAction !== bottom; i++) move(1)
        if (selectedAction !== bottom || scroller.contentY < 550) throw new Error("unreachable clipped action")
        selectedAction.activate()
        if (invoked !== 1) throw new Error("activation failed")
        for (i = 0; i < 8 && selectedAction !== slider; i++) move(1)
        if (selectedAction !== slider) throw new Error("unreachable slider")
        slider.activate()
        move(1)
        if (slider.keyboardPosition !== 1 || submitted !== 0) throw new Error("early submission")
        slider.activate()
        if (submitted !== 1) throw new Error("missing confirmed submission")
        slider.activate()
        slider.cancel()
        if (submitted !== 1 || slider.down) throw new Error("cancel changed state")
        resetInput()
    }
}
''', QUrl.fromLocalFile(str(source / "KeyboardProbe.qml")))
item = component.create()
if item is None:
    errors.extend(error.toString() for error in component.errors())
else:
    evaluate(item, "exercise()")
    sip.delete(item)

for fixture in ("c100x_numeric_probe.qml", "c100x_bridge_probe.qml", "c100x_hook_probe.qml", "c100x_menu_hook_probe.qml"):
    component = QQmlComponent(engine)
    document = Path(__file__).with_name(fixture).read_bytes()
    document = document.replace(b"@MAIN_HOOK@", (source / "hooks/main.inc").read_bytes().replace(b"@RELEASE@", b"."))
    document = document.replace(b"@MENU_HOOK@", (source / "hooks/menu.inc").read_bytes())
    if fixture == "c100x_hook_probe.qml":
        stock_lines = Path(os.environ["C100X_STOCK_MAIN"]).read_text().splitlines()
        for token, anchor in (
            (b"@VENDOR_ARRIVAL@", "                        if (!mainStackView.currentItem.hasOwnProperty('menuVisible') ||"),
            (b"@VENDOR_POP_ARRIVAL@", "                        if(!vctModel.vct.callInProgress)"),
        ):
            start = stock_lines.index(anchor)
            end = stock_lines.index("                    }", start)
            document = document.replace(token, "\n".join(stock_lines[start:end]).encode())
    component.setData(document,
                      QUrl.fromLocalFile(str(source / fixture)))
    item = component.create()
    if item is None:
        errors.extend(error.toString() for error in component.errors())
    else:
        evaluate(item, "exercise()")
        sip.delete(item)
sys.stdout.write(json.dumps(errors, indent=2) + "\n")
sys.exit(bool(errors))
