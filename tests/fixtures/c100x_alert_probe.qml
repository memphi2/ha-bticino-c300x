import QtQuick 2.7
import "js/c300x_alerts.js" as Controller

FocusScope {
    id: frame
    width: 800; height: 480; focus: true
    property var c100xHost: host
    property alias alerts: alerts
    property alias screen: screen
    property var vendorKeys: []
    Keys.onPressed: { vendorKeys = vendorKeys.concat([event.key]); event.accepted = true }
    QtObject {
        id: host
        property bool running: true
        property bool blocked: false
        readonly property bool alertsBlocked: blocked
        property string language: "en"
        property int normalState: 1
        property int offState: 0
        property var focusWindow: null
        property QtObject vendor: QtObject { property var screenState: screen }
    }
    QtObject {
        id: screen
        property int state: 0
        property int screensaverInterval: 10000
        property int clicks: 0
        property int releases: 0
        signal stateChangedInt(int previous, int current)
        function transition(value) { var prior = state; state = value; stateChangedInt(prior, value) }
        function simulateClick() { clicks++; if (state === 0) transition(1) }
        function disableState(value) {
            if (value !== 1) throw new Error("foreign screen state mutation")
            releases++; transition(0)
        }
    }
    Item { id: vendorFocus; objectName: "vendorFocus"; width: 800; height: 480; focus: true }
    Item { id: callFocus; objectName: "callFocus"; width: 800; height: 480 }
    C300XAlerts { id: alerts; anchors.fill: parent }
    function receive(command) { return Controller.runtimeFor(alerts).controller.receive(command) }
    function resume() { host.blocked = false; vendorFocus.forceActiveFocus() }
    function startCall() { callFocus.forceActiveFocus(); screen.transition(2); host.blocked = true }
    function poll() { alerts.abortPoll(); alerts.waitForCommand() }
}
