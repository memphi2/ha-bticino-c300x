import QtQuick 2.7

ListView {
    id: root
    property bool c100xAction: contentHeight > height
    property bool keyboardSelected: false
    property bool keyboardEditing: false
    function activate() { keyboardEditing = !keyboardEditing }
    function cancel() { keyboardEditing = false }
    function adjust(direction) {
        currentIndex = Math.max(0, Math.min(count - 1, currentIndex + direction))
        positionViewAtIndex(currentIndex, ListView.Contain)
    }
    highlight: Rectangle { color: "#344958"; opacity: root.keyboardSelected ? 0.8 : 0 }
}
