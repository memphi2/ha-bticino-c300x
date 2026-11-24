import QtQuick 2.7
import "js/c300x_ha.js" as Api
import "js/c100x_ringer.js" as Ringer
import "js/c100x_presence.js" as Presence

Item {
    id: bridge
    property var vendor: null
    property var events: null
    property int muteState: -1
    property int commissionedState: -1
    property int normalState: -1
    property int offState: -1
    property var focusWindow: null
    // The verified hook's Loader supplies the vendor stack through its creation context.
    property var pageStack: typeof mainStackView === "undefined" ? null : mainStackView
    readonly property var homeItem: pageStack && pageStack.depth > 0 && typeof pageStack.get === "function" ? pageStack.get(0) : null
    property bool homeRegulationActive: false
    property bool running: false
    property bool displayReady: false
    property bool stopped: false
    property var ringer: null
    property var presence: null
    property string generation: ""
    property alias presenceRetry: presenceTimer
    property string language: Qt.locale().name
    property var preferences: bridge
    readonly property string uiBaseUrl: "http://127.0.0.1:8090"
    readonly property bool vendorReady: !!vendor && !!events && muteState >= 0 && commissionedState >= 0
        && !!vendor.audioState && typeof vendor.audioState.isRingtoneMute === "boolean"
        && typeof vendor.audioState.isStateEnabled === "function"
        && typeof vendor.beepEnabled === "boolean" && !!vendor.networkInfo
        && typeof vendor.networkInfo.isSoftAp === "boolean"
        && typeof events.callInProgress === "boolean" && typeof events.callActive === "boolean"
        && typeof vendor.commissioningStatus === "number" && typeof vendor.blockKeyboard === "boolean"
    readonly property bool blocked: !vendorReady || events.callInProgress || events.callActive
        || vendor.commissioningStatus !== commissionedState || vendor.networkInfo.isSoftAp || vendor.blockKeyboard
    readonly property bool alertsBlocked: blocked || !alertPageAllowed()
    readonly property bool touchToneEnabled: vendorReady && vendor.beepEnabled
    readonly property bool muted: vendorReady && vendor.audioState.isRingtoneMute
    property int muteSignals: 0
    property bool applyingTouchTone: false
    property bool touchToneReportAgain: false
    property alias touchToneRetry: toneRetry
    property alias touchToneReportDeadline: toneDeadline
    property bool feedbackEnabled: true
    property bool ready: false
    property bool busy: false
    property string errorKey: ""
    property alias deadline: preferenceDeadline

    function alertPageAllowed() {
        var current = pageStack ? pageStack.currentItem : null
        if (!current || !current.visible) return false
        if (current === homeItem && pageStack.depth === 1)
            return typeof current.syncC100xMenu === "function" && current.c100xAvailable === true && !homeRegulationActive
        if (current.c100xFullScreen !== true || !current.item || !current.item.visible || !current.item.pageItem) return false
        return current.item.pageItem.visible && current.item.pageName === "HomeAssistant.qml"
    }
    Connections {
        target: bridge.homeItem
        ignoreUnknownSignals: true
        onRegulationState: bridge.homeRegulationActive = state
    }
    onHomeItemChanged: homeRegulationActive = false
    Connections {
        target: bridge.vendorReady ? bridge.vendor.audioState : null
        ignoreUnknownSignals: true
        onIsRingtoneMuteChanged: bridge.muteSignals++
    }

    property QtObject feedbackToggle: QtObject {
        property bool on: true
        onOnChanged: if (on !== bridge.feedbackEnabled) bridge.setFeedbackEnabled(on)
    }
    onFeedbackEnabledChanged: feedbackToggle.on = feedbackEnabled
    onBusyChanged: if (!busy) feedbackToggle.on = feedbackEnabled
    property string entryPage: ""
    property bool homeAvailable: false
    property bool alarmAvailable: false
    property int entryRead: 0
    property int entryRetries: 0
    readonly property bool entriesWanted: running && !stopped && vendorReady
    readonly property bool homeCurrent: !!homeItem && pageStack.currentItem === homeItem
    function readEntries() {
        entryRetry.stop()
        var read = ++entryRead
        if (!entriesWanted) {
            homeAvailable = false
            alarmAvailable = false
            return
        }
        Api.homeButtons(function(alarm, dashboard, valid) {
            if (read !== bridge.entryRead || !bridge.entriesWanted) return
            if (valid) {
                bridge.entryRetries = 0
                bridge.alarmAvailable = alarm
                bridge.homeAvailable = dashboard
            } else if (bridge.entryRetries < 6) {
                entryRetry.interval = 1000 * Math.pow(2, bridge.entryRetries++)
                entryRetry.restart()
            } else {
                bridge.alarmAvailable = false
                bridge.homeAvailable = false
            }
        }, bridge)
    }
    function refreshEntries() {
        entryRetries = 0
        readEntries()
    }
    onEntriesWantedChanged: refreshEntries()
    onHomeCurrentChanged: if (homeCurrent) refreshEntries()
    Connections {
        target: bridge.vendorReady && bridge.vendor.screenState ? bridge.vendor.screenState : null
        ignoreUnknownSignals: true
        onStateChanged: if (bridge.vendor.screenState.state === bridge.normalState) bridge.refreshEntries()
    }
    Timer { id: entryRetry; onTriggered: bridge.readEntries() }
    function load() { Api.loadDisplayPreferences(bridge) }
    function setFeedbackEnabled(value) { Api.saveDisplayPreferences(bridge, value) }
    function setTouchTone(value) {
        if (!running || stopped || blocked || typeof value !== "boolean") return
        vendor.beepEnabled = value
    }
    function setMuted(value) {
        if (!running || stopped || blocked || typeof value !== "boolean") return null
        var audio = vendor.audioState
        if (audio.isStateEnabled(muteState) === value) return value
        var seen = muteSignals
        if (value) audio.enableState(muteState)
        else audio.disableState(muteState)
        if (muteSignals === seen && audio.isStateEnabled(muteState) === value) {
            if (value) audio.disableState(muteState)
            else audio.enableState(muteState)
        }
        return audio.isStateEnabled(muteState)
    }
    function reconnectRinger() { if (!stopped && running && !blocked) ringerRetry.restart() }
    function sync() {
        if (presence) presence.sync()
        if (!ringer) return
        ringerRetry.stop()
        if (!running || stopped || blocked) {
            ringer.stop()
            Api.stopTouchTone(bridge)
        } else {
            ringer.start()
            Api.watchTouchTone(bridge)
        }
    }
    onBlockedChanged: sync()
    onVendorReadyChanged: sync()
    onGenerationChanged: sync()
    onRunningChanged: sync()
    onDisplayReadyChanged: sync()
    onTouchToneEnabledChanged: if (!applyingTouchTone && !stopped && running && !blocked) toneReport.restart()
    Timer { id: ringerRetry; interval: 30000; onTriggered: if (bridge.ringer) bridge.ringer.start() }
    Timer { id: presenceTimer; interval: 1000; onTriggered: if (bridge.presence) bridge.presence.start() }
    Timer { id: toneRetry; interval: 30000; onTriggered: if (bridge.running && !bridge.blocked) Api.watchTouchTone(bridge) }
    Timer { id: toneReport; interval: 0; onTriggered: Api.reportTouchTone(bridge) }
    Timer { id: toneDeadline; interval: 5000; onTriggered: Api.retryTouchTone(bridge) }
    Timer { id: preferenceDeadline; interval: 5000; onTriggered: Api.cancelDisplayPreferences(bridge) }
    Component.onCompleted: {
        ringer = Ringer.create(bridge)
        presence = Presence.create(bridge)
        sync()
    }
    Component.onDestruction: {
        stopped = true
        ringerRetry.stop()
        toneReport.stop()
        if (ringer) ringer.stop()
        if (presence) presence.stop()
        Api.stopTouchTone(bridge)
        Api.cancelDisplayPreferences(bridge)
        entryRead++
    }
}
