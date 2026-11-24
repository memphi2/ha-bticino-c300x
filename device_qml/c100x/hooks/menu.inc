    property bool c100xAvailable: typeof c100xHost !== "undefined" && !!c100xHost
        && c100xHost.vendorReady && c100xHost.running
    property bool c100xHomeShown: c100xAvailable && c100xHost.homeAvailable === true
    property bool c100xAlarmShown: c100xAvailable && c100xHost.alarmAvailable === true
    onC100xHomeShownChanged: syncC100xMenu()
    onC100xAlarmShownChanged: syncC100xMenu()
    ListModel { id: c100xMenu }
    Connections {
        target: listModel
        onCountChanged: root.syncC100xMenu()
    }
    function c100xRow(entry, key) {
        var row = {c100xKey: key, sourceImg: entry.sourceImg || "", component: entry.component}
        if (entry.payload) row.payload = entry.payload
        return row
    }
    function syncC100xMenu() {
        if (typeof c100xHost === "undefined" || listModel.count === 0) return
        var rows = []
        for (var i = 0; i < listModel.count; i++) {
            var entry = listModel.get(i)
            rows.push(c100xRow(entry, "stock:" + (entry.sourceImg || "")))
            if (entry.sourceImg !== "images/Ringtone.svg") continue
            if (c100xHomeShown) rows.push(c100xRow({sourceImg: "@RELEASE@/C100XHome.svg", component: c100xEntry,
                payload: {pageName: "c100x", page: "HomeAssistant.qml", label: "Home Assistant"}}, "c100x:home"))
            if (c100xAlarmShown) rows.push(c100xRow({sourceImg: "@RELEASE@/C100XAlarm.svg", component: c100xEntry,
                payload: {pageName: "c100x", page: "Alarm.qml", label: "Alarmo"}}, "c100x:alarm"))
        }
        var at = 0
        while (at < rows.length) {
            var key = at < c100xMenu.count ? c100xMenu.get(at).c100xKey : null
            if (key === rows[at].c100xKey) { at++; continue }
            var kept = false
            for (var j = at; key !== null && j < rows.length && !kept; j++) kept = rows[j].c100xKey === key
            if (key !== null && !kept) c100xMenu.remove(at)
            else {
                c100xMenu.insert(at, rows[at])
                at++
            }
        }
        while (c100xMenu.count > rows.length) c100xMenu.remove(rows.length)
        if (listView.model !== c100xMenu) {
            var current = listView.currentIndex
            listView.model = c100xMenu
            listView.currentIndex = current
        }
    }
    Component {
        id: c100xEntry
        Item {
            function returnPressed() {
                if (!root.c100xAvailable || c100xHost.blocked) return
                c100xHost.entryPage = payload.page
                root.navigateTo("c100x", "")
            }
            Image { id: c100xIcon; source: sourceImg; anchors.centerIn: parent }
            Text {
                anchors.top: c100xIcon.bottom; anchors.topMargin: 15; anchors.horizontalCenter: c100xIcon.horizontalCenter
                text: payload.label; font.pixelSize: 27; font.bold: true; color: "white"
            }
        }
    }
