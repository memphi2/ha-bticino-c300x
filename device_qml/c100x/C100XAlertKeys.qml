import QtQuick 2.7

FocusScope {
    id: input
    property var controller: null
    property var scroll: null
    property var previousFocus: null
    readonly property bool showing: !!controller && !!controller.notice && !controller.blocked
    onShowingChanged: {
        if (showing) {
            previousFocus = c100xHost.focusWindow ? c100xHost.focusWindow.activeFocusItem : null
            forceActiveFocus()
        } else {
            focus = false
            // Calls/commissioning own focus as soon as the guard closes.
            if (controller && !controller.blocked && previousFocus && previousFocus.visible && previousFocus.enabled)
                previousFocus.forceActiveFocus()
            previousFocus = null
        }
    }
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
