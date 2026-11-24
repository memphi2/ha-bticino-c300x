import QtQuick 2.7

Rectangle {
    id: more
    property bool shown: false
    property bool up: false
    objectName: up ? "c100xMoreAbove" : "c100xMoreBelow"
    z: 50
    width: 64
    height: 22
    radius: 11
    color: "#b3000000"
    visible: shown
    Image { anchors.centerIn: parent; source: "C100XMore.svg"; rotation: more.up ? 180 : 0 }
}
