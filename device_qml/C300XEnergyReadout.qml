import QtQuick 1.1
import Components 1.0
import Components.Styles 1.0

Item {
    id: root
    property string interval: ""
    property variant rows: []
    property int axisWidth: 62
    property real rowsY: 0
    signal dismissed()

    UbuntuLightText {
        objectName: "energyInterval"
        x: root.axisWidth
        width: Math.max(0, parent.width - x - 48)
        height: 22
        text: root.interval
        textFormat: Text.PlainText
        color: "white"
        font.pixelSize: 15
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
    }

    Item {
        anchors.right: parent.right
        width: 40
        height: 28
        Rectangle {
            anchors.centerIn: parent
            width: 17
            height: 2
            rotation: 45
            color: "white"
        }
        Rectangle {
            anchors.centerIn: parent
            width: 17
            height: 2
            rotation: -45
            color: "white"
        }
        MouseArea {
            objectName: "energyDismiss"
            anchors.fill: parent
            onClicked: root.dismissed()
        }
    }

    C300XEnergySums {
        objectName: "energyValues"
        y: root.rowsY
        width: parent.width
        rows: root.rows
    }
}
