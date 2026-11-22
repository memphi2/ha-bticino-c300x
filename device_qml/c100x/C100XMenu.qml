import QtQuick 2.7
import "js/c300x_ha.js" as Api
import "js/c100x_text.js" as Labels

C100XPage {
    id: menu
    headerLabel: "Home Assistant"
    property bool alarmAvailable: false
    property bool dashboardAvailable: false
    property int generation: 0
    signal openPage(string name)
    onBackClicked: back()
    function aboutToShow() {
        var current = ++generation
        Api.homeButtons(function(alarm, dashboard) {
            if (current !== generation || !menu.visible || c100xHost.blocked) return
            alarmAvailable = alarm
            dashboardAvailable = dashboard
        })
    }
    function aboutToHide() { generation++; alarmAvailable = false; dashboardAvailable = false }
    Column {
        x: 24; y: 70; width: parent.width - 48; spacing: 12
        Repeater {
            model: ["HomeAssistant.qml", "Alarm.qml", "C100XSettings.qml", "C100XMemos.qml"]
            Rectangle {
                width: parent.width; height: 76
                color: index === 1 ? "#123a69" : "#244a59"
                enabled: index === 0 ? menu.dashboardAvailable : index === 1 ? menu.alarmAvailable : true
                opacity: enabled ? 1 : 0.45
                C100XText {
                    anchors.fill: parent; anchors.margins: 16
                    verticalAlignment: Text.AlignVCenter
                    text: index === 0 ? "Home Assistant" : index === 1 ? "Alarmo" : Labels.label(c100xHost.language, index === 2 ? "settings" : "memos")
                    color: "white"; font.pixelSize: 26; elide: Text.ElideRight
                }
                C100XAction { anchors.fill: parent; onClicked: menu.openPage(modelData) }
            }
        }
    }
}
