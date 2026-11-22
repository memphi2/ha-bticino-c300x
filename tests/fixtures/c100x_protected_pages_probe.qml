import QtQuick 2.7
import "js/c300x_alerts.js" as Controller

Item {
    id: window
    width: 800; height: 480
    property var activeFocusItem: null
    QtObject {
        id: global
        property bool beepEnabled: true
        property bool blockKeyboard: false
        property int commissioningStatus: 3
        property QtObject networkInfo: QtObject { property bool isSoftAp: false }
        property QtObject audioState: QtObject {
            property bool isRingtoneMute: false
            function enableState(state) { isRingtoneMute = true }
            function disableState(state) { isRingtoneMute = false }
        }
        property QtObject screenState: QtObject {
            property int state: 0
            property int screensaverInterval: 10000
            property int clicks: 0
            signal stateChangedInt(int previous, int current)
            function simulateClick() { clicks++; state = 1 }
            function disableState(value) { state = 0 }
        }
    }
    Item { id: eventManager; property bool callInProgress: false; property bool callActive: false }
    Item {
        id: home
        property bool c100xAvailable: true
        signal regulationState(bool state)
        function syncC100xMenu() {}
    }
    Item { id: vendorSettings }
    QtObject {
        id: mainStackView
        property int depth: 0
        property var currentItem: null
        function get(index) { return index === 0 ? home : currentItem }
        function popPage() { currentItem = home; depth = 1 }
    }
    Item { id: sectionHeader }
    Item { id: pageIndicator }
@MAIN_HOOK@
    property var adapter: null
    function showAdapter(name) {
        if (!adapter) adapter = c100xPage.createObject(window)
        mainStackView.depth = 2
        mainStackView.currentItem = adapter
        adapter.item.openPage(name)
    }
    function showVendor() { mainStackView.depth = 2; mainStackView.currentItem = vendorSettings }
    function showHome() { mainStackView.currentItem = home; mainStackView.depth = 1 }
    function state() {
        return {blocked: c100xAlerts.item.blocked, coreBlocked: c100xHost.blocked,
                notice: !!c100xAlerts.item.notice, clicks: global.screenState.clicks}
    }
    function receive(command) { return Controller.runtimeFor(c100xAlerts.item).controller.receive(command) }
}
