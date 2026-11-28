import QtQuick 2.7

FocusScope {
    id: input
    property var controller: null
    property var scroll: null
    property var owner: null
    readonly property bool showing: !!controller && !!controller.notice && !controller.blocked
    function holds(ancestor) {
        for (var item = input; item; item = item.parent) if (item === ancestor) return true
        return false
    }
    function vendorScope() {
        var item = c100xHost ? c100xHost.pageStack : null
        while (item && item.parent && !holds(item.parent)) item = item.parent
        return item && item.parent ? item : null
    }
    function giveBack() {
        focus = false
        if (owner) owner.focus = true
    }
    onShowingChanged: {
        if (showing) {
            owner = vendorScope()
            forceActiveFocus()
        } else giveBack()
    }
    Component.onDestruction: giveBack()
    Keys.priority: Keys.BeforeItem
    Keys.onPressed: {
        event.accepted = false
        if (!showing) return
        controller.userInteraction()
        if (event.key === Qt.Key_Up || event.key === Qt.Key_Down) {
            if (scroll) scroll.contentY = Math.max(0, Math.min(Math.max(0, scroll.contentHeight - scroll.height),
                scroll.contentY + (event.key === Qt.Key_Down ? 64 : -64)))
        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter
                   || event.key === Qt.Key_Back || event.key === Qt.Key_Escape) {
            if (!event.isAutoRepeat && !controller.acknowledging) {
                controller.acknowledge()
            }
        } else return
        event.accepted = true
    }
}
