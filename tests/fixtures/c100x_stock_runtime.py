"""Run the original C100X main.qml with the generated adapter on host Qt 5.

The vendor skin is read from the private extracted firmware and patched in a
scratch directory by the product's own awk transform; nothing is copied into
the repository. Vendor C++ objects are stand-ins (c100x_stock/), the agent is
an in-memory reply table whose requests are recorded. Keys are real key events.
This is host Qt 5.15, not the firmware's Qt 5.10.1 and not a device.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PyQt5.QtCore import QEventLoop, QIODevice, Qt, QTimer, QUrl
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt5.QtQml import (
    QQmlApplicationEngine,
    QQmlComponent,
    QQmlEngine,
    QQmlExpression,
    QQmlNetworkAccessManagerFactory,
)
from PyQt5.QtTest import QTest

ROOT = Path(__file__).resolve().parents[2]
STUBS = Path(__file__).resolve().parent / "c100x_stock"
RELEASE = ".c100x-" + "5" * 64
KEYS = {"D": Qt.Key_Down, "U": Qt.Key_Up, "R": Qt.Key_Return, "E": Qt.Key_Escape}
IGNORED = ("Implicitly defined onFoo properties in Connections are deprecated",)


class Reply(QNetworkReply):
    def __init__(self, manager, operation, request, status, payload):
        super().__init__(manager)
        self.data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.setOperation(operation)
        self.setRequest(request)
        self.setUrl(request.url())
        self.open(QIODevice.ReadOnly | QIODevice.Unbuffered)
        if status:
            self.setAttribute(QNetworkRequest.HttpStatusCodeAttribute, status)
            self.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
            QTimer.singleShot(0, self.complete)

    def complete(self):
        if self.isFinished():
            return
        self.setFinished(True)
        self.readyRead.emit()
        self.finished.emit()

    def abort(self):
        self.setFinished(True)

    def bytesAvailable(self):
        return len(self.data) + super().bytesAvailable()

    def readData(self, size):
        chunk, self.data = self.data[:size], self.data[size:]
        return chunk


class Agent(QNetworkAccessManager):
    """Answers from the route table; a missing sleeping request never completes."""

    def __init__(self, runtime, parent):
        super().__init__(parent)
        self.runtime = runtime

    def createRequest(self, operation, request, outgoing=None):
        url = request.url()
        if url.scheme() == "data":
            return super().createRequest(operation, request, outgoing)
        body = bytes(outgoing.readAll()).decode() if outgoing is not None else ""
        method = "POST" if operation == self.PostOperation else "GET"
        self.runtime.requests.append((method, url.toString(), body))
        route = self.runtime.routes.get(url.path()) if url.authority() == "127.0.0.1:8090" else None
        if callable(route):
            route = route(method, url, body)
        if route is None:
            if url.path().endswith("/next"):
                return Reply(self, operation, request, 0, {})
            return Reply(self, operation, request, 404, {"ok": False, "error": "not_found"})
        if isinstance(route, tuple):
            return Reply(self, operation, request, route[0], route[1])
        return Reply(self, operation, request, 200, route)


class Factory(QQmlNetworkAccessManagerFactory):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime

    def create(self, parent):
        return Agent(self.runtime, parent)


def build_skin(work, firmware_skin):
    """Scratch copy of the vendor skin with the real hooks and generated adapter."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import c100x_qml_builder
    skin = work / "skin"
    shutil.copytree(firmware_skin, skin)
    for path in skin.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    c100x_qml_builder.build(skin / RELEASE)
    for mode, name in (("main", "main.qml"), ("menu", "MainPage.qml")):
        result = subprocess.run(
            ["awk", "-v", f"mode={mode}", "-v", f"hooks={skin / RELEASE / 'hooks'}", "-v", f"release={RELEASE}",
             "-f", str(ROOT / "native_agent/scripts/c100x_hooks.awk"), str(firmware_skin / name)],
            check=True, capture_output=True)
        (skin / name).write_bytes(result.stdout)
    # Host Qt 5.15 rejects revisioned properties the firmware's 5.10 accepts under "QtQuick 2.0".
    for path in [*skin.glob("*.qml"), *(skin / "Components").glob("*.qml")]:
        path.write_text(re.sub(r"^import QtQuick 2\.0$", "import QtQuick 2.7", path.read_text(), flags=re.M))
    return skin


class Probe:
    """One document next to the generated adapter, with a stand-in c100xHost; no vendor skin."""

    def __init__(self, work, document, routes=None):
        sys.path.insert(0, str(ROOT / "scripts"))
        import c100x_qml_builder
        self.routes = dict(routes or {})
        self.requests = []
        self.warnings = []
        self.app = QGuiApplication.instance() or QGuiApplication([])
        self.source = Path(work) / "adapter"
        c100x_qml_builder.build(self.source)
        self.engine = QQmlEngine()
        self.factory = Factory(self)
        self.engine.setNetworkAccessManagerFactory(self.factory)
        self.engine.warnings.connect(lambda entries: self.warnings.extend(
            entry.toString() for entry in entries if not any(text in entry.toString() for text in IGNORED)))
        component = QQmlComponent(self.engine)
        component.setData(document.encode(), QUrl.fromLocalFile(str(self.source / "Probe.qml")))
        self.root = component.create()
        assert self.root is not None, [error.toString() for error in component.errors()]
        Runtime.wait(self, 50)

    def js(self, code):
        return Runtime.js(self, code, self.root)

    def wait(self, milliseconds):
        Runtime.wait(self, milliseconds)


class Runtime:
    def __init__(self, work, firmware_skin, routes=None, setup=""):
        self.routes = dict(routes or {})
        self.requests = []
        self.warnings = []
        self.app = QGuiApplication.instance() or QGuiApplication([])
        self.skin = build_skin(Path(work), Path(firmware_skin))
        self.engine = QQmlApplicationEngine()
        self.factory = Factory(self)
        self.engine.setNetworkAccessManagerFactory(self.factory)
        self.engine.addImportPath(str(STUBS))
        self.engine.addImportPath(str(self.skin))
        self.engine.warnings.connect(lambda entries: self.warnings.extend(
            entry.toString() for entry in entries if not any(text in entry.toString() for text in IGNORED)))
        component = QQmlComponent(self.engine, QUrl.fromLocalFile(str(STUBS / "VendorGlobal.qml")))
        self.vendor = component.create()
        assert self.vendor is not None, [error.toString() for error in component.errors()]
        self.engine.rootContext().setContextProperty("global", self.vendor)
        if setup:
            self.js(setup, self.vendor)
        self.engine.load(QUrl.fromLocalFile(str(self.skin / "main.qml")))
        assert self.engine.rootObjects(), self.warnings
        self.window = self.engine.rootObjects()[0]
        self.wait(300)

    def wait(self, milliseconds):
        loop = QEventLoop()
        QTimer.singleShot(milliseconds, loop.quit)
        loop.exec_()

    def js(self, code, target=None):
        target = target or self.window
        expression = QQmlExpression(QQmlEngine.contextForObject(target) or self.engine.rootContext(), target, code)
        value, undefined = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value.toVariant() if hasattr(value, "toVariant") else value

    def stack(self, code):
        """Evaluate in the context of the stack's current page (vendor ids resolve there)."""
        return self.js(code, self.js("mainStackView.currentItem"))

    def keys(self, text, settle=900):
        for token in text.split():
            match = re.fullmatch(r"(\d*)([DURE])", token)
            for _ in range(int(match[1] or 1)):
                QTest.keyClick(self.window, KEYS[match[2]])
                self.wait(settle)

    def adapter_warnings(self):
        return [entry for entry in self.warnings if "/.c100x-" in entry]

    def paths(self, method=None):
        return [QUrl(url).path() for kind, url, body in self.requests if method in (None, kind)]

    def shot(self, path):
        self.wait(50)
        assert self.window.grabWindow().save(str(path))
