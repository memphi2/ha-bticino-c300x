"""Qt5 in-memory HTTP reply: no network transport, with real XHR status handling."""

import json

from PyQt5.QtCore import QIODevice, QTimer
from PyQt5.QtNetwork import QNetworkReply, QNetworkRequest


class MemoryReply(QNetworkReply):
    def __init__(self, manager, operation, request, payload):
        super().__init__(manager)
        self.data = json.dumps(payload).encode()
        self.setOperation(operation)
        self.setRequest(request)
        self.setUrl(request.url())
        self.setAttribute(QNetworkRequest.HttpStatusCodeAttribute, 200)
        self.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        self.open(QIODevice.ReadOnly | QIODevice.Unbuffered)
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
