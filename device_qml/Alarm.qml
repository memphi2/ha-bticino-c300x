import QtQuick 1.1
import Components 1.0
import Components.Styles 1.0
import BtObjects 2.0
import "js/c300x_ha.js" as Api
import "js/c300x_i18n.js" as I18n

Page {
    id: page
    showBackButton: true
    onBackClicked: tabView.activateTab(homePage)
    headerLabel: uiText("alarm") + trsl.empty
    onVisibleChanged: {
        if (visible) {
            startStatusWatch()
        } else {
            stopStatusWatch()
        }
    }

    property string uiLanguage: trsl.language
    property string pinCode: ""
    property string alarmRawState: "unknown"
    property bool alarmConfigured: false
    property string selectedCommand: "arm_home"
    property variant alarmCommands: ["arm_home", "arm_away", "arm_night"]
    property variant alarmCommandDetails: []
    property variant alarmOpenSensors: []
    property int alarmOpenSensorCount: 0
    property bool selectedCommandReady: true
    property bool selectedCommandBlockedBySensors: false
    property string selectedCommandStatus: ""
    property int alarmDelayRemaining: 0
    property bool bypassOffered: false
    property string commandFeedback: ""
    property string commandFeedbackColor: "#c7d0d9"
    property string activeFeedbackCommand: ""

    Timer {
        id: modeFeedbackTimer
        interval: 1000
        repeat: false
        onTriggered: activeFeedbackCommand = ""
    }

    function aboutToShow() {
        activeFeedbackCommand = ""
        clearCommandFeedback()
        Api.status(status, page, alarmState, activeSince)
        startStatusWatch()
    }

    function handleScreenOff() {
        return true
    }

    function startStatusWatch() {
        Api.startEventWatch(handleStatusEvent)
    }

    function stopStatusWatch() {
        Api.stopEventWatch()
    }

    function handleStatusEvent(event) {
        if (event && (event.topic === "alarm" || event.topic === "display_bridge.state")) {
            activeFeedbackCommand = ""
            clearCommandFeedback()
            Api.status(status, page, alarmState, activeSince)
        }
    }

    function appendDigit(digit) {
        if (pinCode.length < 10) {
            pinCode = pinCode + digit
        }
    }

    function clearPin() {
        pinCode = ""
    }

    function setCommandFeedback(key, command, color) {
        commandFeedback = uiText(key)
        if (command && command.length > 0) {
            commandFeedback = commandFeedback + ": " + commandLabel(command)
        }
        commandFeedbackColor = color
        flashCommandButton(command, color)
        status.text = commandFeedback
        status.color = color
    }

    function flashCommandButton(command, color) {
        if (!command || command.length === 0) {
            return
        }
        activeFeedbackCommand = command
        commandFeedbackColor = color
        modeFeedbackTimer.restart()
    }

    function clearCommandFeedback() {
        commandFeedback = ""
    }

    function refreshSoon() {
        delayedStatusRefresh.restart()
    }

    function setAlarmDelayRemaining(seconds) {
        var value = parseInt(seconds || 0, 10)
        if (isNaN(value)) {
            value = 0
        }
        alarmDelayRemaining = Math.max(0, value)
    }

    function pinMask() {
        return Array(pinCode.length + 1).join("*")
    }

    function commandLabel(command) {
        if (command === "arm_home") return uiText("armed_home")
        if (command === "arm_away") return uiText("armed_away")
        if (command === "arm_night") return uiText("armed_night")
        if (command === "arm_custom_bypass") return uiText("armed_custom_bypass")
        if (command === "arm_vacation") return uiText("armed_vacation")
        if (command === "disarm") return uiText("disarmed")
        return command
    }

    function commandTargetState(command) {
        if (command === "arm_home") return "armed_home"
        if (command === "arm_away") return "armed_away"
        if (command === "arm_night") return "armed_night"
        if (command === "arm_custom_bypass") return "armed_custom_bypass"
        if (command === "arm_vacation") return "armed_vacation"
        if (command === "disarm") return "disarmed"
        return ""
    }

    function isArmCommand(command) {
        return command.indexOf("arm_") === 0
    }

    function stateLabel() {
        if (alarmRawState === "disarmed") return uiText("disarmed")
        if (alarmRawState === "armed_home") return uiText("armed_home")
        if (alarmRawState === "armed_away") return uiText("armed_away")
        if (alarmRawState === "armed_night") return uiText("armed_night")
        if (alarmRawState === "armed_custom_bypass") return uiText("armed_custom_bypass")
        if (alarmRawState === "armed_vacation") return uiText("armed_vacation")
        if (alarmRawState === "arming") return uiText("arming")
        if (alarmRawState === "pending") return uiText("pending")
        if (alarmRawState === "triggered") return uiText("triggered")
        if (alarmRawState === "unavailable") return uiText("offline")
        return uiText("unknown")
    }

    function selectCommand(command) {
        if (selectedCommand !== command) {
            bypassOffered = false
        }
        selectedCommand = command
        flashCommandButton(command, "#f1c40f")
        refreshCommandReadiness()
        if (!selectedCommandReady) {
            if (command.indexOf("arm_") === 0) {
                setCommandFeedback("checking", command, "#f1c40f")
                Api.alarmCheck(command, status, page)
            } else {
                setCommandFeedback("not_ready_to_arm", command, "#ff6b6b")
            }
            return
        }
        if (!commandRequiresPin(command)) {
            executeCommand(command, false)
        } else {
            setCommandFeedback("pin_required", command, "#f1c40f")
        }
    }

    function commandRequiresPin(command) {
        return Api.alarmCommandRequiresCode(alarmCommandDetails, command)
    }

    function submitPin() {
        executeCommand(selectedCommand, false)
    }

    function executeCommand(command, force) {
        if (!alarmConfigured) {
            status.text = uiText("alarm_not_configured")
            status.color = "#ff6b6b"
            return
        }
        if (alarmCommands.length === 0) {
            status.text = uiText("no_mode_available")
            status.color = "#f1c40f"
            return
        }
        refreshCommandReadiness()
        if (!force && !selectedCommandReady) {
            setCommandFeedback("not_ready_to_arm", command, "#ff6b6b")
            return
        }
        var needsPin = commandRequiresPin(command)
        if (needsPin && pinCode.length === 0) {
            setCommandFeedback("pin_required", command, "#f1c40f")
            return
        }
        var code = needsPin ? pinCode : ""
        pinCode = ""
        selectedCommand = command
        flashCommandButton(command, "#f1c40f")
        if (force) {
            bypassOffered = false
        }
        setCommandFeedback(force ? "bypass_open_sensors" : "sending", command, "#f1c40f")
        Api.alarmCommand(command, code, status, page, alarmState, activeSince, force)
    }

    function modeBackground(command) {
        return selectedCommand === command ? "images/settings/list_btn.svg" : "images/settings/act_btn.svg"
    }

    function modeReadyColor(command) {
        return Api.alarmCommandReady(alarmCommandDetails, command) ? "#58d68d" : "#ff6b6b"
    }

    function modeReadyIndicatorVisible(command) {
        return isArmCommand(command) && commandTargetState(command) !== alarmRawState
    }

    function modeFeedbackVisible(command) {
        return activeFeedbackCommand === command
    }

    function modeFeedbackColor(command) {
        if (!modeFeedbackVisible(command)) {
            return "transparent"
        }
        if (commandFeedbackColor === "#f1c40f") {
            return "#f1c40f"
        }
        if (commandFeedbackColor === "#58d68d") {
            return "#58d68d"
        }
        if (commandFeedbackColor === "#ff6b6b" || !Api.alarmCommandReady(alarmCommandDetails, command)) {
            return "#ff6b6b"
        }
        return "#58d68d"
    }

    function refreshCommandReadiness() {
        selectedCommandReady = Api.alarmCommandReady(alarmCommandDetails, selectedCommand)
        selectedCommandBlockedBySensors = Api.alarmCommandHasBlockers(alarmCommandDetails, selectedCommand)
        selectedCommandStatus = selectedCommandReady ? "" : Api.alarmBlockingText(alarmCommandDetails, selectedCommand, page)
    }

    function feedbackTitle() {
        if (!alarmConfigured) return uiText("alarm_not_configured")
        if (alarmCommands.length === 0) return uiText("no_mode_available")
        if (bypassVisible()) return uiText("not_ready_to_arm")
        return stateLabel()
    }

    function feedbackDetail() {
        if (!alarmConfigured || alarmCommands.length === 0) return ""
        if (alarmRawState === "triggered") {
            var sensors = Api.alarmOpenSensorsText(page)
            if (sensors.length > 0) return sensors
            return commandLabel(selectedCommand)
        }
        if (bypassVisible()) return selectedCommandStatus
        var timer = alarmDelayRemaining > 0 ? alarmDelayRemaining + " " + uiText("seconds_short") : ""
        var pin = pinCode.length > 0 ? uiText("pin_required") + " " + pinMask() : ""
        if (timer.length > 0 && pin.length > 0) {
            return timer + "  " + commandLabel(selectedCommand) + "  " + pin
        }
        if (pinCode.length > 0) {
            return commandLabel(selectedCommand) + "  " + pin
        }
        if (commandRequiresPin(selectedCommand)) {
            if (timer.length > 0) return timer + "  " + commandLabel(selectedCommand)
            return commandLabel(selectedCommand)
        }
        if (timer.length > 0) return timer + "  " + commandLabel(selectedCommand)
        if (!selectedCommandReady) return commandLabel(selectedCommand)
        return uiText("ready_to_arm") + ": " + commandLabel(selectedCommand)
    }

    function feedbackColor() {
        if (alarmRawState === "triggered") return "#ff6b6b"
        if (!alarmConfigured || bypassVisible()) return "#ff6b6b"
        if (alarmRawState === "arming" || alarmRawState === "pending") return "#f1c40f"
        if (alarmRawState === "unavailable" || alarmRawState === "unknown") return "#f1c40f"
        return "#58d68d"
    }

    function bypassVisible() {
        return bypassOffered && selectedCommandBlockedBySensors && selectedCommand.indexOf("arm_") === 0
    }

    function keyBackground(pressed) {
        return pressed ? "images/first_configuration/list_btn_p.svg" : "images/first_configuration/list_btn.svg"
    }

    function stateColor() {
        if (alarmRawState === "triggered") return "#ff6b6b"
        if (alarmRawState === "arming" || alarmRawState === "pending") return "#f1c40f"
        if (alarmRawState === "unavailable" || alarmRawState === "unknown") return "#f1c40f"
        return "white"
    }

    function modeColumnCount() {
        if (alarmCommands.length <= 0) return 1
        if (alarmCommands.length <= 4) return alarmCommands.length
        return 4
    }

    function modeRowCount() {
        return alarmCommands.length <= modeColumnCount() ? 1 : 2
    }

    function uiText(key) {
        return I18n.text(uiLanguage, key)
    }

    Timer {
        interval: 1000
        repeat: true
        running: alarmDelayRemaining > 0
        onTriggered: setAlarmDelayRemaining(alarmDelayRemaining - 1)
    }

    Timer {
        id: delayedStatusRefresh
        interval: 700
        repeat: false
        onTriggered: Api.status(status, page, alarmState, activeSince)
    }

    Column {
        anchors.top: header.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.topMargin: 16
        anchors.leftMargin: 40
        anchors.rightMargin: 40
        spacing: 6

        Item {
            id: statePanel
            width: parent.width
            height: 50

            Image {
                anchors.fill: parent
                source: "images/settings/medium_list_btn.svg"
                fillMode: Image.Stretch
            }

            UbuntuLightText {
                id: alarmState
                text: "..."
                color: stateColor()
                font.pixelSize: 30
                anchors.left: parent.left
                anchors.leftMargin: 76
                anchors.verticalCenter: parent.verticalCenter
            }

            Image {
                source: "images/keylock_icon-small.svg"
                width: 40
                height: 40
                fillMode: Image.PreserveAspectFit
                anchors.left: parent.left
                anchors.leftMargin: 22
                anchors.verticalCenter: parent.verticalCenter
            }

            UbuntuLightText {
                id: activeSince
                text: ""
                color: "#c7d0d9"
                font.pixelSize: 17
                anchors.right: parent.right
                anchors.rightMargin: 22
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        Grid {
            id: modeGrid
            width: parent.width
            height: visible ? (modeRowCount() * 38) + ((modeRowCount() - 1) * spacing) : 0
            visible: alarmCommands.length > 0
            spacing: 8
            columns: modeColumnCount()
            property int commandCount: alarmCommands.length > 0 ? alarmCommands.length : 1
            property int columnCount: modeColumnCount()
            property int cellWidth: (width - (spacing * (columnCount - 1))) / columnCount

            Repeater {
                model: alarmCommands

                Item {
                    width: modeGrid.cellWidth
                    height: 38

                    Image {
                        anchors.fill: parent
                        source: modeBackground(modelData)
                        fillMode: Image.Stretch
                    }

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 3
                        radius: 4
                        visible: modeFeedbackVisible(modelData)
                        color: modeFeedbackColor(modelData)
                        opacity: 0.55
                    }

                    UbuntuLightText {
                        text: commandLabel(modelData) + trsl.empty
                        color: "white"
                        font.pixelSize: 16
                        anchors.centerIn: parent
                    }

                    Rectangle {
                        width: 10
                        height: 10
                        radius: 5
                        visible: modeReadyIndicatorVisible(modelData)
                        color: modeReadyColor(modelData)
                        anchors.left: parent.left
                        anchors.leftMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    BeepingMouseArea {
                        anchors.fill: parent
                        onClicked: selectCommand(modelData)
                    }
                }
            }
        }

        Row {
            width: parent.width
            height: 204
            spacing: 20

            Grid {
                id: keypad
                columns: 3
                spacing: 6
                property int keyWidth: 132
                property int keyHeight: 38
                width: (columns * keyWidth) + ((columns - 1) * spacing)
                height: (4 * keyHeight) + (3 * spacing)

                Repeater {
                    model: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "C", "0", "OK"]

                    Item {
                        width: keypad.keyWidth
                        height: keypad.keyHeight

                        Image {
                            anchors.fill: parent
                            source: keyBackground(keyMouse.pressed)
                            fillMode: Image.Stretch
                        }

                        UbuntuLightText {
                            text: modelData + trsl.empty
                            color: "white"
                            font.pixelSize: modelData === "OK" ? 17 : 22
                            anchors.centerIn: parent
                        }

                        BeepingMouseArea {
                            id: keyMouse
                            anchors.fill: parent
                            onClicked: {
                                if (modelData === "C") {
                                    clearPin()
                                } else if (modelData === "OK") {
                                    submitPin()
                                } else {
                                    appendDigit(modelData)
                                }
                            }
                        }
                    }
                }
            }

            Column {
                width: parent.width - keypad.width - parent.spacing
                height: parent.height
                spacing: 8

                Item {
                    width: parent.width
                    height: 42

                    Image {
                        anchors.fill: parent
                        source: keyBackground(stairMouse.pressed)
                        fillMode: Image.Stretch
                    }

                    UbuntuLightText {
                        text: uiText("stair_light") + trsl.empty
                        color: "white"
                        font.pixelSize: 18
                        anchors.centerIn: parent
                    }

                    BeepingMouseArea {
                        id: stairMouse
                        anchors.fill: parent
                        onClicked: Api.stairLight(status, page)
                    }
                }

                Item {
                    width: parent.width
                    height: bypassVisible() ? 96 : 120

                    Image {
                        anchors.fill: parent
                        source: "images/settings/act_btn.svg"
                        fillMode: Image.Stretch
                    }

                    UbuntuLightText {
                        text: feedbackTitle() + trsl.empty
                        color: feedbackColor()
                        font.pixelSize: 15
                        anchors.left: parent.left
                        anchors.leftMargin: 18
                        anchors.top: parent.top
                        anchors.topMargin: 10
                    }

                    UbuntuLightText {
                        text: feedbackDetail() + trsl.empty
                        color: "white"
                        font.pixelSize: feedbackDetail().length > 62 ? 11 : (feedbackDetail().length > 36 ? 13 : 20)
                        anchors.left: parent.left
                        anchors.leftMargin: 18
                        anchors.right: parent.right
                        anchors.rightMargin: 14
                        anchors.top: parent.top
                        anchors.topMargin: 36
                        wrapMode: Text.Wrap
                    }
                }

                Item {
                    width: parent.width
                    height: bypassVisible() ? 36 : 0
                    visible: bypassVisible()

                    Image {
                        anchors.fill: parent
                        source: keyBackground(bypassMouse.pressed)
                        fillMode: Image.Stretch
                    }

                    UbuntuLightText {
                        text: uiText("bypass_open_sensors") + trsl.empty
                        color: "white"
                        font.pixelSize: 16
                        anchors.centerIn: parent
                    }

                    BeepingMouseArea {
                        id: bypassMouse
                        anchors.fill: parent
                        onClicked: executeCommand(selectedCommand, true)
                    }
                }

                UbuntuLightText {
                    id: status
                    text: ""
                    color: "#c7d0d9"
                    font.pixelSize: 16
                    width: parent.width
                    wrapMode: Text.Wrap
                }
            }
        }
    }
}
