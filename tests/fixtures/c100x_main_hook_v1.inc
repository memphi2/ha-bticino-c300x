    property var c100xHost: c100xBridge.item
    Loader {
        id: c100xBridge
        source: "@RELEASE@/C100XBridge.qml"
        onLoaded: {
            item.vendor = global
            item.events = eventManager
            item.muteState = AudioState.RingtoneMute
            item.commissionedState = Commissioning.Commissioned
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
            source: "@RELEASE@/C100XScreen.qml"
            onLoaded: item.exitRequested.connect(function() { mainStackView.popPage() })
        }
    }
