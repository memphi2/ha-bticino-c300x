import QtQuick 2.7
import "js/c300x_i18n.js" as I18n
import "js/c100x_text.js" as Labels

C100XPage {
    id: page
    headerLabel: Labels.label(c100xHost.language, "settings")
    onBackClicked: back()
    function aboutToShow() { c100xHost.preferences.load() }
    Column {
        x: 24; y: 80; width: parent.width - 48; spacing: 20
        Repeater {
            model: ["ha_feedback_colors", "touch_tone"]
            Rectangle {
                width: parent.width; height: 90; color: "#244a59"
                enabled: index === 0 ? c100xHost.preferences.ready && !c100xHost.preferences.busy : c100xHost.vendorReady
                opacity: enabled ? 1 : 0.45
                C100XText {
                    x: 16; y: 12; width: parent.width - 100; height: parent.height - 24
                    text: index === 0 ? I18n.text(c100xHost.language, modelData) : Labels.label(c100xHost.language, "tone")
                    font.pixelSize: 24; color: "white"; wrapMode: Text.Wrap; verticalAlignment: Text.AlignVCenter
                }
                Rectangle {
                    x: parent.width - 64; y: 28; width: 34; height: 34; border.color: "white"; border.width: 2
                    color: (index === 0 ? c100xHost.preferences.feedbackEnabled : c100xHost.touchToneEnabled) ? "#58d68d" : "transparent"
                }
                C100XAction {
                    anchors.fill: parent
                    onClicked: {
                        if (index === 0) c100xHost.preferences.setFeedbackEnabled(!c100xHost.preferences.feedbackEnabled)
                        else c100xHost.setTouchTone(!c100xHost.touchToneEnabled)
                    }
                }
            }
        }
    }
}
