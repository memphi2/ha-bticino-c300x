import QtQuick 1.1
import "js/c300x_i18n.js" as I18n
import Components 1.0
import Components.Styles 1.0
import Components.Settings 1.0
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
    property string problem: c300xDisplayPreferences.bridgeProblem
    property bool answered: false
    property bool reachable: answered && problem === ""
    property string address: ""
    property string contact: ""
    property string agentVersion: ""
    property string firmwareVersion: ""
    property string integrationVersion: ""
    property string instanceName: ""
    function label(key) { return I18n.text(trsl.language, key) + trsl.empty }
    function clearConfirmation() {
        var open = pending !== ""
        pending = ""
        expiresAt = 0
        expiry.stop()
        if (open) dismissPopup()
    }
    function ask(action) {
        if (!visible || busy || pending || !(action === "reboot" ? canReboot : action === "remove" && canRemove)) return
        status = ""
        expiresAt = Date.now() + expiry.interval
        pending = action
        expiry.restart()
        installPopup(confirmation)
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
    Component {
        id: confirmation
        ConfirmPopup {
            sourceSizeWidth: 400
            sourceSizeHeight: panel.pending === "remove" ? 190 : 130
            maxLine: 6
            message: panel.pending ? panel.label("maintenance_confirm_" + panel.pending) : ""
            onDeleteClicked: panel.confirmAction()
            onCancelClicked: panel.clearConfirmation()
        }
    }

    function contactText(age) {
        if (typeof age !== "number") return label("contact_never")
        if (age < 90) return label("contact_now")
        if (age < 5400) return label("contact_min").replace("%1", Math.round(age / 60))
        if (age < 172800) return label("contact_hours").replace("%1", Math.round(age / 3600))
        return label("contact_days").replace("%1", Math.floor(age / 86400))
    }
    function readStatus() {
        Bridge.stationStatus(function(data) {
            panel.address = data && /^https?:\/\/[^\/?#@\s]+$/.test(data.home_assistant) ? data.home_assistant : ""
            panel.contact = data ? panel.contactText(data.last_contact_age) : ""
            panel.agentVersion = data && data.version ? data.version : ""
            panel.firmwareVersion = data && data.firmware ? data.firmware : ""
        }, panel)
        Bridge.bridgeDetails(function(data, reason) {
            panel.answered = true
            c300xDisplayPreferences.bridgeProblem = reason
            if (!data) return
            panel.integrationVersion = data.integration_version || ""
            panel.instanceName = data.instance_name || ""
        }, panel)
    }
    function aboutToShow() {
        hidden()
        sshRunning = sshKnown = canReboot = canRemove = false
        status = ""
        c300xDisplayPreferences.load()
        Maintenance.request(panel, deadline, "", null)
        if (visible) readStatus()
    }
    function hidden() {
        clearConfirmation()
        Maintenance.cancel(panel, deadline)
    }
    onVisibleChanged: if (visible) readStatus(); else hidden()
    Component.onDestruction: hidden()
    Timer {
        id: deadline
        interval: 125000
        onTriggered: {
            Maintenance.cancel(panel, deadline)
            panel.status = "maintenance_timeout"
        }
    }

    Flickable {
        id: scroller
        anchors.fill: parent
        anchors.topMargin: 8
        clip: true
        contentHeight: content.height
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height
        Column {
            id: content
            anchors.horizontalCenter: parent.horizontalCenter
            width: 400
            Repeater {
                model: [
                    {k: "Home Assistant", v: panel.label(panel.reachable ? "status_ok" : panel.problem ? "status_down" : "status_checking")
                        + (panel.reachable && panel.instanceName ? " (" + panel.instanceName + ")" : ""),
                     c: panel.reachable ? "#58d68d" : panel.problem ? "#f1c40f" : "white"},
                    {k: panel.label("status_server"), v: panel.address || "-", c: "white"},
                    {k: panel.label("status_contact"), v: panel.contact || "-", c: "white"},
                    {k: "", v: "Integration " + (panel.reachable && panel.integrationVersion ? panel.integrationVersion : "-")
                        + " \u00b7 Agent " + (panel.agentVersion || "-") + " \u00b7 Firmware " + (panel.firmwareVersion || "-"), c: "white"}
                ]
                Item {
                    width: content.width
                    height: 24
                    UbuntuLightText {
                        anchors.verticalCenter: parent.verticalCenter
                        color: "#c7d0d9"
                        font.pixelSize: 18
                        text: modelData.k
                    }
                    UbuntuLightText {
                        objectName: "statusValue" + index
                        anchors.left: parent.left
                        anchors.leftMargin: modelData.k ? 140 : 0
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        color: modelData.c
                        font.pixelSize: 18
                        elide: Text.ElideRight
                        text: modelData.v
                    }
                }
            }
            UbuntuLightText {
                objectName: "bridgeReason"
                visible: text !== ""
                width: parent.width
                color: "#f1c40f"
                font.pixelSize: 18
                wrapMode: Text.WordWrap
                text: panel.problem ? panel.label(panel.problem) : ""
            }
            Repeater {
                model: [
                    {h: panel.label("section_display")},
                    {t: c300xDisplayPreferences.label, s: c300xDisplayPreferences.feedbackEnabled,
                     e: c300xDisplayPreferences.ready && !c300xDisplayPreferences.busy, a: "feedback"},
                    {h: panel.label("section_station")},
                    {t: "SSH", s: panel.sshRunning, e: panel.sshKnown && !panel.busy, a: "ssh"}
                ]
                Item {
                    width: content.width
                    height: modelData.h ? 26 : 37
                    Rectangle {
                        visible: !!modelData.h
                        anchors.bottom: parent.bottom
                        width: parent.width
                        height: 1
                        color: "#5c6fd0"
                    }
                    UbuntuLightText {
                        anchors.left: parent.left
                        anchors.right: toggle.left
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.verticalCenterOffset: modelData.h ? 1 : 0
                        color: modelData.h ? "#c7d0d9" : "white"
                        font.pixelSize: 18
                        elide: Text.ElideRight
                        text: modelData.h || modelData.t
                    }
                    BasicButton {
                        id: toggle
                        visible: !modelData.h
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        checked: modelData.s === true
                        enabled: modelData.e === true && !panel.pending
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
                            if (modelData.a === "ssh")
                                Maintenance.request(panel, deadline, "/ssh", {enabled: !checked})
                            else
                                c300xDisplayPreferences.setFeedbackEnabled(!checked)
                        }
                    }
                }
            }
            Item { width: 1; height: 6 }
            Item {
                width: content.width
                height: 50
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 8
                    Repeater {
                        model: ["reboot", "remove"]
                        BasicButton {
                            style: IconAndLabelStyle {
                                defaultImage: "images/settings/list_option_btn.svg"
                                pressedImage: "images/settings/list_option_btn_p.svg"
                                background.width: 236
                                background.height: 50
                                description: panel.label("maintenance_" + modelData)
                            }
                            enabled: (modelData === "reboot" ? panel.canReboot : panel.canRemove) && !panel.busy && !panel.pending
                            opacity: enabled ? 1 : 0.45
                            onMouseClicked: panel.ask(modelData)
                        }
                    }
                }
            }
            UbuntuLightText {
                visible: text !== ""
                width: parent.width
                color: "white"
                font.pixelSize: 18
                wrapMode: Text.WordWrap
                text: panel.status ? panel.label(panel.status) : ""
            }
        }
    }
    Rectangle {
        visible: scroller.contentHeight > scroller.height
        anchors.right: parent.right
        anchors.rightMargin: 10
        width: 4
        radius: 2
        color: "#c7d0d9"
        opacity: 0.7
        y: scroller.y + scroller.contentY / scroller.contentHeight * scroller.height
        height: scroller.height * scroller.height / scroller.contentHeight
    }
}
