import QtQuick 1.1
import Components 1.0
import Components.Styles 1.0

Grid {
    id: root
    property variant rows: []
    property bool costs: false
    columns: 2
    spacing: 0
    height: Math.ceil(rows.length / 2) * 22

    Repeater {
        model: root.rows

        Item {
            width: Math.floor(root.width / 2)
            height: 22

            Rectangle {
                id: sumMark
                anchors.verticalCenter: parent.verticalCenter
                width: 10
                height: 10
                radius: 2
                color: modelData.color
            }

            UbuntuLightText {
                id: sumCost
                anchors.right: parent.right
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                width: root.costs ? 82 : 0
                horizontalAlignment: Text.AlignRight
                text: modelData.cost ? modelData.cost : ""
                color: "#e3e9f1"
                font.pixelSize: 14
                elide: Text.ElideRight
                clip: true
            }

            UbuntuLightText {
                id: sumValue
                anchors.right: sumCost.left
                anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                width: root.costs ? 100 : Math.min(116, parent.width * 0.52)
                text: modelData.value
                color: "white"
                font.pixelSize: 15
                horizontalAlignment: Text.AlignRight
                elide: Text.ElideRight
                clip: true
            }

            UbuntuLightText {
                anchors.left: sumMark.right
                anchors.leftMargin: 8
                anchors.right: sumValue.left
                anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                text: modelData.label
                textFormat: Text.PlainText
                color: "white"
                font.pixelSize: 14
                elide: Text.ElideRight
                clip: true
            }
        }
    }
}
