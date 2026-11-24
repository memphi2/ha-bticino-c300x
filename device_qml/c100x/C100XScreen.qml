import QtQuick 2.7

FocusScope {
    id: screen
    width: 800
    height: 480
    focus: true
    property int count: 1
    property int currentIndex: 0
    property string pageName: ""
    readonly property bool failed: body.status === Loader.Error
    property alias pageItem: body.item
    signal exitRequested()
    function known(name) { return ["HomeAssistant.qml", "Alarm.qml"].indexOf(name) >= 0 }
    function openPage(name) { if (!c100xHost.blocked && known(name)) pageName = name }
    function goBack() {
        if (pageName === "Alarm.qml" && c100xHost.entryPage === "HomeAssistant.qml") pageName = "HomeAssistant.qml"
        else exitRequested()
    }
    Component.onCompleted: if (known(c100xHost.entryPage)) pageName = c100xHost.entryPage
    Loader {
        id: body
        anchors.fill: parent
        active: screen.visible && !c100xHost.blocked && screen.pageName !== ""
        source: screen.pageName
        focus: true
        onLoaded: item.forceActiveFocus()
    }
    Connections {
        target: body.item
        ignoreUnknownSignals: true
        onBack: screen.goBack()
        onAlarmRequested: screen.openPage("Alarm.qml")
    }
    Connections {
        target: c100xHost
        onBlockedChanged: if (c100xHost.blocked && screen.known(c100xHost.entryPage)) screen.pageName = c100xHost.entryPage
    }
}
