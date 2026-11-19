import QtQuick 1.1

Item {
    id: root
    property variant energy: ({})
    property variant agenda: ({})
    property variant leaveHome: ({})
    property variant situations: ({})
    property bool energyVisible: false
    property bool agendaVisible: false
    property bool leaveHomeVisible: false
    property bool situationsVisible: false
    property bool busy: false
    property bool online: true
    signal actionRequested(variant item)
    signal alarmRequested()
    Loader {
        id: energyLoader
        anchors.fill: parent
        source: root.energyVisible ? "C300XEnergy.qml" : ""
    }
    Binding {
        target: energyLoader.item
        property: "energy"
        value: root.energy
        when: energyLoader.status === Loader.Ready
    }
    Loader {
        id: agendaLoader
        anchors.fill: parent
        source: root.agendaVisible ? "C300XAgenda.qml" : ""
    }
    Binding {
        target: agendaLoader.item
        property: "agenda"
        value: root.agenda
        when: agendaLoader.status === Loader.Ready
    }
    Loader {
        id: leaveHomeLoader
        anchors.fill: parent
        source: root.leaveHomeVisible ? "C300XLeaveHome.qml" : ""
    }
    Binding {
        target: leaveHomeLoader.item
        property: "leaveHome"
        value: root.leaveHome
        when: leaveHomeLoader.status === Loader.Ready
    }
    Binding {
        target: leaveHomeLoader.item
        property: "busy"
        value: root.busy
        when: leaveHomeLoader.status === Loader.Ready
    }
    Binding {
        target: leaveHomeLoader.item
        property: "online"
        value: root.online
        when: leaveHomeLoader.status === Loader.Ready
    }
    Connections {
        target: leaveHomeLoader.item
        onActionRequested: root.actionRequested(item)
        onAlarmRequested: root.alarmRequested()
    }
    Loader {
        id: situationsLoader
        anchors.fill: parent
        source: root.situationsVisible ? "C300XSituations.qml" : ""
    }
    Binding {
        target: situationsLoader.item
        property: "situations"
        value: root.situations
        when: situationsLoader.status === Loader.Ready
    }
}
