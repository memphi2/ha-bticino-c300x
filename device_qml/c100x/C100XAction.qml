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
    readonly property bool keyboardConfirmRequired: !keyboardBuckets
    property bool keyboardConfirming: false
    property bool keyboardApplySelected: false
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
        if (keyboardConfirming) {
            if (!keyboardApplySelected) { cancel(); return }
            keyboardConfirming = false
            keyboardEditing = false
            down = false
            actionReleased(point())
            return
        }
        if (keyboardSteps > 1 || (keyboardConfirmRequired && keyboardSteps === 1)) {
            if (keyboardEditing && keyboardConfirmRequired) {
                keyboardApplySelected = false
                keyboardConfirming = true
                return
            }
            if (!keyboardEditing)
                keyboardPosition = Math.max(0, Math.min(keyboardSteps - 1, keyboardInitialPosition))
            keyboardEditing = !keyboardEditing
            down = keyboardEditing
            updatePosition()
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
        if (keyboardConfirming) { keyboardApplySelected = direction > 0; return }
        keyboardPosition = Math.max(0, Math.min(keyboardSteps - 1, keyboardPosition + direction))
        updatePosition()
        positionChanged(point())
        clicked(point())
    }
    function cancel() {
        var editing = keyboardEditing
        keyboardConfirming = false
        keyboardApplySelected = false
        keyboardEditing = false
        down = false
        if (editing) canceled()
    }
    function confirmationLabel(apply) {
        var labels = {en: ["Cancel", "Apply"], de: ["Abbrechen", "Anwenden"],
                      fr: ["Annuler", "Appliquer"], it: ["Annulla", "Applica"]}
        var language = String(c100xHost.language).slice(0, 2).toLowerCase()
        return (labels[language] || labels.en)[apply ? 1 : 0]
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
        enabled: !root.keyboardConfirming
        onPressed: { root.down = true; root.mouseX = mouse.x; root.actionPressed(mouse) }
        onPositionChanged: { root.mouseX = mouse.x; root.positionChanged(mouse) }
        onReleased: { root.down = false; root.actionReleased(mouse) }
        onClicked: { root.mouseX = mouse.x; root.clicked(mouse) }
        onCanceled: root.cancel()
    }
    Loader {
        anchors.fill: parent
        z: 101
        active: root.keyboardConfirming
        sourceComponent: Component {
            Row {
                spacing: 8
                Repeater {
                    model: [false, true]
                    Rectangle {
                        width: (root.width - 8) / 2
                        height: root.height
                        color: "#23323b"
                        border.width: root.keyboardApplySelected === modelData ? 3 : 1
                        border.color: root.keyboardApplySelected === modelData ? "#ffffff" : "#74818b"
                        radius: 4
                        C100XText {
                            anchors.fill: parent
                            anchors.margins: 6
                            text: root.confirmationLabel(modelData)
                            color: "white"
                            font.pixelSize: 18
                            fontSizeMode: Text.Fit
                            minimumPixelSize: 12
                            elide: Text.ElideRight
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: { root.keyboardApplySelected = modelData; root.activate() }
                        }
                    }
                }
            }
        }
    }
}
