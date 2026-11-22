import QtQuick 2.7

Item {
    id: root
    property bool c100xAction: true
    property bool keyboardSelected: false
    property bool down: false
    property int keyboardSteps: 0
    property int keyboardPosition: 0
    property bool keyboardEditing: false
    property real mouseX: width / 2
    signal clicked(var mouse)
    signal actionPressed(var mouse)
    signal actionReleased(var mouse)
    signal positionChanged(var mouse)
    signal canceled()

    function point() { return {x: mouseX, y: height / 2, accepted: true} }
    function activate() {
        if (!enabled || !visible) return
        if (keyboardSteps > 1) {
            keyboardEditing = !keyboardEditing
            down = keyboardEditing
            mouseX = (keyboardPosition + 0.5) * width / keyboardSteps
            if (keyboardEditing) { actionPressed(point()); clicked(point()) }
            else actionReleased(point())
        } else {
            down = true
            actionPressed(point())
            clicked(point())
            actionReleased(point())
            down = false
        }
    }
    function adjust(direction) {
        keyboardPosition = Math.max(0, Math.min(keyboardSteps - 1, keyboardPosition + direction))
        mouseX = (keyboardPosition + 0.5) * width / keyboardSteps
        positionChanged(point())
        clicked(point())
    }
    function cancel() {
        if (keyboardEditing) canceled()
        keyboardEditing = false
        down = false
    }
    onVisibleChanged: if (!visible) cancel()
    onEnabledChanged: if (!enabled) cancel()
    Rectangle {
        anchors.fill: parent
        z: 100
        color: "transparent"
        border.width: root.keyboardSelected ? 3 : 0
        border.color: root.keyboardEditing ? "#ffbc42" : "#ffffff"
        radius: 4
    }
    MouseArea {
        anchors.fill: parent
        onPressed: { root.down = true; root.mouseX = mouse.x; root.actionPressed(mouse) }
        onPositionChanged: { root.mouseX = mouse.x; root.positionChanged(mouse) }
        onReleased: { root.down = false; root.actionReleased(mouse) }
        onClicked: { root.mouseX = mouse.x; root.clicked(mouse) }
        onCanceled: root.cancel()
    }
}
