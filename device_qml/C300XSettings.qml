import QtQuick 1.1
import "js/c300x_i18n.js" as I18n
import Components 1.0
import Components.Styles 1.0
import "js/c300x_maintenance.js" as Maintenance
import "js/c300x_ha.js" as Bridge

Item {
    id: panel
    property string uiBaseUrl: c300xDisplayPreferences.uiBaseUrl
    property bool sshKnown: false
    property bool sshRunning: false
    property bool canReboot: false
    property bool canRemove: false
    property bool busy: false
    property string pending: ""
    property double expiresAt: 0
    function label(key) { return I18n.text(trsl.language, key) + trsl.empty }
    function clearConfirmation() { pending = ""; expiresAt = 0; expiry.stop() }
    function ask(action) {
        if (!visible || busy || pending || !(action === "reboot" ? canReboot : action === "remove" && canRemove)) return
        status = ""
        expiresAt = Date.now() + expiry.interval
        pending = action
        expiry.restart()
    }
    function confirmAction() {
        var action = pending
        var valid = visible && !busy && Date.now() < expiresAt
        clearConfirmation()
        if (!valid) return
        if (action === "reboot" && canReboot)
            Maintenance.request(panel, deadline, "/reboot", {confirm: "reboot"})
        if (action === "remove" && canRemove)
            Maintenance.request(panel, deadline, "/remove", {confirm: "remove_agent"})
    }
    Timer { id: expiry; interval: 10000; onTriggered: panel.clearConfirmation() }
    property string status: ""

    function aboutToShow() {
        hidden()
        sshRunning = sshKnown = canReboot = canRemove = false
        status = ""
        c300xDisplayPreferences.load()
        Maintenance.request(panel, deadline, "", null)
    }
    function hidden() {
        clearConfirmation()
        Maintenance.cancel(panel, deadline)
    }
    function checkBridge() {
        if (!c300xDisplayPreferences.bridgeProblem) return
        Bridge.homeButtons(function(alarm, dashboard, valid, reason) {
            c300xDisplayPreferences.bridgeProblem = valid ? "" : reason
        }, panel)
    }
    onVisibleChanged: if (visible) checkBridge(); else hidden()
    Component.onDestruction: hidden()
    Timer {
        id: deadline
        interval: 125000
        onTriggered: {
            Maintenance.cancel(panel, deadline)
            panel.status = "maintenance_timeout"
        }
    }

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 10
        spacing: 6
        width: parent.width - 64
        UbuntuLightText {
            objectName: "bridgeReason"
            visible: text !== ""
            width: parent.width
            color: "#f1c40f"
            font.pixelSize: 16
            wrapMode: Text.WordWrap
            text: c300xDisplayPreferences.bridgeProblem ? panel.label(c300xDisplayPreferences.bridgeProblem) : ""
        }
        Repeater {
            model: 2
            Item {
                width: parent.width
                height: 50
                UbuntuLightText {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    color: "white"
                    font.pixelSize: 20
                    text: index === 0 ? "SSH" : c300xDisplayPreferences.label
                }
                BasicButton {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    checked: index === 0 ? panel.sshRunning : c300xDisplayPreferences.feedbackEnabled
                    enabled: !panel.pending && (index === 0 ? panel.sshKnown && !panel.busy :
                             c300xDisplayPreferences.ready && !c300xDisplayPreferences.busy)
                    opacity: enabled ? 1 : 0.45
                    style: CheckableButtonStyle {
                        defaultImage: "images/ringtones/switch-bg_btn.svg"
                        checkedImage: "images/ringtones/switch-bg_btn_p.svg"
                        defaultIconLeft: "images/ringtones/switch_btn.svg"
                        defaultIconRight: "images/ringtones/disable_icon.svg"
                        checkedIconLeft: "images/ringtones/enable_icon.svg"
                        checkedIconRight: "images/ringtones/switch_btn_p.svg"
                    }
                    onMouseClicked: {
                        if (index === 0)
                            Maintenance.request(panel, deadline, "/ssh", {enabled: !checked})
                        else
                            c300xDisplayPreferences.setFeedbackEnabled(!checked)
                    }
                }
            }
        }
        BasicButton {
            style: IconAndLabelStyle {
                defaultImage: "images/settings/list_option_btn.svg"
                background.width: Math.min(320, panel.width - 64)
                pressedImage: "images/settings/list_option_btn_p.svg"
                description: panel.label("maintenance_reboot")
            }
            enabled: panel.canReboot && !panel.busy && !panel.pending
            opacity: enabled ? 1 : 0.45
            onMouseClicked: panel.ask("reboot")
        }
        Item { width: 1; height: 20 }
        BasicButton {
            style: IconAndLabelStyle {
                defaultImage: "images/settings/list_option_btn.svg"
                background.width: Math.min(320, panel.width - 64)
                pressedImage: "images/settings/list_option_btn_p.svg"
                description: panel.label("maintenance_remove")
            }
            enabled: panel.canRemove && !panel.busy && !panel.pending
            opacity: enabled ? 1 : 0.45
            onMouseClicked: panel.ask("remove")
        }
        BasicButton {
            visible: panel.pending !== ""
            style: IconAndLabelStyle {
                defaultImage: "images/settings/list_option_btn.svg"
                background.width: Math.min(320, panel.width - 64)
                pressedImage: "images/settings/list_option_btn_p.svg"
                description: panel.label(panel.pending === "reboot" ? "maintenance_confirm_reboot" : "maintenance_confirm_remove")
            }
            onMouseClicked: panel.confirmAction()
        }
        BasicButton {
            visible: panel.pending !== ""
            style: IconAndLabelStyle {
                defaultImage: "images/settings/list_option_btn.svg"
                background.width: Math.min(320, panel.width - 64)
                pressedImage: "images/settings/list_option_btn_p.svg"
                description: panel.label("maintenance_cancel")
            }
            onMouseClicked: panel.clearConfirmation()
        }
        UbuntuLightText {
            width: parent.width
            color: "white"
            font.pixelSize: 18
            wrapMode: Text.WordWrap
            text: panel.status ? panel.label(panel.status) : ""
        }
    }
}
