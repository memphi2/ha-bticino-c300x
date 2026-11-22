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
