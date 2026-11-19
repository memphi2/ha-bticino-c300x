import QtQuick 1.1
import Components 1.0

Grid {
    id: navigation
    property variant links: []
    signal selected(int pageIndex)
    columns: 2
    spacing: 10

    Repeater {
        model: navigation.links.length
        Item {
            width: (navigation.width - navigation.spacing) / 2
            height: 52
            Image {
                anchors.fill: parent
                source: button.pressed ? "images/first_configuration/list_btn_p.svg" : "images/first_configuration/list_btn.svg"
                fillMode: Image.Stretch
            }
            Text {
                anchors.fill: parent
                anchors.margins: 8
                text: navigation.links[index].title
                textFormat: Text.PlainText
                font.family: "Ubuntu"
                font.pixelSize: 16
                color: "white"
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
            BeepingMouseArea {
                id: button
                anchors.fill: parent
                onClicked: navigation.selected(navigation.links[index].index)
            }
        }
    }
}
