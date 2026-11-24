import QtQuick 2.7

C100XAction {
    id: root
    property bool checked: false
    property bool checkable: false
    property QtObject style
    signal touched()
    onClicked: { if (checkable) checked = !checked; touched() }
    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: root.checked ? "#66ffffff" : "#14ffffff"
        border.color: "white"
        border.width: 1
        Rectangle {
            width: parent.height - 8
            height: parent.height - 8
            radius: height / 2
            y: 4
            x: root.checked ? parent.width - width - 4 : 4
            color: root.checked ? "white" : "transparent"
            border.color: "white"
            border.width: 2
        }
    }
}
