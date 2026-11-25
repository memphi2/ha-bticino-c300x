    property bool c100xAvailable: typeof c100xHost !== "undefined" && !!c100xHost
        && c100xHost.vendorReady && c100xHost.running
    onC100xAvailableChanged: syncC100xMenu()
    function syncC100xMenu() {
        if (!listModel || listModel.count === 0) return
        for (var i = 0; i < listModel.count; i++) {
            var entry = listModel.get(i)
            if (entry.payload && entry.payload.pageName === "c100x") {
                if (!c100xAvailable) listModel.remove(i)
                return
            }
        }
        if (c100xAvailable)
            listModel.insert(Math.max(0, listModel.count - 1), {component: c100xMenuItem, payload: {pageName: "c100x"}})
    }
    Component {
        id: c100xMenuItem
        Item {
            function returnPressed() { if (root.c100xAvailable && !c100xHost.blocked) root.navigateTo("c100x", "") }
            Image { id: c100xIcon; source: "images/Info.svg"; anchors.centerIn: parent }
            Text {
                anchors.top: c100xIcon.bottom; anchors.topMargin: 20; anchors.horizontalCenter: parent.horizontalCenter
                text: "Home Assistant"; font.pixelSize: 27; color: "white"
            }
        }
    }
