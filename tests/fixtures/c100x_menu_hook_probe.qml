import QtQuick 2.7

Item {
    id: root
    width: 800; height: 480
    property QtObject c100xHost: QtObject {
        property bool vendorReady: true
        property bool running: true
        property bool blocked: false
    }
    signal navigateTo(string pageName, url imageUrl)
    ListModel {
        id: listModel
        Component.onCompleted: {
            append({payload: {pageName: "settings"}})
            append({payload: {pageName: "exit"}})
            root.syncC100xMenu()
        }
    }
@MENU_HOOK@
    function exercise() {
        if (listModel.count !== 3 || listModel.get(1).payload.pageName !== "c100x")
            throw new Error("extra menu entry not placed before Exit")
        syncC100xMenu()
        if (listModel.count !== 3) throw new Error("duplicate menu entry")
        c100xHost.running = false
        if (listModel.count !== 2) throw new Error("failed bridge left menu entry")
        c100xHost.running = true
        if (listModel.count !== 3) throw new Error("bridge recovery lost menu entry")
        c100xHost = null
        if (listModel.count !== 2) throw new Error("stock main did not disable menu hook")
    }
}
