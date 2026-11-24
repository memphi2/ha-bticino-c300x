    property var c100xHost: c100xBridge.item
    property bool c100xFullScreenActive: !!mainStackView.currentItem
        && mainStackView.currentItem.hasOwnProperty("c100xFullScreen")
        && mainStackView.currentItem.c100xFullScreen
    property bool c100xChromeHidden: false
    property bool c100xHeaderWasVisible: true
    property bool c100xIndicatorWasVisible: true
    onC100xFullScreenActiveChanged: {
        if (c100xFullScreenActive && !c100xChromeHidden) {
            c100xHeaderWasVisible = sectionHeader.visible
            c100xIndicatorWasVisible = pageIndicator.visible
            c100xChromeHidden = true
            sectionHeader.visible = false
            pageIndicator.visible = false
        } else if (!c100xFullScreenActive && c100xChromeHidden) {
            sectionHeader.visible = c100xHeaderWasVisible
            pageIndicator.visible = c100xIndicatorWasVisible
            c100xChromeHidden = false
        }
    }
    Loader {
        id: c100xBridge
        source: "@RELEASE@/C100XBridge.qml"
        onLoaded: {
            item.vendor = global
            item.events = eventManager
            item.muteState = AudioState.RingtoneMute
            item.commissionedState = Commissioning.Commissioned
            item.normalState = ScreenState.Normal
            item.offState = ScreenState.ScreenOff
            item.focusWindow = window
            item.displayReady = Qt.binding(function() {
                return c100xReady.status === Loader.Ready && c100xReady.item.ready
                    && c100xAlerts.status === Loader.Ready && c100xAlerts.item.screenReady
            })
            item.generation = "@RELEASE@".substring(7)
            item.running = true
        }
    }
    Loader {
        id: c100xReady
        source: "@RELEASE@/C100XReady.qml"
    }
    Loader {
        id: c100xAlerts
        anchors.fill: parent
        z: 100
        active: !!c100xHost && c100xHost.running
        source: "@RELEASE@/C300XAlerts.qml"
        Keys.forwardTo: [eventManager]
    }
    function c100xSyncSettings() {
        var page = mainStackView.currentItem
        var view = page && page.children && page.children.length > 0 ? page.children[0] : null
        var model = view ? view.model : null
        if (!model || typeof model.get !== "function" || typeof model.insert !== "function" || model.count < 4) return
        var last = model.get(model.count - 1)
        var second = model.get(1).payload
        if (!second || second.pageName !== "wifiReset" || last.sourceImg !== "images/Exit.svg") return
        var ready = !!c100xHost && c100xHost.running && c100xHost.vendorReady
        if (ready) c100xHost.preferences.load()
        var wanted = ready && c100xHost.preferences.ready
        for (var i = 0; i < model.count; i++) {
            var payload = model.get(i).payload
            if (payload && payload.c100x === true) {
                if (!wanted) model.remove(i)
                return
            }
        }
        if (wanted) model.insert(model.count - 1, {sourceImg: "@RELEASE@/C100XStatus.svg", component: c100xStatusItem,
            payload: {c100x: true, obj: c100xHost.feedbackToggle, prop: "on"}})
    }
    Connections {
        target: mainStackView
        onCurrentItemChanged: window.c100xSyncSettings()
    }
    Connections {
        target: c100xHost
        ignoreUnknownSignals: true
        onReadyChanged: window.c100xSyncSettings()
        onRunningChanged: window.c100xSyncSettings()
        onVendorReadyChanged: window.c100xSyncSettings()
    }
    Component {
        id: c100xStatusItem
        Loader {
            source: "@RELEASE@/C100XStatusItem.qml"
            function returnPressed() { if (item) item.returnPressed() }
        }
    }
    Component {
        id: c100xPage
        Loader {
            width: 800; height: 480
            focus: true
            property int count: 1
            property int currentIndex: 0
            property bool menuVisible: false
            property bool c100xFullScreen: true
            source: "@RELEASE@/C100XScreen.qml"
            onLoaded: item.exitRequested.connect(function() { mainStackView.popPage() })
        }
    }
