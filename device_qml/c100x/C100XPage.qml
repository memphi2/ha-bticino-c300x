import QtQuick 2.7

FocusScope {
    id: root
    width: 800
    height: 480
    focus: true
    property string headerLabel: ""
    property bool showBackButton: true
    property color tint: "#66000000"
    property string icon: "C100XHome.svg"
    property alias header: headAnchor
    default property alias content: body.data
    property var selectedAction: null
    property int selectedAt: 0
    property int pages: 1
    property int pageIndex: 0
    property string view: ""
    property string shownView: ""
    property int homeAt: 0
    property bool inside: false
    property bool arriving: false
    property int arrivals: 0
    property bool exitSelected: false
    readonly property int count: pages + 1
    readonly property int currentIndex: exitSelected ? pages : Math.max(0, Math.min(pages - 1, pageIndex))
    property bool lifecycleReady: false
    property bool lifecycleActive: false
    signal backClicked()
    signal back()
    signal alarmRequested()
    signal pageRequested(int index)

    function scan(item, seen) {
        if (!item || !item.visible || !item.enabled || item.opacity === 0) return seen
        if (item.c100xAction === true && item.width > 0 && item.height > 0) seen.actions.push(item)
        if (item.c100xScroll === true && item.contentHeight > item.height + 1) seen.scrolls.push(item)
        var children = item.children || []
        for (var i = 0; i < children.length; i++) scan(children[i], seen)
        return seen
    }
    function controls() { return scan(body, {actions: [], scrolls: []}) }
    function usable(item) { return !!item && item.visible && item.enabled && item.width > 0 && item.height > 0 }
    function reveal(item) {
        var parentItem = item.parent
        while (parentItem && parentItem !== root) {
            if (parentItem.c100xScroll === true) {
                var top = item.mapToItem(parentItem.contentItem, 0, 0).y - parentItem.originY
                var last = Math.max(0, parentItem.contentHeight - parentItem.height)
                var at = parentItem.contentY - parentItem.originY
                if (top < at) at = top - 8
                else if (top + item.height > at + parentItem.height) at = top + item.height - parentItem.height + 8
                at = Math.max(0, Math.min(last, at))
                var edge = at < 24 ? 0 : last - at < 24 ? last : at
                if (top >= edge && top + item.height <= edge + parentItem.height) at = edge
                parentItem.contentY = parentItem.originY + at
            }
            parentItem = parentItem.parent
        }
    }
    function select(item) {
        if (selectedAction && selectedAction !== item) {
            selectedAction.cancel()
            selectedAction.keyboardSelected = false
        }
        selectedAction = item || null
        if (item) { item.keyboardSelected = true; reveal(item) }
    }
    function enter(last, at) {
        exitSelected = false
        var seen = controls()
        if (seen.actions.length) {
            selectedAt = last ? seen.actions.length - 1 : Math.max(0, Math.min(seen.actions.length - 1, at || 0))
            select(seen.actions[selectedAt])
        } else {
            select(null)
        }
        inside = seen.actions.length > 0 || seen.scrolls.length > 0
        return inside
    }
    function leave() {
        select(null)
        inside = false
        if (pages === 1) exitSelected = true
    }
    function move(direction) {
        settle()
        arriving = false
        if (!inside) {
            if (pages === 1 && exitSelected && enter(direction < 0)) return
            var next = (currentIndex + direction + count) % count
            exitSelected = next === pages
            if (!exitSelected && next !== pageIndex) pageRequested(next)
            return
        }
        var seen = controls()
        var at = seen.actions.indexOf(selectedAction)
        if (at >= 0 && selectedAction.keyboardEditing) {
            selectedAction.adjust(direction)
            return
        }
        if (seen.actions.length) {
            var to = at < 0 ? Math.max(0, Math.min(seen.actions.length - 1, selectedAt)) : at + direction
            if (to < 0 || to >= seen.actions.length) { leave(); return }
            selectedAt = to
            select(seen.actions[to])
        } else if (seen.scrolls.length) {
            var list = seen.scrolls[0]
            var last = list.originY + Math.max(0, list.contentHeight - list.height)
            var y = Math.max(list.originY, Math.min(last, list.contentY + direction * Math.round(list.height * 0.6)))
            if (y === list.contentY) leave()
            else list.contentY = y
        } else {
            leave()
        }
    }
    function confirm() {
        settle()
        arriving = false
        if (exitSelected) backClicked()
        else if (!inside) enter(false)
        else if (usable(selectedAction)) selectedAction.activate()
    }
    function arrive() {
        if (!lifecycleActive) return
        shownView = view
        select(null)
        inside = false
        exitSelected = false
        arrivals = 0
        arriving = true
    }
    function settle() {
        if (arriving) arriving = !enter(false, view === "" ? homeAt : 0) && ++arrivals < 100
    }
    function resetInput() {
        select(null)
        inside = false
        arriving = false
        exitSelected = false
    }
    onViewChanged: {
        if (shownView === "") homeAt = selectedAt
        arrive()
    }
    onPageIndexChanged: homeAt = 0
    Timer {
        interval: root.arriving ? 120 : 500
        repeat: true
        running: root.lifecycleActive && (root.arriving || root.inside)
        onTriggered: {
            if (root.arriving) { root.settle(); return }
            if (root.exitSelected || root.usable(root.selectedAction)) return
            if (root.selectedAction || root.controls().actions.length > 0)
                root.enter(false, root.selectedAt)
        }
    }
    Keys.onPressed: {
        event.accepted = false
        if (c100xHost.blocked) return
        if (event.key === Qt.Key_Up || event.key === Qt.Key_Down) {
            move(event.key === Qt.Key_Up ? -1 : 1)
            event.accepted = true
        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            if (!event.isAutoRepeat) confirm()
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
        if (active) arrive()
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
    Rectangle { anchors.fill: parent; color: root.tint; visible: !root.exitSelected }
    Image { x: 380; y: 8; width: 40; height: 40; sourceSize.width: 40; sourceSize.height: 40; source: root.icon }
    C100XText {
        id: title
        x: 36; y: 0
        width: Math.min(implicitWidth, 320)
        height: 56
        text: root.headerLabel
        color: "white"
        font.pixelSize: 24
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
    }
    Rectangle {
        objectName: "c100xPageMark"
        x: 36; y: 49
        width: title.width
        height: 5
        color: "white"
        visible: !root.inside && !root.exitSelected && root.pages > 1
    }
    Item {
        id: body
        objectName: "c100xBody"
        width: 800
        height: 440
        visible: !root.exitSelected
        Item { id: headAnchor; width: 800; height: 56 }
    }
    Image {
        objectName: "c100xExit"
        anchors.centerIn: parent
        source: root.exitSelected ? "../images/Exit.svg" : ""
        visible: root.exitSelected
    }
    Row {
        objectName: "c100xDots"
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 10
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 6
        Repeater {
            model: root.count
            Rectangle {
                width: 20; height: 20; radius: 10
                color: index === root.currentIndex ? "white" : "transparent"
                border.color: "white"
                border.width: 1
            }
        }
    }
}
