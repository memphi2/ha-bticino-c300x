import QtQuick 2.7

Item {
    id: probe
    width: 800; height: 480
    property alias c100xHost: bridge
    QtObject {
        id: vendor
        property bool beepEnabled: true
        property bool blockKeyboard: false
        property int commissioningStatus: 3
        property QtObject networkInfo: QtObject { property bool isSoftAp: false }
        property QtObject audioState: QtObject {
            property bool isRingtoneMute: false
            property int calls: 0
            function enableState(state) { if (state !== 17) throw new Error("wrong enum"); calls++; isRingtoneMute = true }
            function disableState(state) { if (state !== 17) throw new Error("wrong enum"); calls++; isRingtoneMute = false }
            function isStateEnabled(state) { if (state !== 17) throw new Error("wrong enum"); return isRingtoneMute }
        }
    }
    QtObject {
        id: events
        property bool callInProgress: false
        property bool callActive: false
    }
    C100XBridge { id: bridge; vendor: vendor; events: events; muteState: 17; commissionedState: 3 }
    C100XScreen { id: screen; anchors.fill: parent }
    function require(condition, message) { if (!condition) throw new Error(message) }
    function exercise() {
        require(bridge.vendorReady && !bridge.blocked, "verified mock vendor contract not ready")
        bridge.running = true
        bridge.setMuted(true)
        require(vendor.audioState.isRingtoneMute && bridge.muted, "mute did not read back")
        bridge.setMuted(false)
        require(!vendor.audioState.isRingtoneMute && !bridge.muted, "unmute did not read back")
        bridge.setTouchTone(false)
        require(!vendor.beepEnabled && !bridge.touchToneEnabled, "key tone did not read back")
        require(screen.pageName === "" && !screen.pageItem, "screen opened a page without an entry")
        bridge.entryPage = "HomeAssistant.qml"
        screen.openPage("HomeAssistant.qml")
        require(screen.pageItem && screen.pageItem.pageActive, "dashboard loader did not start runtime")
        screen.openPage("Alarm.qml")
        require(screen.pageItem && screen.pageItem.pageActive, "alarm loader did not start runtime")
        screen.pageItem.pinCode = "1234"
        events.callInProgress = true
        require(bridge.blocked && !screen.pageItem, "call must unload extra page")
        bridge.setMuted(true)
        bridge.setTouchTone(true)
        require(vendor.audioState.calls === 2 && !vendor.beepEnabled, "call guard changed vendor state")
        events.callInProgress = false
        require(screen.pageName === "HomeAssistant.qml", "preempted page did not return to its entry")
        screen.openPage("Alarm.qml")
        require(screen.pageItem.pinCode === "", "PIN survived preemption")
        vendor.networkInfo.isSoftAp = true
        require(bridge.blocked && !screen.pageItem, "soft AP must preempt")
        vendor.networkInfo.isSoftAp = false
        vendor.commissioningStatus = 2
        require(bridge.blocked && !screen.pageItem, "commissioning must preempt")
        vendor.commissioningStatus = 3
        screen.openPage("Alarm.qml")
        events.callActive = true
        require(bridge.blocked, "active call must block")
        events.callActive = false
        screen.openPage("C100XSettings.qml")
        require(screen.pageName === "HomeAssistant.qml", "loader accepted the removed settings page")
        var old = screen.pageName
        screen.openPage("../../main.qml")
        require(screen.pageName === old, "loader accepted foreign source")
        screen.visible = false
        require(!screen.pageItem, "hidden page still loaded")
        bridge.running = false
    }
}
