import QtQuick 1.1
import Components 1.0

Grid {
    id: navigation
    property variant links: []
    property bool bar: false
    property int current: -2
    signal selected(int pageIndex)
    columns: 2
    spacing: bar ? 0 : 10

    Repeater {
        model: navigation.links.length
        Item {
            property variant link: index < navigation.links.length ? navigation.links[index] : ({})
            property bool active: link.index === navigation.current
            width: (navigation.width - navigation.spacing * (navigation.columns - 1)) / navigation.columns
            height: navigation.bar ? 56 : 52
            Image {
                anchors.fill: parent
                visible: !navigation.bar
                source: button.pressed ? "images/first_configuration/list_btn_p.svg" : "images/first_configuration/list_btn.svg"
                fillMode: Image.Stretch
            }
            Rectangle {
                anchors.fill: parent
                visible: navigation.bar
                color: "#080c24"
                opacity: button.pressed ? 0.95 : 0.76
            }
            Rectangle {
                visible: navigation.bar && active
                anchors.bottom: parent.bottom
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width / 2
                height: 3
                color: "#ffd24a"
            }
            Text {
                anchors.fill: parent
                anchors.margins: navigation.bar ? 6 : 8
                text: link.title || ""
                textFormat: Text.PlainText
                font.family: "Ubuntu"
                font.pixelSize: navigation.bar ? 17 : 16
                color: active ? "#ffd24a" : "white"
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
                horizontalAlignment: navigation.bar ? Text.AlignHCenter : Text.AlignLeft
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
