import QtQuick 2.7

Flickable {
    id: root
    property bool c100xAction: contentHeight > height
    property bool keyboardSelected: false
    property bool keyboardEditing: false
    function activate() { keyboardEditing = !keyboardEditing }
    function cancel() { keyboardEditing = false }
    function adjust(direction) { contentY = Math.max(0, Math.min(contentHeight - height, contentY + direction * 60)) }
    Rectangle {
        x: root.width - 4
        y: root.contentY
        width: 4
        height: root.height
        color: root.keyboardEditing ? "#ffbc42" : "#ffffff"
        visible: root.keyboardSelected
    }
}
