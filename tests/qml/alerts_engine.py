"""Real offscreen mouse routing and Timer checks; Qt6 adapter, no device I/O."""

import os
from pathlib import Path
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import check_display_layout as harness  # noqa: E402
from PySide6.QtCore import QPoint, QUrl, qInstallMessageHandler  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtNetwork import QNetworkAccessManager  # noqa: E402
from PySide6.QtQml import QQmlEngine, QQmlNetworkAccessManagerFactory  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402


class OfflineManager(QNetworkAccessManager):
    def createRequest(self, operation, request, outgoing=None):
        # Any escape from the XHR mock fails closed before opening a socket.
        if request.url().scheme() not in ("file", "qrc", "data"):
            raise AssertionError("Unexpected network request: " + request.url().toString())
        return super().createRequest(operation, request, outgoing)


class OfflineFactory(QQmlNetworkAccessManagerFactory):
    def create(self, parent):
        return OfflineManager(parent)


def run(mode, fault="none"):
    app = QGuiApplication([])
    messages = []
    previous = qInstallMessageHandler(lambda _kind, _context, message: messages.append(message))
    try:
        with tempfile.TemporaryDirectory(prefix="c300x-alert-engine-") as temporary:
            directory = Path(temporary)
            harness.write_alert_mocks(directory)
            source = (ROOT / "device_qml/C300XAlerts.qml").read_text()
            if fault == "missing_observer":
                source = source.replace("            root.userInteraction()\n            mouse.accepted = false",
                                        "            mouse.accepted = false", 1)
            elif fault == "consumed_press":
                source = source.replace("            mouse.accepted = false", "            mouse.accepted = true", 1)
            (directory / "C300XAlerts.qml").write_text(harness.adapt_qml(source))
            (directory / "js").mkdir()
            (directory / "js/c300x_alerts.js").write_bytes((ROOT / "device_qml/js/c300x_alerts.js").read_bytes())
            frame = harness.frame_qml({"component": "C300XAlerts", "properties": {}}, harness.VIEWPORTS["native"])
            frame = frame.replace("function simulateClick() { frame.wakeCalls++ }",
                                  "function simulateClick() { frame.wakeCalls++; if (state === 0) { state = 2; stateChangedInt(0, 2) } }")
            frame = frame.replace("function disableState(value) { frame.releaseCalls++ }",
                                  "function disableState(value) { frame.releaseCalls++; state = 0; stateChangedInt(2, 0) }")
            (directory / "Frame.qml").write_text(frame)
            engine = QQmlEngine()
            factory = OfflineFactory()
            engine.setNetworkAccessManagerFactory(factory)
            engine.addImportPath(str(directory))
            transport = engine.evaluate(harness.MOCK_XHR.replace("return {constructor:", "return {requests: requests, constructor:"))
            assert not transport.isError(), transport.toString()
            engine.globalObject().setProperty("mockTransport", transport)
            engine.rootContext().setContextProperty("XMLHttpRequest", transport.property("constructor"))
            window = QQuickView(engine, None)
            window.setSource(QUrl.fromLocalFile(str(directory / "Frame.qml")))
            assert window.status() != QQuickView.Error, [error.toString() for error in window.errors()]
            root = window.rootObject()
            engine.globalObject().setProperty("probe", engine.newQObject(root))
            window.show()
            QTest.qWait(150)

            def js(expression):
                value = engine.evaluate(expression)
                assert not value.isError(), value.toString()
                return value.toVariant()

            def deliver(serial):
                js('var command = {id: "' + f'{serial:032x}' + '", revision: "' + f'{serial:032x}' + '", '
                   'notification_id: "test", severity: "warning", title: "Notice", message: "Message", '
                   'wake_duration: 1, sound_duration: 1, expires_in: 60, remaining_ms: 5000, '
                   'expires: Date.now() + 5000, message_expires: Date.now() + 60000}; '
                   'mockTransport.deliver(command)')

            assert js("probe.alertTarget.pendingRequest !== null")
            if mode == "transport":
                js("var stale = probe.alertTarget.pendingRequest; var callback = stale.onreadystatechange; probe.callActive = true")
                assert js("stale.aborted && probe.alertTarget.pendingRequest === null")
                QTest.qWait(150)
                assert js("mockTransport.log.length") == 1
                js("probe.callActive = false")
                QTest.qWait(150)
                assert js("mockTransport.log.length") == 2
                js('stale.status = 200; stale.readyState = 4; stale.responseText = "{}"; callback()')
                assert js("probe.alertTarget.pendingRequest !== stale && probe.alertTarget.notice === null")
                js("probe.alertTarget.preempt()")
                assert js("probe.alertTarget.pendingRequest === null")
                QTest.qWait(150)
                assert js("mockTransport.log.length") == 3
                js('probe.alertTarget.pendingRequest.respond(409, "{}")')
                QTest.qWait(150)
                assert js("mockTransport.log.length") == 4
                assert js("probe.alertTarget.pendingRequest !== null")
            else:
                # Control run proves the real timer releases an owned wake.
                js("probe.global.screenState.state = 0")
                deliver(1)
                QTest.qWait(1200)
                assert root.property("releaseCalls") == 1
                deliver(2)
                QTest.qWait(100)
                assert js("probe.global.screenState.state") == 2
                QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
                assert root.property("underlyingClicks") == 1, "outside press must pass through"
                assert js("probe.alertTarget.notice !== null"), "outside press must not dismiss"
                beeps = root.property("beepCalls")
                QTest.qWait(1200)
                assert root.property("releaseCalls") == 1, "user-owned Normal must survive alert expiry"
                assert root.property("beepCalls") == beeps
                QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(400, 385))
                assert js("probe.alertTarget.notice === null"), "panel acknowledgement must still work"
                assert root.property("underlyingClicks") == 1, "panel press must not pass through"
                QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
                assert root.property("underlyingClicks") == 2
            js("var last = probe.alertTarget.pendingRequest; probe.alertTarget.shutdown()")
            QTest.qWait(150)
            assert js("last.aborted && probe.alertTarget.pendingRequest === null")
            window.setSource(QUrl())
            window.close()
            app.processEvents()
            mouse_warning = ('Parameter "mouse" is not declared. Injection of parameters into signal handlers '
                             'is deprecated. Use JavaScript functions with formal parameters instead.')
            assert all("/C300XAlerts.qml:" in message and (
                harness.QT6_CONNECTION_WARNING in message or message.endswith(mouse_warning)
            ) for message in messages), messages
    finally:
        qInstallMessageHandler(previous)
    print("Alert engine regression passed: " + mode)


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "none")
