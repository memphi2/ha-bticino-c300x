import QtQuick 2.7

Item {
    id: root
    width: 800; height: 480
    property QtObject c100xHost: QtObject {
        property bool vendorReady: true
        property bool running: true
        property bool blocked: false
        property bool homeAvailable: true
        property bool alarmAvailable: true
        property string entryPage: ""
    }
    signal navigateTo(string pageName, url imageUrl)
    QtObject {
        id: listView
        property var model: listModel
        property int currentIndex: 0
    }
    ListModel {
        id: listModel
        Component.onCompleted: {
            append({sourceImg: "images/Ringtone.svg", payload: {prop: "volume"}})
            append({sourceImg: "images/settings.svg", payload: {pageName: "settings"}})
            append({sourceImg: "images/Exit.svg"})
            root.syncC100xMenu()
        }
    }
@MENU_HOOK@
    function order() {
        var out = []
        for (var i = 0; i < listView.model.count; i++) out.push(listView.model.get(i).c100xKey || listView.model.get(i).sourceImg)
        return out.join(" ")
    }
    function exercise() {
        if (listView.model === listModel) throw new Error("carousel does not show the adapter's list")
        if (order() !== "stock:images/Ringtone.svg c100x:home c100x:alarm stock:images/settings.svg stock:images/Exit.svg")
            throw new Error("entries not placed after the ringtone: " + order())
        if (listModel.count !== 3) throw new Error("vendor list changed")
        syncC100xMenu()
        if (listView.model.count !== 5) throw new Error("duplicate entry")
        c100xHost.homeAvailable = false
        if (order() !== "stock:images/Ringtone.svg c100x:alarm stock:images/settings.svg stock:images/Exit.svg")
            throw new Error("dashboard entry left behind: " + order())
        listModel.insert(1, {sourceImg: "images/Professional studio.svg", payload: {prop: "autoOpen"}})
        if (order() !== "stock:images/Ringtone.svg c100x:alarm stock:images/Professional studio.svg stock:images/settings.svg stock:images/Exit.svg")
            throw new Error("vendor insert not followed: " + order())
        c100xHost.running = false
        if (listView.model.count !== 4) throw new Error("failed bridge left an entry")
        c100xHost.running = true
        if (listView.model.count !== 5) throw new Error("bridge recovery lost the entry")
        c100xHost = null
        if (listView.model.count !== 4 || listModel.count !== 4) throw new Error("missing bridge left an entry")
    }
}
