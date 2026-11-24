import QtQuick 2.7

FocusScope {
    id: frame
    width: 800; height: 480; focus: true
    property int submissions: 0
    property string submittedValue: ""
    property var pressedKeys: []
    property var releasedKeys: []
    Keys.onPressed: { pressedKeys = pressedKeys.concat([event.key]); event.accepted = true }
    Keys.onReleased: { releasedKeys = releasedKeys.concat([event.key]); event.accepted = true }
    property QtObject c100xHost: QtObject {
        property bool blocked: false
        property string language: "en"
        property QtObject preferences: QtObject {
            property bool feedbackEnabled: true
            function load() {}
        }
    }
    HomeAssistant { id: helper; visible: false }
    C100XPage {
        id: page
        C300XDetailControl {
            id: detail
            y: 70; width: 760; hostPage: helper
            control: ({kind: "number", command: "temperature", min: 15, max: 30, step: 0.5, value: 21.5})
            onSubmitted: { frame.submissions++; frame.submittedValue = value }
        }
    }
    property var slider: null
    function selectSlider() {
        page.enter(false)
        for (var i = 0; i < 20 && page.selectedAction; i++) {
            if (page.selectedAction.objectName === "c100xNumericSlider") {
                slider = page.selectedAction
                page.forceActiveFocus()
                return
            }
            page.move(1)
        }
        throw new Error("numeric slider is unreachable")
    }
    function state() {
        return {editing: slider.keyboardEditing, preview: detail.preview, submissions: submissions,
                value: submittedValue, interaction: helper.interactionActive}
    }
}
