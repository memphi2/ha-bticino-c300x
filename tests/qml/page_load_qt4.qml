import QtQuick 1.1
import "js/c300x_ha.js" as ProbeApi

Rectangle {
    id: probeRoot
    width: 800; height: 480
    color: "#203070"
    QtObject { id: trsl; property string empty: ""; property string language: "en" }
    QtObject { id: homePage }
    QtObject { id: eventManager; function delayedGoToHomePage() {} }
    QtObject {
        id: c300xDisplayPreferences
        property string uiBaseUrl: "http://127.0.0.1:9"; property string bridgeProblem: ""; property bool openIntegration: false
        property bool bridgeShown: true; property bool feedbackEnabled: true; property bool ready: true; property bool busy: false
        property string label: ""
        function load() {} function setFeedbackEnabled(value) { feedbackEnabled = value }
    }
    QtObject { id: tabView; property QtObject current: QtObject { property string _pageName: "@HOST@" } function activateTab(a, b) {} }
    QtObject {
        id: global
        property bool answeringMachine: true
        property bool beepEnabled: false
        property bool screenshotActive: false
        property QtObject guiSettings: QtObject { property bool answeringMachineVisible: true; property bool professionalStudio: false }
        property bool advancedConfiguration: true
        property string device_id: "probe"
        property QtObject screenState: QtObject { property int state: 1; signal stateChangedInt(int new_state); function enableState(s) {} function disableState(s) {} }
        property QtObject audioState: QtObject { property int state: 0; function isStateEnabled(s) { return false } function enableState(s) {} function disableState(s) {} }
        function beep() {}
    }
    @HOST@ { id: page; _pageName: "@HOST@" }
    Component.onCompleted: ProbeApi.useBaseUrl("http://127.0.0.1:9")
    Timer { interval: 300; running: true; onTriggered: { page.aboutToShow(); console.log("C300X_PAGE_QT4_SHOWN @HOST@") } }
}
