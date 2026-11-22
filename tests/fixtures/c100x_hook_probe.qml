import QtQuick 2.7

Item {
    id: window
    width: 800; height: 480
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
    }
    QtObject {
        id: eventManager
        property bool callInProgress: false
        property bool callActive: false
    }
    QtObject { id: mainStackView; property int pops: 0; function popPage() { pops++ } }
@MAIN_HOOK@
    function exercise() {
        if (!c100xHost || !c100xHost.running || !c100xHost.vendorReady || c100xHost.blocked)
            throw new Error("stock hook did not initialize bridge")
        var page = c100xPage.createObject(window)
        if (!page || !page.item || page.item.failed) throw new Error("stock hook did not load screen")
        page.item.exitRequested()
        if (mainStackView.pops !== 1) throw new Error("back did not reach vendor stack")
        page.destroy()
    }
}
