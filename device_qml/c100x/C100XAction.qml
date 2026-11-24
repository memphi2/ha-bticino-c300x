import QtQuick 2.7

Item {
    id: root
    property bool c100xAction: true
    property bool keyboardSelected: false
    property bool down: false
    property int keyboardSteps: 0
    property int keyboardPosition: 0
    property int keyboardInitialPosition: 0
    property bool keyboardBuckets: true
    property real keyboardRangeRatio: 1
    property bool keyboardEditing: false
    property real mouseX: width / 2
    signal clicked(var mouse)
    signal actionPressed(var mouse)
    signal actionReleased(var mouse)
    signal positionChanged(var mouse)
    signal canceled()

    function point() { return {x: mouseX, y: height / 2, accepted: true} }
    function updatePosition() {
        mouseX = keyboardBuckets ? (keyboardPosition + 0.5) * width / keyboardSteps
            : keyboardPosition * keyboardRangeRatio * width / Math.max(1, keyboardSteps - 1)
    }
    function activate() {
        if (!enabled || !visible) return
        if (keyboardSteps > 1 || (!keyboardBuckets && keyboardSteps === 1)) {
            if (!keyboardEditing)
                keyboardPosition = Math.max(0, Math.min(keyboardSteps - 1, keyboardInitialPosition))
            keyboardEditing = !keyboardEditing
            down = keyboardEditing
            updatePosition()
            if (keyboardEditing) { actionPressed(point()); clicked(point()) }
            else actionReleased(point())
        } else {
            var at = point()
            down = true
            actionPressed(at)
            down = false
            actionReleased(at)
            clicked(at)
        }
    }
    function adjust(direction) {
        keyboardPosition = Math.max(0, Math.min(keyboardSteps - 1, keyboardPosition + direction))
        updatePosition()
        positionChanged(point())
        clicked(point())
    }
    function cancel() {
        var editing = keyboardEditing
        keyboardEditing = false
        down = false
        if (editing) canceled()
    }
    onVisibleChanged: if (!visible) cancel()
    onEnabledChanged: if (!enabled) cancel()
    Rectangle {
        anchors.fill: parent
        z: 100
        visible: root.keyboardSelected
        color: root.keyboardEditing ? "transparent" : "#33ffffff"
        border.width: root.keyboardEditing ? 3 : 0
        border.color: "white"
        radius: 6
        Rectangle {
            objectName: "c100xFocusBar"
            anchors.bottom: parent.bottom
            width: parent.width
            height: 5
            color: "white"
        }
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
