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
            item.generation = "@RELEASE@".substring(7)
            item.running = true
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
