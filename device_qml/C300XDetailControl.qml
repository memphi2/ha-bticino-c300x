import QtQuick 1.1
import Components 1.0
import Components.Styles 1.0

Item {
    id: controlRow
    property variant control: ({})
    property variant hostPage: null
    property bool paletteTab: false
    property real preview: initialValue()
    property int touchHeight: 56
    property int headingHeight: paletteTab ? 0 : 28
    signal submitted(variant value)
    signal adjusted(int direction)
    signal refreshRequested()

    function initialValue() {
        return hostPage && control.kind === "number" ? (hostPage.controlValueUnset(control) ? control.min : Number(control.value)) : 0
    }

    function choiceColumns() {
        var options = control.options || []
        if (!hostPage) return 1
        if (control.swatches) return Math.max(1, Math.min(4, Math.floor((width + 8) / 148)))
        var longest = 0
        for (var i = 0; i < options.length; i++) {
            longest = Math.max(longest, hostPage.optionLabel(control, options[i], i).length)
        }
        var minimumWidth = longest > 44 ? 520 : longest > 18 ? 300 : 140
        return Math.max(1, Math.min(options.length, Math.floor((width + 8) / (minimumWidth + 8))))
    }

    function numericRangeValid() {
        return control.kind === "number" && isFinite(control.min) && isFinite(control.max) &&
                isFinite(control.step) && control.max > control.min && control.step > 0
    }

    function updatePreview(x, trackWidth) {
        if (!hostPage || !numericRangeValid() || trackWidth <= 0) return
        var ratio = Math.max(0, Math.min(1, x / trackWidth))
        var steps = Math.min(hostPage.controlLastStep(control), Math.round(ratio * (control.max - control.min) / control.step))
        preview = Number((control.min + steps * control.step).toFixed(6))
    }

    function canAdjust(direction) {
        if (!hostPage || !numericRangeValid() || hostPage.controlValueUnset(control)) return false
        var step = Math.round((Number(control.value) - control.min) / control.step)
        return direction < 0 ? step > 0 : step < hostPage.controlLastStep(control)
    }

    onControlChanged: if (hostPage && sliderMouse && !sliderMouse.pressed) preview = initialValue()
    height: control.kind === "choice" ? headingHeight + optionGrid.height : control.kind === "number" ? 28 + touchHeight + (presetGrid.visible ? presetGrid.height + 8 : 0) : touchHeight
    opacity: enabled ? 1 : 0.45

    Image {
        visible: control.kind === "button"
        anchors.fill: parent
        source: controlButtonMouse.pressed ? "images/settings/list_btn_p.svg" : "images/settings/list_btn.svg"
        fillMode: Image.Stretch
    }
    UbuntuLightText {
        visible: !controlRow.paletteTab
        width: control.kind === "boolean" ? parent.width - 144 : parent.width
        height: control.kind === "button" || control.kind === "boolean" ? touchHeight : 24
        text: hostPage ? hostPage.controlLabel(control) + (control.kind === "number" ? ": " + (sliderMouse.pressed ? hostPage.numberText(control, preview) : hostPage.controlValue(control)) : "") : ""
        textFormat: Text.PlainText
        font.pixelSize: 18
        color: "white"
        wrapMode: control.kind === "button" || control.kind === "boolean" ? Text.Wrap : Text.NoWrap
        elide: Text.ElideRight
        horizontalAlignment: control.kind === "button" ? Text.AlignHCenter : Text.AlignLeft
        verticalAlignment: control.kind === "button" || control.kind === "boolean" ? Text.AlignVCenter : Text.AlignTop
    }
    Grid {
        id: presetGrid
        visible: control.kind === "number" && (control.presets || []).length > 0
        anchors.top: parent.top; anchors.topMargin: 28
        width: parent.width
        columns: Math.max(1, Math.min(4, (control.presets || []).length))
        spacing: 8
        Repeater {
            model: control.presets || []
            Item {
                property variant preset: modelData
                width: (presetGrid.width - (presetGrid.columns - 1) * 8) / presetGrid.columns
                height: touchHeight
                Image { anchors.fill: parent; source: presetMouse.pressed ? "images/settings/list_btn_p.svg" : control.active !== false && control.value === preset.value ? "images/settings/list_btn.svg" : "images/settings/act_btn.svg"; fillMode: Image.Stretch }
                UbuntuLightText {
                    anchors.fill: parent; anchors.margins: 6
                    text: hostPage ? hostPage.uiText(preset.label) : ""; textFormat: Text.PlainText; font.pixelSize: 16; color: "white"
                    wrapMode: Text.Wrap; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                }
                BeepingMouseArea { id: presetMouse; anchors.fill: parent; onClicked: controlRow.submitted(String(preset.value)) }
            }
        }
    }
    Item {
        id: numericControls
        visible: control.kind === "number"
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: touchHeight
        Repeater {
            model: [-1, 1]
            Item {
                property int direction: modelData
                x: direction < 0 ? 0 : numericControls.width - width
                width: 64; height: touchHeight
                enabled: controlRow.canAdjust(direction)
                opacity: enabled ? 1 : 0.45
                Image { anchors.fill: parent; source: adjustMouse.pressed ? "images/settings/list_btn_p.svg" : "images/settings/list_btn.svg"; fillMode: Image.Stretch }
                UbuntuLightText { anchors.centerIn: parent; text: direction < 0 ? "-" : "+"; font.pixelSize: 28; color: "white" }
                BeepingMouseArea { id: adjustMouse; anchors.fill: parent; onClicked: controlRow.adjusted(direction) }
            }
        }
        Item {
            anchors.left: parent.left; anchors.right: parent.right
            anchors.leftMargin: 80; anchors.rightMargin: 80
            height: touchHeight
            enabled: controlRow.numericRangeValid()
            Rectangle { width: parent.width; height: 5; anchors.verticalCenter: parent.verticalCenter; color: "#c7d0d9" }
            Rectangle {
                width: 28; height: 36; radius: 4
                color: "#58d68d"
                opacity: (!hostPage || hostPage.controlValueUnset(control)) && !sliderMouse.pressed ? 0.45 : 1
                anchors.verticalCenter: parent.verticalCenter
                x: controlRow.numericRangeValid() ? Math.max(0, Math.min(parent.width - width, (preview - control.min) / (control.max - control.min) * (parent.width - width))) : 0
            }
            BeepingMouseArea {
                id: sliderMouse
                anchors.fill: parent
                onPressed: { hostPage.interactionActive = true; controlRow.updatePreview(mouse.x, width) }
                onPositionChanged: if (pressed) controlRow.updatePreview(mouse.x, width)
                onReleased: {
                    hostPage.interactionActive = false
                    controlRow.submitted(String(preview))
                }
                onCanceled: {
                    hostPage.interactionActive = false
                    preview = controlRow.initialValue()
                    controlRow.refreshRequested()
                }
            }
        }
    }
    Grid {
        id: optionGrid
        visible: control.kind === "choice"
        anchors.top: parent.top; anchors.topMargin: headingHeight
        width: parent.width
        columns: controlRow.choiceColumns()
        spacing: 8
        height: Math.max(0, Math.ceil((control.options || []).length / columns) * (touchHeight + 8) - 8)
        Repeater {
            model: control.options || []
            Item {
                width: (optionGrid.width - (optionGrid.columns - 1) * 8) / optionGrid.columns
                height: touchHeight
                Image { anchors.fill: parent; source: optionMouse.pressed ? "images/settings/list_btn_p.svg" : control.value === modelData ? "images/settings/list_btn.svg" : "images/settings/act_btn.svg"; fillMode: Image.Stretch }
                Rectangle {
                    visible: control.swatches !== undefined
                    anchors.left: parent.left; anchors.leftMargin: 8; anchors.verticalCenter: parent.verticalCenter
                    width: 28; height: 28; radius: 3
                    color: control.swatches ? control.swatches[index] : "transparent"
                    border.width: control.value === modelData ? 3 : 1
                    border.color: "white"
                }
                UbuntuLightText {
                    anchors.fill: parent; anchors.margins: 6; anchors.leftMargin: control.swatches ? 42 : 6
                    text: hostPage ? hostPage.optionLabel(control, modelData, index) : ""; textFormat: Text.PlainText; font.pixelSize: 18; color: "white"
                    wrapMode: Text.Wrap; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                }
                BeepingMouseArea { id: optionMouse; anchors.fill: parent; onClicked: controlRow.submitted(modelData) }
            }
        }
    }
    Item {
        visible: control.kind === "boolean"
        anchors.right: parent.right; width: 136; height: touchHeight; opacity: booleanMouse.pressed ? 0.6 : 1
        Rectangle { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; width: 30; height: 30; radius: 3; color: control.value === true ? "#58d68d" : "transparent"; border.color: !hostPage || hostPage.controlValueUnset(control) ? "#f1c40f" : "white"; border.width: 2 }
        UbuntuLightText { anchors.left: parent.left; anchors.leftMargin: 44; anchors.verticalCenter: parent.verticalCenter; text: !hostPage || hostPage.controlValueUnset(control) ? "?" : hostPage.uiText(control.value ? "on" : "off"); font.pixelSize: 18; color: "white" }
        BeepingMouseArea { id: booleanMouse; anchors.fill: parent; onClicked: controlRow.submitted(control.value === true ? "false" : "true") }
    }
    BeepingMouseArea {
        id: controlButtonMouse
        visible: control.kind === "button"
        anchors.fill: parent
        onClicked: controlRow.submitted(null)
    }
}
