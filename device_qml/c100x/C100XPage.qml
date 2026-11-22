import QtQuick 2.7

FocusScope {
    id: root
    width: 800
    height: 480
    focus: true
    property string headerLabel: ""
    property bool showBackButton: true
    property color backgroundColor: "#102b39"
    property alias header: heading
    property var selectedAction: null
    property int count: 1
    property int currentIndex: 0
    property bool lifecycleReady: false
    property bool lifecycleActive: false
    signal backClicked()
    signal back()
    signal alarmRequested()

    function actions(item, output) {
        if (!item || !item.visible || !item.enabled || item.opacity === 0) return
        if (item.c100xAction === true && item.width > 0 && item.height > 0) output.push(item)
        var children = item.children || []
        for (var i = 0; i < children.length; i++) actions(children[i], output)
    }
    function reveal(item) {
        var parentItem = item.parent
        while (parentItem && parentItem !== root) {
            if (parentItem.contentY !== undefined && parentItem.contentItem !== undefined) {
                var point = item.mapToItem(parentItem.contentItem, 0, 0)
                if (point.y < parentItem.contentY) parentItem.contentY = Math.max(0, point.y)
                else if (point.y + item.height > parentItem.contentY + parentItem.height)
                    parentItem.contentY = Math.max(0, Math.min(parentItem.contentHeight - parentItem.height, point.y + item.height - parentItem.height))
            }
            parentItem = parentItem.parent
        }
    }
    function move(direction) {
        var available = []
        actions(root, available)
        var at = available.indexOf(selectedAction)
        if (selectedAction && at >= 0 && selectedAction.keyboardEditing) {
            selectedAction.adjust(direction)
            return
        }
        if (selectedAction) { selectedAction.cancel(); selectedAction.keyboardSelected = false }
        var next = at < 0 ? (direction < 0 ? available.length - 1 : 0) : (at + direction + available.length) % available.length
        selectedAction = available.length ? available[next] : null
        if (selectedAction) { selectedAction.keyboardSelected = true; reveal(selectedAction) }
    }
    function resetInput() {
        if (selectedAction) { selectedAction.cancel(); selectedAction.keyboardSelected = false }
        selectedAction = null
    }
    Keys.onPressed: {
        event.accepted = false
        if (c100xHost.blocked) return
        if (event.key === Qt.Key_Up || event.key === Qt.Key_Down) {
            move(event.key === Qt.Key_Up ? -1 : 1)
            event.accepted = true
        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            if (!selectedAction) move(1)
            else if (selectedAction.visible && selectedAction.enabled) selectedAction.activate()
            event.accepted = true
        } else if (event.key === Qt.Key_Back || event.key === Qt.Key_Escape) {
            if (selectedAction && selectedAction.keyboardEditing) selectedAction.cancel()
            else backClicked()
            event.accepted = true
        }
    }
    function syncLifecycle() {
        if (!lifecycleReady) return
        var active = visible && !c100xHost.blocked
        if (active === lifecycleActive) return
        lifecycleActive = active
        resetInput()
        if (active && root.aboutToShow) root.aboutToShow()
        else if (!active && root.aboutToHide) root.aboutToHide()
    }
    onVisibleChanged: syncLifecycle()
    Connections {
        target: c100xHost
        ignoreUnknownSignals: true
        onBlockedChanged: root.syncLifecycle()
    }
    Component.onCompleted: { lifecycleReady = true; syncLifecycle() }
    Component.onDestruction: {
        resetInput()
        if (lifecycleActive && root.aboutToHide) root.aboutToHide()
    }
    Rectangle { anchors.fill: parent; z: -1; color: root.backgroundColor }
    Item {
        id: heading
        width: parent.width
        height: 54
        C100XAction {
            id: backAction
            width: 64
            height: 46
            x: 6; y: 4
            visible: root.showBackButton
            onClicked: root.backClicked()
            C100XText { anchors.centerIn: parent; text: "<"; color: "white"; font.pixelSize: 28 }
        }
        C100XText {
            anchors.left: backAction.right
            anchors.right: parent.right
            anchors.rightMargin: 250
            height: parent.height
            text: root.headerLabel
            color: "white"
            font.pixelSize: 22
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
    }
}
