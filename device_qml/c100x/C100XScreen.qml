import QtQuick 2.7

FocusScope {
    id: screen
    width: 800
    height: 480
    focus: true
    property int count: 1
    property int currentIndex: 0
    property string pageName: "C100XMenu.qml"
    readonly property bool failed: body.status === Loader.Error
    property alias pageItem: body.item
    signal exitRequested()
    function openPage(name) {
        if (c100xHost.blocked || ["C100XMenu.qml", "HomeAssistant.qml", "Alarm.qml", "C100XMemos.qml"].indexOf(name) < 0) return
        pageName = name
    }
    function goBack() {
        if (pageName === "C100XMenu.qml") exitRequested()
        else pageName = "C100XMenu.qml"
    }
    Loader {
        id: body
        anchors.fill: parent
        active: screen.visible && !c100xHost.blocked
        source: screen.pageName
        focus: true
        onLoaded: item.forceActiveFocus()
    }
    Connections {
        target: body.item
        ignoreUnknownSignals: true
        onBack: screen.goBack()
        onAlarmRequested: screen.openPage("Alarm.qml")
        onOpenPage: screen.openPage(name)
    }
    Connections {
        target: c100xHost
        onBlockedChanged: if (c100xHost.blocked) screen.pageName = "C100XMenu.qml"
    }
}
