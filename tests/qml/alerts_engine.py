"""Real offscreen mouse routing and Timer checks; Qt6 adapter, no device I/O."""

import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import check_display_layout as harness  # noqa: E402
from PySide6.QtCore import QIODevice, QPoint, Qt, QTimer, QUrl, qInstallMessageHandler  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply  # noqa: E402
from PySide6.QtQml import QQmlEngine, QQmlNetworkAccessManagerFactory  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402


class DeniedReply(QNetworkReply):
    def __init__(self, manager, operation, request):
        super().__init__(manager)
        self.setOperation(operation)
        self.setRequest(request)
        self.setUrl(request.url())
        self.open(QIODevice.ReadOnly)
        self.setError(QNetworkReply.ContentAccessDenied, "Unexpected network request")
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
        # Any escape from the XHR mock fails closed before opening a socket.
        if request.url().scheme() not in ("file", "qrc", "data"):
            self.attempts.append(request.url().toString())
            return DeniedReply(self, operation, request)
        return super().createRequest(operation, request, outgoing)


class OfflineFactory(QQmlNetworkAccessManagerFactory):
    def __init__(self):
        super().__init__()
        self.attempts = []

    def create(self, parent):
        return OfflineManager(parent, self.attempts)


def run(mode, fault="none"):
    app = QGuiApplication([])
    messages = []
    previous = qInstallMessageHandler(lambda _kind, _context, message: messages.append(message))
    try:
        with tempfile.TemporaryDirectory(prefix="c300x-alert-engine-") as temporary:
            directory = Path(temporary)
            harness.write_alert_mocks(directory)
            source = harness.adapt_qml((ROOT / "device_qml/C300XAlerts.qml").read_text())
            # Fault injection follows strict adaptation; the production handler is never exempted.
            if fault == "missing_observer":
                source = source.replace("            root.userInteraction()\n            mouse.accepted = false",
                                        "            mouse.accepted = false", 1)
            elif fault == "consumed_press":
                source = source.replace("            mouse.accepted = false", "            mouse.accepted = true", 1)
            (directory / "C300XAlerts.qml").write_text(source)
            (directory / "js").mkdir()
            (directory / "js/c300x_alerts.js").write_bytes((ROOT / "device_qml/js/c300x_alerts.js").read_bytes())
            (directory / "js/c300x_i18n.js").write_bytes((ROOT / "device_qml/js/c300x_i18n.js").read_bytes())
            (directory / "js/c300x_ha.js").write_text(harness.mock_api_transport(
                (ROOT / "device_qml/js/c300x_ha.js").read_text()))
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

            assert js("probe.alertTarget.canListen() && mockTransport.pending().length === 1")
            if mode == "ack":
                deliver(1)
                js("mockTransport.ackResponse(null, {})")
                QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(400, 385))
                assert js("probe.alertTarget.acknowledging && !!probe.alertTarget.notice")
                requests = js("mockTransport.log.length")
                QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(400, 385))
                assert js("mockTransport.log.length") == requests
                js('mockTransport.requests[mockTransport.requests.length - 1].respond(503, "{}")')
                assert js("probe.alertTarget.ackFailed && !probe.alertTarget.acknowledging && !!probe.alertTarget.notice")
                QTest.qWait(300)
                assert js("mockTransport.log.length") == requests, "no automatic ack retry"
                js("mockTransport.ackResponse(200, {ok: true})")
                QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(400, 385))
                assert js("!probe.alertTarget.notice && !probe.alertTarget.ackFailed")
                assert js("mockTransport.log.length") == requests + 1
            elif mode == "localization":
                deliver(1)
                pending = [root]
                severity_label = None
                while pending:
                    item = pending.pop()
                    context = QQmlEngine.contextForObject(item)
                    if context and context.nameForObject(item) == "severityLabel":
                        severity_label = item
                        break
                    pending.extend(item.childItems())
                assert severity_label is not None
                for language, severity, acknowledgement in (
                    ("de", "!  Warnung", "Gelesen"), ("it", "!  Avviso", "Letto"),
                    ("fr", "!  Avertissement", "Lu"), ("en", "!  Warning", "Mark read"),
                ):
                    js('probe.trsl.language = "' + language + '"')
                    app.processEvents()
                    assert js("probe.alertTarget.uiLanguage") == language
                    assert js("probe.alertTarget.severityText()") == severity
                    assert severity_label.property("text") == severity
                    assert js("probe.alertTarget.acknowledgeLabel") == acknowledgement
            elif mode == "transport":
                js("var stale = mockTransport.pending()[0]; var callback = stale.onreadystatechange; probe.callActive = true")
                assert js("stale.aborted && mockTransport.pending().length === 0")
                QTest.qWait(150)
                assert js("mockTransport.log.length") == 1
                js("probe.callActive = false")
                QTest.qWait(150)
                assert js("mockTransport.log.length") == 2
                js('stale.status = 200; stale.readyState = 4; stale.responseText = "{}"; callback()')
                assert js("mockTransport.pending().length === 1 && mockTransport.pending()[0] !== stale && !probe.alertTarget.notice")
                js("probe.alertTarget.preempt()")
                assert js("mockTransport.pending().length === 0")
                QTest.qWait(150)
                assert js("mockTransport.log.length") == 3
                js('mockTransport.pending()[0].respond(409, "{}")')
                QTest.qWait(150)
                assert js("mockTransport.log.length") == 4
                assert js("mockTransport.pending().length === 1")
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
            js("var last = mockTransport.pending()[0]; probe.alertTarget.shutdown()")
            QTest.qWait(150)
            assert js("last.aborted && mockTransport.pending().length === 0 && !probe.alertTarget.canListen()")
            window.setSource(QUrl())
            window.close()
            app.processEvents()
            assert factory.attempts == [], factory.attempts
            assert messages == [], messages
    finally:
        qInstallMessageHandler(previous)
    sys.stdout.write("Alert engine regression passed: " + mode + "\n")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "none")
