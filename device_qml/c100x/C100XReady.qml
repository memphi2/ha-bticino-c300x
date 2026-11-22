import QtQuick 2.7

Item {
    id: preflight
    property bool ready: false
    property var components: []
    Component.onCompleted: {
        var names = ["Alarm.qml", "HomeAssistant.qml", "C100XMenu.qml", "C100XScreen.qml", "C100XSettings.qml", "C100XMemos.qml",
            "C300XAgenda.qml", "C300XChecks.qml", "C300XDetailControl.qml", "C300XEnergy.qml", "C300XEnergyConsumers.qml",
            "C300XEnergyReadout.qml", "C300XEnergySums.qml", "C300XLeaveHome.qml", "C300XOptionalPages.qml",
            "C300XPageNavigation.qml", "C300XSituations.qml"]
        var loaded = []
        for (var i = 0; i < names.length; i++) {
            var component = Qt.createComponent(names[i])
            if (component.status !== Component.Ready) return
            loaded.push(component)
        }
        components = loaded
        ready = true
    }
}
