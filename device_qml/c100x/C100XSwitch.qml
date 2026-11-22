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
        radius: 4
        color: root.checked ? "#257458" : "#36434b"
        border.color: "#b1c2cb"
        Rectangle {
            width: parent.width / 2 - 6
            height: parent.height - 8
            y: 4
            x: root.checked ? parent.width - width - 4 : 4
            color: "#ffffff"
            radius: 3
        }
    }
}
