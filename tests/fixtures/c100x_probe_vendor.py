"""What the vendor skin gives every adapter page: its `global` object, the EXIT picture and the background."""

from pathlib import Path

from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtQml import QQmlComponent

GLOBAL = b"""import QtQuick 2.7
QtObject {
    property QtObject screenState: QtObject {
        property int state: 2
        signal stateChangedInt(int new_state)
    }
}
"""


def provide(engine, source):
    component = QQmlComponent(engine)
    component.setData(GLOBAL, QUrl())
    vendor = component.create()
    assert vendor is not None, component.errors()
    engine.rootContext().setContextProperty("global", vendor)
    images = Path(source).parent / "images"
    images.mkdir(exist_ok=True)
    (images / "Exit.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="136" height="136"/>\n')
    picture = QImage(8, 8, QImage.Format_RGB32)
    picture.fill(QColor("#2b2440"))
    assert picture.save(str(images / "background.jpg"))
    return vendor
