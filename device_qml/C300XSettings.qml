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
    property string problem: ""
    property bool bridgeOff: false
    property bool answered: false
    property bool reachable: answered && problem === ""
    property string address: ""
    property string contact: ""
    property string agentVersion: ""
    property string firmwareVersion: ""
    property string integrationVersion: ""
    property string instanceName: ""
    property bool keepOpen: false
    property bool tabNavigation: false
    property bool saving: false
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

    function statusKey(row) {
        return row === 0 ? "Home Assistant" : row === 2 ? label("status_contact") : row === 3 ? "Integration" : row === 4 ? "Agent" : ""
    }
    function statusValue(row) {
        if (row === 0) return label(reachable ? "status_ok" : problem ? "status_down" : "status_checking")
            + (reachable && instanceName ? " (" + instanceName + ")" : "")
        if (row === 1) return address || "-"
        if (row === 2) return contact || "-"
        if (row === 3) return reachable && integrationVersion ? integrationVersion : "-"
        return (agentVersion || "-") + " \u00b7 Firmware " + (firmwareVersion || "-")
    }
    function rowText(row) {
        if (row === 0) return label("section_display")
        if (row === 1) return c300xDisplayPreferences.label
        if (row === 2) return label("setting_standby")
        if (row === 3) return label(!reachable ? "setting_nav" : tabNavigation ? "setting_nav_tabs" : "setting_nav_pager")
        return row === 4 ? label("section_station") : "SSH"
    }
    function rowOn(row) {
        return row === 1 ? c300xDisplayPreferences.feedbackEnabled === true : row === 2 ? keepOpen : row === 3 ? tabNavigation : row === 5 && sshRunning
    }
    function rowEnabled(row) {
        if (row === 1) return c300xDisplayPreferences.ready && !c300xDisplayPreferences.busy
        if (row === 5) return sshKnown && !busy
        return (row === 2 || row === 3) && reachable && !saving
    }
    function contactText(age) {
        if (typeof age !== "number") return label("contact_never")
        if (age < 90) return label("contact_now")
        if (age < 5400) return label("contact_min").replace("%1", Math.round(age / 60))
        if (age < 172800) return label("contact_hours").replace("%1", Math.round(age / 3600))
        return label("contact_days").replace("%1", Math.floor(age / 86400))
    }
    function reasonKey() {
        return problem === "bridge_not_registered" && bridgeOff ? "bridge_disabled" : problem
    }
    function applyDisplay(data) {
        keepOpen = data.preventReturnToHomepage === true
        tabNavigation = data.navigation === "tabs"
    }
    function readLocal() {
        Bridge.stationStatus(function(data) {
            panel.address = data && /^https?:\/\/[^\/?#@\s]+$/.test(data.home_assistant) ? data.home_assistant : ""
            panel.contact = data ? panel.contactText(data.last_contact_age) : ""
            panel.bridgeOff = !!data && data.disabled === true
            panel.agentVersion = data && data.version ? data.version : ""
            panel.firmwareVersion = data && data.firmware ? data.firmware : ""
        }, panel)
    }
    function readStatus() {
        readLocal()
        Bridge.bridgeDetails(function(data, reason) {
            panel.readLocal()
            panel.answered = true
            panel.problem = reason
            if (!data) return
            panel.integrationVersion = data.integration_version || ""
            panel.instanceName = data.instance_name || ""
            panel.applyDisplay(data)
        }, panel)
    }
    function setDisplay(key, value) {
        if (saving || !reachable || pending) return
        saving = true
        status = ""
        Bridge.displaySetting(key, value, function(data) {
            panel.saving = false
            if (data) panel.applyDisplay(data)
            else panel.status = "display_settings_error"
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
        saving = false
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
            Item {
                width: content.width
                height: statusRows.height + 8
                Image {
                    anchors.fill: parent
                    source: "images/settings/act_btn.svg"
                    fillMode: Image.Stretch
                }
                Column {
                    id: statusRows
                    x: 8
                    y: 4
                    width: parent.width - 16
                    Repeater {
                        model: 5
                        Item {
                            width: statusRows.width
                            height: Math.max(23, statusValue.paintedHeight + 2)
                            UbuntuLightText {
                                anchors.verticalCenter: parent.verticalCenter
                                color: "#c7d0d9"
                                font.pixelSize: 18
                                text: panel.statusKey(index)
                            }
                            UbuntuLightText {
                                id: statusValue
                                objectName: "statusValue" + index
                                anchors.left: parent.left
                                anchors.leftMargin: index === 1 ? 0 : 140
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                color: index > 0 ? "white" : panel.reachable ? "#58d68d" : panel.problem ? "#f1c40f" : "white"
                                font.pixelSize: 18
                                wrapMode: index === 1 ? Text.WrapAnywhere : Text.NoWrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                                text: panel.statusValue(index)
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
                        text: panel.problem ? panel.label(panel.reasonKey()) : ""
                    }
                }
            }
            Repeater {
                model: 6
                Item {
                    width: content.width
                    property bool head: index === 0 || index === 4
                    height: head ? 24 : 34
                    Rectangle {
                        visible: head
                        anchors.bottom: parent.bottom
                        width: parent.width
                        height: 1
                        color: "#5c6fd0"
                    }
                    UbuntuLightText {
                        anchors.left: parent.left
                        anchors.right: toggle.left
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.verticalCenterOffset: head ? 1 : 0
                        color: "white"
                        font.pixelSize: 18
                        elide: Text.ElideRight
                        text: panel.rowText(index)
                    }
                    BasicButton {
                        id: toggle
                        visible: !head
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        checked: panel.rowOn(index)
                        enabled: panel.rowEnabled(index) && !panel.pending
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
                            if (index === 5)
                                Maintenance.request(panel, deadline, "/ssh", {enabled: !checked})
                            else if (index === 1)
                                c300xDisplayPreferences.setFeedbackEnabled(!checked)
                            else if (index === 2)
                                panel.setDisplay("dashboard_prevent_return", checked ? "off" : "on")
                            else
                                panel.setDisplay("dashboard_navigation", checked ? "pager" : "tabs")
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
