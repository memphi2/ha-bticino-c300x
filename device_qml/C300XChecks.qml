import QtQuick 1.1
import Components.Styles 1.0

Column {
    id: root
    property variant checks: []
    property string emptyText: ""
    spacing: 8
    Repeater {
        model: root.checks
        Item {
            width: root.width
            height: 44
            UbuntuLightText {
                anchors.left: parent.left
                anchors.right: checkState.left
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                text: modelData.name
                textFormat: Text.PlainText
                font.pixelSize: 20
                color: "white"
                elide: Text.ElideRight
            }
            UbuntuLightText {
                id: checkState
                width: parent.width * 0.36
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: modelData.state_label
                textFormat: Text.PlainText
                font.pixelSize: 19
                color: modelData.color
                horizontalAlignment: Text.AlignRight
                elide: Text.ElideRight
            }
        }
    }
    UbuntuLightText {
        width: root.width
        height: visible ? Math.max(52, paintedHeight) : 0
        visible: root.checks.length === 0
        text: root.emptyText
        textFormat: Text.PlainText
        color: "#c7d0d9"
        font.pixelSize: 19
        wrapMode: Text.Wrap
    }
}
