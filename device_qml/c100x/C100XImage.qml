import QtQuick 2.7

Item {
    id: root
    property string source: ""
    property int fillMode: Image.Stretch
    property bool cache: true
    readonly property bool skin: source.indexOf("images/settings/") === 0 || source.indexOf("images/first_configuration/") === 0
    readonly property int status: picture.status
    readonly property size sourceSize: picture.sourceSize
    readonly property real paintedWidth: picture.paintedWidth
    readonly property real paintedHeight: picture.paintedHeight
    Rectangle {
        anchors.fill: parent
        visible: root.skin
        color: root.source.indexOf("_p.svg") >= 0 ? "#31526b" : "#23323b"
        border.width: 1
        border.color: "#74818b"
        radius: 4
    }
    Image {
        id: picture
        anchors.fill: parent
        source: root.skin ? "" : root.source === "images/keylock_icon-small.svg" ? "../images/key.svg" : root.source
        fillMode: root.fillMode
        cache: root.cache
    }
}
