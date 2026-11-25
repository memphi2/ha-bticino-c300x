import QtQuick 1.1
import "js/c300x_i18n.js" as ProbeTexts

Rectangle {
    id: probeRoot
    width: 800; height: 480
    color: "#203070"
    Image { anchors.fill: parent; source: "@BACKGROUND@" }
    QtObject { id: trsl; property string empty: ""; property string language: "@LANGUAGE@" }
    QtObject { id: homePage }
    QtObject { id: eventManager; function delayedGoToHomePage() {} }
    QtObject {
        id: c300xDisplayPreferences
        property string uiBaseUrl: "@BASE@"; property string bridgeProblem: ""; property bool openIntegration: true
        property bool bridgeShown: true; property bool feedbackEnabled: false; property bool ready: true; property bool busy: false
        property string label: ProbeTexts.text(trsl.language, "ha_feedback_colors")
        function load() {} function setFeedbackEnabled(value) { feedbackEnabled = value }
    }
    QtObject { id: tabView; property QtObject current: QtObject { property string _pageName: "Settings" } function activateTab(a, b) {} }
    QtObject {
        id: global
        property bool answeringMachine: true
        property bool beepEnabled: false
        property bool screenshotActive: false
        property QtObject guiSettings: QtObject { property bool answeringMachineVisible: true; property bool professionalStudio: false }
        property bool advancedConfiguration: true
        property string device_id: "probe"
        property QtObject wifi: QtObject { property bool powered: true; function scan() {} }
        property QtObject mNetworkManager: QtObject { property string state: "online"; function getTechnology(name) { return global.wifi } }
        property QtObject screenState: QtObject { property int state: 1; signal stateChangedInt(int new_state); function enableState(s) {} function disableState(s) {} }
        property QtObject audioState: QtObject { property int state: 0; function isStateEnabled(s) { return false } function enableState(s) {} function disableState(s) {} }
        function relaunchConnman() {} function beep() {} function takeScreenshot() {}
    }
    Settings { id: page; _pageName: "Settings" }

    property variant addresses: @ADDRESSES@
    property Item tab: null
    property Item view: null

    function find(item, test) {
        if (test(item)) return item
        var kids = item.children
        for (var i = 0; kids && i < kids.length; i++) {
            var hit = find(kids[i], test)
            if (hit) return hit
        }
        return null
    }
    function inside(item, ancestor) {
        for (var at = item; at; at = at.parent) if (at === ancestor) return true
        return false
    }
    function texts(item, out) {
        if (!item.visible || item.opacity === 0) return out
        if (item.paintedWidth !== undefined && item.text !== undefined && item.text !== "") {
            var at = item.mapToItem(probeRoot, 0, 0)
            var shift = item.horizontalAlignment === Text.AlignHCenter ? (item.width - item.paintedWidth) / 2
                : item.horizontalAlignment === Text.AlignRight ? item.width - item.paintedWidth : 0
            out.push({text: item.text, name: "" + item.objectName, left: at.x + shift, right: at.x + shift + item.paintedWidth,
                      top: at.y, bottom: at.y + item.paintedHeight, width: item.width, lines: item.lineCount,
                      truncated: item.truncated, scrolls: inside(item, view)})
        }
        var kids = item.children
        for (var i = 0; kids && i < kids.length; i++) texts(kids[i], out)
        return out
    }
    function report(stage) {
        var column = view.contentItem.children[0]
        var origin = column.mapToItem(probeRoot, 0, 0)
        var window = view.mapToItem(probeRoot, 0, 0)
        var whole = tab.mapToItem(probeRoot, 0, 0)
        console.log("C300X_TAB_QT4 " + JSON.stringify({stage: stage, column: [origin.x, origin.x + column.width],
            view: [window.y, window.y + view.height], panel: [whole.x, whole.y, whole.x + tab.width, whole.y + tab.height],
            content: view.contentHeight, scrolled: view.contentY, status: tab.status, problem: tab.problem,
            reachable: tab.reachable, texts: texts(tab, [])}))
    }
    Timer {
        property int step: 0
        interval: 250; repeat: true; running: true
        onTriggered: {
            step++
            if (step === 1) page.aboutToShow()
            if (step !== 10) return
            tab = find(page, function(item) { return typeof item.readStatus === "function" && typeof item.ask === "function" })
            if (!tab) { console.log("C300X_TAB_QT4_MISSING"); running = false; return }
            view = find(tab, function(item) { return item.contentY !== undefined && item.contentHeight !== undefined })
            report("first")
            var kept = tab.address
            for (var i = 0; i < addresses.length; i++) {
                tab.address = addresses[i]
                report("address " + addresses[i])
            }
            tab.address = kept
            if (@SWITCH@) tab.setDisplay("dashboard_prevent_return", "on")
            running = false
            last.start()
        }
    }
    Timer {
        id: last
        interval: 1200
        onTriggered: {
            report("switch")
            view.contentY = Math.max(0, view.contentHeight - view.height)
            report("end")
            if (!@END@) view.contentY = 0
            console.log("C300X_TAB_QT4_DONE")
        }
    }
}
