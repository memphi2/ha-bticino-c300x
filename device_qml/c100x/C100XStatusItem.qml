import QtQuick 2.7
import "js/c100x_text.js" as Labels

Item {
    id: entry
    function returnPressed() {
        if (toggle.status === Loader.Ready && !c100xHost.blocked && c100xHost.preferences.ready && !c100xHost.preferences.busy)
            toggle.item.returnPressed()
    }
    Loader {
        id: toggle
        anchors.fill: parent
        source: "../Components/ToggleItem.qml"
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.verticalCenter
        anchors.topMargin: 110
        text: Labels.label(c100xHost.language, "status")
        color: "white"
        font.pixelSize: 24
    }
}
