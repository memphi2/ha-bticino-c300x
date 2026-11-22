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
    Item {
        id: eventManager
        property bool callInProgress: false
        property bool callActive: false
    }
    QtObject {
        id: mainStackView
        property int pops: 0
        property var currentItem: null
        property int depth: 2
        property var iconList: ["vendor"]
        function popPage() { pops++ }
    }
    QtObject { id: vctModel; property QtObject vct: QtObject { property bool callInProgress: false } }
    Item { id: sectionHeader; property bool shown: false; property string imageUrl: "" }
    Item { id: pageIndicator; property bool shown: false }
    QtObject { id: showSectionHeader; function start() { sectionHeader.shown = true } }
    QtObject { id: showPageIndicator; function start() { pageIndicator.shown = true } }
    QtObject { id: hidePageIndicator; function start() { pageIndicator.shown = false } }
    Component { id: vendorPage; Item {} }
    function nativeArrival() {
@VENDOR_ARRIVAL@
    }
    function nativePopArrival() {
@VENDOR_POP_ARRIVAL@
    }
@MAIN_HOOK@
    function exercise() {
        if (!c100xHost || !c100xHost.running || !c100xHost.vendorReady || c100xHost.blocked)
            throw new Error("stock hook did not initialize bridge")
        var page = c100xPage.createObject(window)
        if (!page || !page.item || page.item.failed) throw new Error("stock hook did not load screen")
        mainStackView.currentItem = page
        nativeArrival()
        if ((sectionHeader.shown && sectionHeader.visible) || (pageIndicator.shown && pageIndicator.visible))
            throw new Error("vendor arrival chrome overlays C100X page")
        nativePopArrival()
        if ((sectionHeader.shown && sectionHeader.visible) || (pageIndicator.shown && pageIndicator.visible))
            throw new Error("vendor pop chrome overlays C100X page")
        page.item.exitRequested()
        if (mainStackView.pops !== 1) throw new Error("back did not reach vendor stack")
        var normal = vendorPage.createObject(window)
        mainStackView.currentItem = normal
        nativeArrival()
        if (!sectionHeader.visible || !pageIndicator.visible || !sectionHeader.shown || !pageIndicator.shown)
            throw new Error("C100X hook changed normal vendor chrome")
        sectionHeader.visible = false
        pageIndicator.visible = false
        mainStackView.currentItem = page
        mainStackView.currentItem = normal
        if (sectionHeader.visible || pageIndicator.visible)
            throw new Error("hook did not restore pre-existing vendor visibility")
        normal.destroy()
        page.destroy()
    }
}
