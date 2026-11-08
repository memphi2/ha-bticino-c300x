import QtQuick 1.1
import Components 1.0
import Components.Styles 1.0
import BtObjects 2.0
import "js/c300x_ha.js" as Api
import "js/c300x_i18n.js" as I18n

Page {
    id: page
    showBackButton: true
    onBackClicked: {
        if (notificationsOpen) notificationsOpen = false
        else if (selectedItem) selectedItem = null
        else tabView.activateTab(homePage)
    }
    headerLabel: (notificationsOpen ? uiText("notifications") : selectedItem ? itemName(selectedItem) : uiText("home_assistant")) + trsl.empty

    property string uiLanguage: trsl.language
    property variant dashboardPages: []
    property variant badges: []
    property variant items: []
    property variant flowItems: []
    property variant flowLines: []
    property int currentPageIndex: 0
    property int pageCount: 0
    property int flowWidth: 0
    property int flowHeight: 0
    property bool flowVisible: false
    property bool preventReturnToHomepage: true
    property string pageTitle: ""
    property string pageLabel: ""
    property string flowColor: "transparent"
    property bool weatherVisible: false
    property string weatherTitle: ""
    property string weatherCondition: ""
    property string weatherConditionKey: ""
    property string weatherTemperature: ""
    property string weatherHumidity: ""
    property string weatherWind: ""
    property string weatherForecast: ""
    property variant weatherForecast1: ({})
    property variant weatherForecast2: ({})
    property string weatherSun: ""
    property string weatherSunrise: ""
    property string weatherSunset: ""
    property string weatherUpdated: ""
    property string weatherColor: "#58d68d"
    property variant selectedItem: null
    property bool dashboardOnline: false
    property bool dashboardLoading: false
    property bool dashboardRefreshAgain: false
    property bool pageActive: false
    property bool watchFailed: false
    property int runtimeGeneration: 0
    property string pendingEntity: ""
    property bool controlInFlight: false
    property bool interactionActive: false
    property variant notifications: []
    property bool notificationsOpen: false

    function notificationAction(item, actionId) {
        var command = {revision: item.revision, action_id: actionId}
        Api.dashboardControl({entity_id: "notification." + item.id}, {command: ""}, JSON.stringify(command), status, page)
    }

    function notificationSymbol(item) {
        return item.icon === "warning" ? "!" : item.icon === "calendar" ? "\u25a6" : "i"
    }

    function notificationColor(item) {
        return item.priority === "urgent" ? "#ff6b6b" : item.priority === "important" ? "#f1c40f" : "white"
    }

    function aboutToShow() {
        pageActive = true
        Api.dashboard(status, page)
        startWatch()
    }

    function aboutToHide() {
        pageActive = false
        runtimeGeneration += 1
        dashboardLoading = false
        dashboardRefreshAgain = false
        dashboardOnline = false
        pendingEntity = ""
        controlInFlight = false
        interactionActive = false
        Api.stopDashboardRuntime()
    }

    function handleScreenOff() {
        aboutToHide()
        return preventReturnToHomepage
    }

    function startWatch() {
        watchFailed = false
        Api.startEventWatch(function(event) {
            if (event.topic === "connection.error") {
                watchFailed = true
                dashboardOnline = false
                badges = [{state: uiText("offline"), color: "#f1c40f"}]
                status.text = uiText("offline")
                status.color = "#f1c40f"
            } else {
                Api.dashboard(status, page)
            }
        })
    }

    function refreshSelectedItem() {
        if (!selectedItem) return
        for (var i = 0; i < items.length; i++) {
            if (items[i].entity_id === selectedItem.entity_id) {
                selectedItem = items[i]
                return
            }
        }
        selectedItem = null
    }

    function controlLabel(control) {
        if (control.command === "open_cover") return "\u2191"
        if (control.command === "stop_cover") return "\u25a0"
        if (control.command === "close_cover") return "\u2193"
        return uiText(control.command)
    }

    function controlValue(control) {
        return control.value === null || control.value === undefined ? "?" : String(control.value) + (control.unit ? " " + control.unit : "")
    }

    function optionLabel(control, option) {
        if (control.command === "option" || control.command === "preset_mode") return String(option)
        var key = (control.command === "color" ? "color_" : "mode_") + String(option)
        var label = uiText(key)
        return label === key ? String(option) : label
    }

    function detailState(item) {
        if (!item) return ""
        if (!dashboardOnline || item.available === false) return uiText("offline")
        if (pendingEntity === item.entity_id) return uiText("sending")
        var detail = item.details || {}
        if (detail.activity) return uiText("activity_" + detail.activity)
        return detail.type === "sensor" || detail.type === "binary_sensor" ? "" : detail.state_label || ""
    }

    function detailColor(item) {
        if (!dashboardOnline || !item || item.available === false) return "#f1c40f"
        var activity = item.details ? item.details.activity : ""
        if (activity === "heating" || activity === "preheating") return "#f1c40f"
        if (activity === "cooling") return "#65d7e5"
        return itemColor(item)
    }

    function detailValue(item) {
        if (!item || !item.details) return ""
        if (!dashboardOnline || item.available === false) return "?"
        return item.details.value + (item.details.unit ? " " + item.details.unit : "")
    }

    function openDetails(item) {
        selectedItem = item
        details.contentY = 0
    }

    function overviewControls(item) {
        var result = []
        var controls = item.controls || []
        for (var i = 0; i < controls.length; i++) {
            if (controls[i].kind === "button" || controls[i].command === "temperature" || controls[i].command === "value") result.push(controls[i])
        }
        return result
    }

    function adjustControl(item, control, direction) {
        if (control.value === null || control.value === undefined) return
        var steps = Math.round((Number(control.value) - control.min) / control.step) + direction
        steps = Math.max(0, Math.min(Math.floor((control.max - control.min) / control.step), steps))
        var value = control.min + steps * control.step
        Api.dashboardControl(item, control, String(Number(value.toFixed(6))), status, page)
    }

    Timer {
        interval: 5000
        repeat: false
        running: pageActive && watchFailed
        onTriggered: {
            startWatch()
            Api.dashboard(status, page)
        }
    }

    Timer {
        interval: 10000
        repeat: false
        running: pageActive && pendingEntity.length > 0
        onTriggered: {
            aboutToHide()
            aboutToShow()
        }
    }

    function itemName(item) {
        return item.name || item.entity_id || uiText("action")
    }

    function itemDetail(item) {
        if (!dashboardOnline || item.available === false) return uiText("offline")
        if (pendingEntity === item.entity_id) return uiText("sending")
        var values = []
        if (item.kind === "switch") values.push(item.state ? uiText("on") : uiText("off"))
        if (item.current_temperature !== undefined && item.current_temperature !== null) {
            values.push(String(item.current_temperature) + " " + (item.temperature_unit || ""))
        }
        var controls = item.controls || []
        for (var i = 0; i < controls.length; i++) {
            if (controls[i].command === "temperature" || controls[i].command === "brightness" || controls[i].command === "position") {
                values.push(controlLabel(controls[i]) + ": " + controlValue(controls[i]))
            }
        }
        if (values.length > 0) return values.join("   ")
        if (item.kind === "switch") {
            return item.state ? uiText("on") : uiText("off")
        }
        if (item.hasOwnProperty && item.hasOwnProperty("state_label")) {
            return item.state_label
        }
        return item.state_label || uiText("execute")
    }

    function itemColor(item) {
        if (item.color && item.color.length > 0) {
            return item.color
        }
        if (item.kind === "switch" && item.state) {
            return "#58d68d"
        }
        if (item.kind === "entity" && item.state) {
            return "#58d68d"
        }
        return "#c7d0d9"
    }

    function sliderValueText(item) {
        if (item.state_label && item.state_label.length > 0) {
            return item.state_label
        }
        return String(item.value || "")
    }

    function safeNumber(value, fallbackValue) {
        if (value === undefined || value === null || value === "") {
            return fallbackValue
        }
        var numberValue = Number(value)
        if (isNaN(numberValue)) {
            return fallbackValue
        }
        return numberValue
    }

    function badgeColumnCount() {
        if (badges.length <= 0) {
            return 1
        }
        return badges.length < 4 ? badges.length : 4
    }

    function badgeGridHeight() {
        if (badges.length <= 0) {
            return 0
        }
        return Math.ceil(badges.length / badgeColumnCount()) * 54
    }

    function uiText(key) {
        return I18n.text(uiLanguage, key)
    }

    function uiWeather(key, fallback) {
        return I18n.weather(uiLanguage, key, fallback)
    }

    function weatherDetailsText() {
        var details = []
        if (weatherHumidity.length > 0) {
            details.push(uiText("humidity") + ": " + weatherHumidity)
        }
        if (weatherWind.length > 0) {
            details.push(uiText("wind") + ": " + weatherWind)
        }
        return details.join("   ")
    }

    function weatherUpdatedText() {
        return weatherUpdated.length > 0 ? uiText("updated") + " " + weatherUpdated : ""
    }

    function weatherConditionText() {
        return weatherCondition
    }

    function weatherSunText() {
        var parts = []
        if (weatherSunrise.length > 0) {
            parts.push(uiText("rise") + ": " + weatherSunrise)
        }
        if (weatherSunset.length > 0) {
            parts.push(uiText("set") + ": " + weatherSunset)
        }
        if (parts.length > 0) {
            return parts.join("   ")
        }
        return weatherUpdatedText()
    }

    function weatherForecastText(item) {
        if (!item || !item.condition_key) {
            return ""
        }
        return uiWeather(item.condition_key, item.condition || "")
    }

    function weatherForecastTemperature(item) {
        return item && item.temperature ? item.temperature : ""
    }

    function weatherForecastTime(item) {
        return item && item.time ? item.time : ""
    }

    Component {
        id: controlOverview
        Item {
            property variant tileItem: parent ? parent.tileItem : ({})
            anchors.fill: parent
            Image {
                anchors.fill: parent
                source: "images/settings/act_btn.svg"
                fillMode: Image.Stretch
            }
            UbuntuLightText {
                anchors.left: parent.left
                anchors.right: detailsButton.left
                anchors.top: parent.top
                anchors.margins: 12
                text: itemName(tileItem)
                textFormat: Text.PlainText
                font.pixelSize: 20
                color: "white"
                elide: Text.ElideRight
            }
            UbuntuLightText {
                anchors.left: parent.left
                anchors.right: detailsButton.left
                anchors.top: parent.top
                anchors.leftMargin: 12
                anchors.topMargin: 39
                text: itemDetail(tileItem)
                textFormat: Text.PlainText
                font.pixelSize: 15
                color: tileItem.available === false ? "#f1c40f" : "#c7d0d9"
                elide: Text.ElideRight
            }
            Item {
                id: detailsButton
                width: 52
                height: 42
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 8
                Image { anchors.fill: parent; source: "images/settings/list_btn.svg"; fillMode: Image.Stretch }
                UbuntuLightText { anchors.centerIn: parent; text: "..."; font.pixelSize: 24; color: "white" }
                BeepingMouseArea { anchors.fill: parent; onClicked: openDetails(tileItem) }
            }
            Row {
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.margins: 8
                spacing: 8
                Repeater {
                    model: overviewControls(tileItem)
                    Row {
                        property variant control: modelData
                        spacing: 8
                        Repeater {
                            model: control.kind === "number" ? [-1, 1] : [0]
                            Item {
                                width: control.command === "toggle" ? 140 : 80
                                height: 38
                                Image { anchors.fill: parent; source: "images/settings/list_btn.svg"; fillMode: Image.Stretch }
                                UbuntuLightText {
                                    anchors.fill: parent
                                    anchors.margins: 6
                                    text: modelData === -1 ? "-" : modelData === 1 ? "+" : controlLabel(control)
                                    textFormat: Text.PlainText
                                    font.pixelSize: 18
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                    color: "white"
                                }
                                BeepingMouseArea {
                                    anchors.fill: parent
                                    enabled: dashboardOnline && tileItem.available !== false && pendingEntity.length === 0
                                    onClicked: {
                                        if (control.kind === "number") adjustControl(tileItem, control, modelData)
                                        else Api.dashboardControl(tileItem, control, null, status, page)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Component {
        id: sensorOverview
        Item {
            property variant tileItem: parent ? parent.tileItem : ({})
            anchors.fill: parent
            Image { anchors.fill: parent; source: "images/settings/act_btn.svg"; fillMode: Image.Stretch }
            UbuntuLightText {
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                anchors.margins: 12; height: 24
                text: itemName(tileItem); textFormat: Text.PlainText
                font.pixelSize: 18; color: "white"; elide: Text.ElideRight
            }
            UbuntuLightText {
                anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                anchors.leftMargin: 12; anchors.rightMargin: 32; anchors.bottomMargin: 10
                height: 42; text: itemDetail(tileItem); textFormat: Text.PlainText
                font.pixelSize: text.length > 20 ? 18 : text.length > 12 ? 24 : 30
                color: detailColor(tileItem); elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
            UbuntuLightText { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; text: "\u203a"; font.pixelSize: 28; color: "white" }
            BeepingMouseArea { anchors.fill: parent; onClicked: openDetails(tileItem) }
        }
    }

    Flickable {
        id: notificationDetails
        visible: notificationsOpen
        anchors.top: header.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: detailStatus.top
        anchors.margins: 24
        clip: true
        contentWidth: width
        contentHeight: notificationColumn.height
        flickableDirection: Flickable.VerticalFlick
        Column {
            id: notificationColumn
            width: notificationDetails.width
            spacing: 20
            Repeater {
                model: notifications
                Column {
                    property variant notification: modelData
                    width: notificationColumn.width
                    spacing: 10
                    UbuntuLightText {
                        width: parent.width
                        text: notificationSymbol(notification) + "  " + notification.title
                        textFormat: Text.PlainText
                        font.pixelSize: 22
                        color: notificationColor(notification)
                        wrapMode: Text.Wrap
                    }
                    UbuntuLightText {
                        width: parent.width
                        text: notification.message
                        textFormat: Text.PlainText
                        font.pixelSize: 18
                        color: "white"
                        wrapMode: Text.Wrap
                    }
                    Flow {
                        width: parent.width
                        spacing: 8
                        enabled: dashboardOnline && pendingEntity.length === 0
                        Repeater {
                            model: notification.actions.concat([{action_id: null, label: uiText("dismiss_notification")}])
                            Item {
                                width: (notificationColumn.width - 8) / 2
                                height: 48
                                Image { anchors.fill: parent; source: "images/settings/list_btn.svg"; fillMode: Image.Stretch }
                                UbuntuLightText {
                                    anchors.fill: parent; anchors.margins: 8
                                    text: modelData.label; textFormat: Text.PlainText
                                    font.pixelSize: 17; color: "white"
                                    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                                BeepingMouseArea { anchors.fill: parent; onClicked: notificationAction(notification, modelData.action_id) }
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: "#c7d0d9"; opacity: 0.4 }
                }
            }
        }
    }

    Item {
        id: entitySummary
        property variant summary: selectedItem && selectedItem.details ? selectedItem.details : ({})
        property bool isCover: summary.type === "cover"
        visible: selectedItem !== null && selectedItem.details !== undefined && !notificationsOpen
        anchors.top: header.bottom
        anchors.left: parent.left; anchors.right: parent.right
        anchors.leftMargin: 24; anchors.rightMargin: 24
        height: visible ? (isCover ? 124 : 112) : 0
        Item {
            id: coverPreview
            visible: entitySummary.isCover
            width: visible ? 76 : 0; height: 92
            anchors.left: parent.left; anchors.top: parent.top; anchors.topMargin: 16
            Rectangle { anchors.fill: parent; color: "transparent"; border.color: "#c7d0d9"; border.width: 3 }
            Item {
                anchors.fill: parent; anchors.margins: 5; clip: true
                visible: dashboardOnline && selectedItem && selectedItem.available !== false && entitySummary.summary.position !== null && entitySummary.summary.position !== undefined
                Item {
                    width: parent.width
                    height: parent.height * (100 - safeNumber(entitySummary.summary.position, 100)) / 100
                    clip: true
                    Column {
                        width: parent.width; spacing: 2
                        Repeater { model: 10; Rectangle { width: coverPreview.width - 10; height: 7; color: "#c7d0d9" } }
                    }
                }
            }
            UbuntuLightText {
                anchors.centerIn: parent; text: "?"; font.pixelSize: 30; color: "#f1c40f"
                visible: !dashboardOnline || !selectedItem || selectedItem.available === false || entitySummary.summary.position === null || entitySummary.summary.position === undefined
            }
        }
        Column {
            anchors.left: parent.left; anchors.leftMargin: entitySummary.isCover ? 96 : 0
            anchors.right: summaryActions.left; anchors.rightMargin: 12
            anchors.top: parent.top; anchors.topMargin: 12
            spacing: 3
            UbuntuLightText {
                width: parent.width; height: 22
                text: entitySummary.summary.label ? uiText(entitySummary.summary.label) : uiText("current_state")
                textFormat: Text.PlainText; font.pixelSize: 16; color: "#c7d0d9"; elide: Text.ElideRight
            }
            UbuntuLightText {
                width: parent.width; height: 68
                text: detailValue(selectedItem); textFormat: Text.PlainText
                font.pixelSize: text.length > 24 ? 18 : text.length > 12 ? 24 : 38
                color: detailColor(selectedItem); wrapMode: Text.Wrap; elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
        }
        Item {
            id: summaryActions
            anchors.right: parent.right; anchors.top: parent.top
            width: entitySummary.isCover ? Math.min(240, parent.width * 0.42) : (entitySummary.summary.type === "sensor" || entitySummary.summary.type === "binary_sensor" ? 0 : parent.width * 0.4)
            height: parent.height
            UbuntuLightText {
                anchors.top: parent.top; anchors.topMargin: 16; width: parent.width; height: 40
                text: detailState(selectedItem); textFormat: Text.PlainText
                font.pixelSize: 18; color: detailColor(selectedItem); wrapMode: Text.Wrap; elide: Text.ElideRight
            }
            Row {
                anchors.top: parent.top; anchors.topMargin: 62; width: parent.width; spacing: 8
                visible: entitySummary.isCover
                Repeater {
                    model: entitySummary.isCover ? Api.dashboardCoverControls(selectedItem) : []
                    Item {
                        property variant control: modelData
                        width: (summaryActions.width - 16) / 3; height: 48
                        opacity: dashboardOnline && selectedItem && selectedItem.available !== false && pendingEntity.length === 0 ? 1 : 0.45
                        Image { anchors.fill: parent; source: "images/settings/list_btn.svg"; fillMode: Image.Stretch }
                        UbuntuLightText { anchors.centerIn: parent; text: controlLabel(control); font.pixelSize: 26; color: "white" }
                        BeepingMouseArea {
                            anchors.fill: parent
                            enabled: dashboardOnline && selectedItem && selectedItem.available !== false && pendingEntity.length === 0
                            onClicked: Api.dashboardControl(selectedItem, control, null, status, page)
                        }
                    }
                }
            }
        }
        Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: "#c7d0d9"; opacity: 0.4 }
    }

    Flickable {
        id: details
        visible: selectedItem !== null && !notificationsOpen
        anchors.top: entitySummary.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: detailStatus.top
        anchors.margins: 24
        clip: true
        contentWidth: width
        contentHeight: controlColumn.height
        flickableDirection: Flickable.VerticalFlick
        interactive: !interactionActive
        Column {
            id: controlColumn
            width: details.width
            spacing: 12
            UbuntuLightText {
                width: parent.width
                height: visible ? implicitHeight : 0
                visible: selectedItem !== null && selectedItem.details === undefined
                text: selectedItem ? itemDetail(selectedItem) : ""
                textFormat: Text.PlainText
                font.pixelSize: 18
                color: dashboardOnline ? "white" : "#f1c40f"
                wrapMode: Text.Wrap
            }
            Repeater {
                model: dashboardOnline && selectedItem && selectedItem.available !== false && selectedItem.details ? (selectedItem.details.fields || []) : []
                Row {
                    width: controlColumn.width; height: 44; spacing: 12
                    UbuntuLightText { width: (parent.width - 12) / 2; height: 44; text: uiText(modelData.label); textFormat: Text.PlainText; font.pixelSize: 18; color: "#c7d0d9"; elide: Text.ElideRight }
                    UbuntuLightText { width: (parent.width - 12) / 2; height: 44; text: modelData.value + " " + modelData.unit; textFormat: Text.PlainText; font.pixelSize: 24; color: "white"; elide: Text.ElideRight }
                }
            }
            Repeater {
                model: Api.dashboardDetailControls(selectedItem)
                Item {
                    id: controlRow
                    property variant control: modelData
                    property real preview: control.kind === "number" ? (control.value === null ? control.min : Number(control.value)) : 0
                    width: controlColumn.width
                    height: control.kind === "choice" ? 42 + optionGrid.height : control.kind === "number" ? (control.presets ? 150 : 96) : 44
                    enabled: dashboardOnline && selectedItem && selectedItem.available !== false && pendingEntity.length === 0
                    opacity: enabled ? 1 : 0.45
                    Image {
                        visible: control.kind === "button"
                        anchors.fill: parent
                        source: "images/settings/list_btn.svg"
                        fillMode: Image.Stretch
                    }
                    UbuntuLightText {
                        width: parent.width
                        height: 32
                        text: controlLabel(control) + (control.kind === "number" ? ": " + (sliderMouse.pressed ? preview + " " + (control.unit || "") : controlValue(control)) : "")
                        textFormat: Text.PlainText
                        font.pixelSize: 18
                        color: "white"
                        elide: Text.ElideRight
                    }
                    Row {
                        id: whitePresets
                        visible: control.kind === "number" && control.presets !== undefined
                        anchors.top: parent.top; anchors.topMargin: 36
                        width: parent.width; spacing: 8
                        Repeater {
                            model: control.presets || []
                            Item {
                                property variant preset: modelData
                                width: (controlRow.width - Math.max(0, (control.presets || []).length - 1) * 8) / Math.max(1, (control.presets || []).length)
                                height: 44
                                Image { anchors.fill: parent; source: control.active !== false && control.value === preset.value ? "images/settings/list_btn.svg" : "images/settings/act_btn.svg"; fillMode: Image.Stretch }
                                UbuntuLightText {
                                    anchors.fill: parent; anchors.margins: 6
                                    text: uiText(preset.label); textFormat: Text.PlainText; font.pixelSize: 16; color: "white"
                                    wrapMode: Text.Wrap; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                }
                                BeepingMouseArea { anchors.fill: parent; onClicked: Api.dashboardControl(selectedItem, control, String(preset.value), status, page) }
                            }
                        }
                    }
                    Row {
                        visible: control.kind === "number"
                        anchors.bottom: parent.bottom
                        spacing: 12
                        Repeater {
                            model: [-1, 1]
                            Item {
                                width: 52
                                height: 44
                                Image { anchors.fill: parent; source: "images/settings/list_btn.svg"; fillMode: Image.Stretch }
                                UbuntuLightText { anchors.centerIn: parent; text: modelData < 0 ? "-" : "+"; font.pixelSize: 24; color: "white" }
                                BeepingMouseArea { anchors.fill: parent; onClicked: adjustControl(selectedItem, control, modelData) }
                            }
                        }
                    }
                    Item {
                        id: sliderTrack
                        visible: control.kind === "number"
                        anchors.left: parent.left
                        anchors.leftMargin: 140
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 44
                        Rectangle { width: parent.width; height: 5; anchors.verticalCenter: parent.verticalCenter; color: "#c7d0d9" }
                        Rectangle {
                            width: 22; height: 30; radius: 4
                            color: "#58d68d"
                            anchors.verticalCenter: parent.verticalCenter
                            x: control.kind === "number" ? Math.max(0, Math.min(parent.width - width, (preview - control.min) / (control.max - control.min) * (parent.width - width))) : 0
                        }
                        BeepingMouseArea {
                            id: sliderMouse
                            anchors.fill: parent
                            function updatePreview(x) {
                                var ratio = Math.max(0, Math.min(1, x / width))
                                var steps = Math.min(Math.floor((control.max - control.min) / control.step), Math.round(ratio * (control.max - control.min) / control.step))
                                preview = Number((control.min + steps * control.step).toFixed(6))
                            }
                            onPressed: { interactionActive = true; updatePreview(mouse.x) }
                            onPositionChanged: if (pressed) updatePreview(mouse.x)
                            onReleased: {
                                interactionActive = false
                                Api.dashboardControl(selectedItem, control, String(preview), status, page)
                            }
                            onCanceled: { interactionActive = false; Api.dashboard(status, page) }
                        }
                    }
                    Grid {
                        id: optionGrid
                        visible: control.kind === "choice"
                        anchors.top: parent.top
                        anchors.topMargin: 38
                        width: parent.width
                        columns: control.swatches ? 4 : 2
                        spacing: 8
                        height: Math.ceil((control.options || []).length / columns) * 58
                        Repeater {
                            model: control.options || []
                            Item {
                                width: (optionGrid.width - (optionGrid.columns - 1) * 8) / optionGrid.columns
                                height: 50
                                Image { anchors.fill: parent; source: control.value === modelData ? "images/settings/list_btn.svg" : "images/settings/act_btn.svg"; fillMode: Image.Stretch }
                                Rectangle {
                                    visible: control.swatches !== undefined
                                    anchors.left: parent.left; anchors.leftMargin: 8; anchors.verticalCenter: parent.verticalCenter
                                    width: 24; height: 24; radius: 3
                                    color: control.swatches ? control.swatches[index] : "transparent"
                                    border.width: control.value === modelData ? 3 : 1
                                    border.color: "white"
                                }
                                UbuntuLightText {
                                    anchors.fill: parent; anchors.margins: 6; anchors.leftMargin: control.swatches ? 38 : 6
                                    text: optionLabel(control, modelData); textFormat: Text.PlainText; font.pixelSize: 16; color: "white"
                                    wrapMode: Text.Wrap; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                }
                                BeepingMouseArea { anchors.fill: parent; onClicked: Api.dashboardControl(selectedItem, control, modelData, status, page) }
                            }
                        }
                    }
                    Item {
                        visible: control.kind === "boolean"
                        anchors.right: parent.right; width: 124; height: 44
                        Rectangle { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; width: 30; height: 30; radius: 3; color: control.value === true ? "#58d68d" : "transparent"; border.color: "white"; border.width: 2 }
                        UbuntuLightText { anchors.left: parent.left; anchors.leftMargin: 44; anchors.verticalCenter: parent.verticalCenter; text: control.value === null ? "?" : uiText(control.value ? "on" : "off"); font.pixelSize: 18; color: "white" }
                        BeepingMouseArea { anchors.fill: parent; onClicked: Api.dashboardControl(selectedItem, control, control.value === true ? "false" : "true", status, page) }
                    }
                    BeepingMouseArea {
                        visible: control.kind === "button"
                        anchors.fill: parent
                        onClicked: Api.dashboardControl(selectedItem, control, null, status, page)
                    }
                }
            }
        }
    }

    UbuntuLightText {
        id: detailStatus
        visible: selectedItem !== null || notificationsOpen
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 24
        height: 32
        text: status.text
        textFormat: Text.PlainText
        color: status.color
        font.pixelSize: 16
        elide: Text.ElideRight
    }

    Column {
        visible: selectedItem === null && !notificationsOpen
        anchors.top: header.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.topMargin: 18
        anchors.leftMargin: 36
        anchors.rightMargin: 36
        anchors.bottomMargin: 18
        spacing: 9

        Item {
            id: notificationBanner
            width: parent.width
            height: notifications.length > 0 ? 44 : 0
            visible: notifications.length > 0
            Image { anchors.fill: parent; source: "images/settings/list_btn.svg"; fillMode: Image.Stretch }
            UbuntuLightText {
                anchors.fill: parent; anchors.margins: 9
                text: notifications.length > 0 ? notificationSymbol(notifications[0]) + "  " + notifications[0].title + " (" + notifications.length + ")" : ""
                textFormat: Text.PlainText; font.pixelSize: 18
                color: notifications.length > 0 ? notificationColor(notifications[0]) : "white"
                elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
            }
            BeepingMouseArea { anchors.fill: parent; onClicked: notificationsOpen = true }
        }

        Grid {
            id: badgeGrid
            width: parent.width
            columns: badgeColumnCount()
            spacing: 8
            height: badgeGridHeight()
            visible: badges.length > 0
            property int tileWidth: (width - (spacing * (columns - 1))) / columns

            Repeater {
                model: badges

                Item {
                    width: badgeGrid.tileWidth
                    height: 46

                    Image {
                        anchors.fill: parent
                        source: "images/settings/medium_list_btn.svg"
                        fillMode: Image.Stretch
                    }

                    UbuntuLightText {
                        text: (modelData.state || modelData.name || "") + trsl.empty
                        color: modelData.color || "white"
                        font.pixelSize: 17
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }

        Flickable {
            id: scroll
            width: parent.width
            height: parent.height - notificationBanner.height - (notificationBanner.visible ? 9 : 0) - badgeGrid.height - pagerRow.height - status.height - 32
            contentWidth: width
            contentHeight: contentColumn.height
            clip: true

            Column {
                id: contentColumn
                width: scroll.width
                spacing: 10

                UbuntuLightText {
                    text: pageTitle + trsl.empty
                    color: "white"
                    font.pixelSize: 24
                    width: parent.width
                    height: pageTitle.length > 0 ? 34 : 0
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }

                Item {
                    id: weatherCard
                    width: parent.width
                    height: weatherVisible ? 166 : 0
                    visible: weatherVisible
                    property int tileSpacing: 10
                    property int tileLeft: 18
                    property int tileWidth: (width - (tileLeft * 2) - (tileSpacing * 2)) / 3

                    Image {
                        anchors.fill: parent
                        source: "images/settings/act_btn.svg"
                        fillMode: Image.Stretch
                    }

                    Rectangle {
                        id: weatherNowTile
                        width: weatherCard.tileWidth
                        height: 92
                        radius: 8
                        color: weatherColor
                        border.color: "#ffffff"
                        border.width: 1
                        opacity: 0.94
                        anchors.left: parent.left
                        anchors.leftMargin: weatherCard.tileLeft
                        anchors.top: parent.top
                        anchors.topMargin: 14

                        UbuntuLightText {
                            text: weatherTemperature.length > 0 ? weatherTemperature : uiText("weather")
                            color: "white"
                            font.pixelSize: weatherTemperature.length > 7 ? 20 : 24
                            font.bold: true
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.topMargin: 8
                            height: 42
                            anchors.leftMargin: 5
                            anchors.rightMargin: 5
                            wrapMode: Text.WordWrap
                        }

                        UbuntuLightText {
                            text: weatherConditionText() + trsl.empty
                            color: "white"
                            font.pixelSize: 18
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 9
                            height: 34
                            anchors.leftMargin: 5
                            anchors.rightMargin: 5
                            elide: Text.ElideRight
                        }
                    }

                    Rectangle {
                        id: weatherForecastTile1
                        width: weatherCard.tileWidth
                        height: 92
                        radius: 8
                        color: "#1f2c36"
                        border.color: weatherColor
                        border.width: 2
                        opacity: 0.94
                        anchors.left: weatherNowTile.right
                        anchors.leftMargin: weatherCard.tileSpacing
                        anchors.top: weatherNowTile.top

                        UbuntuLightText {
                            text: weatherForecastTime(weatherForecast1) + trsl.empty
                            color: "#c7d0d9"
                            font.pixelSize: 14
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.topMargin: 7
                            height: 20
                            elide: Text.ElideRight
                        }

                        UbuntuLightText {
                            text: weatherForecastTemperature(weatherForecast1) + trsl.empty
                            color: "white"
                            font.pixelSize: 20
                            font.bold: true
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.topMargin: 30
                            height: 28
                            elide: Text.ElideRight
                        }

                        UbuntuLightText {
                            text: weatherForecastText(weatherForecast1) + trsl.empty
                            color: "#e6edf3"
                            font.pixelSize: 16
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 7
                            height: 25
                            anchors.leftMargin: 5
                            anchors.rightMargin: 5
                            elide: Text.ElideRight
                        }
                    }

                    Rectangle {
                        id: weatherForecastTile2
                        width: weatherCard.tileWidth
                        height: 92
                        radius: 8
                        color: "#1f2c36"
                        border.color: weatherColor
                        border.width: 2
                        opacity: 0.94
                        anchors.left: weatherForecastTile1.right
                        anchors.leftMargin: weatherCard.tileSpacing
                        anchors.top: weatherNowTile.top

                        UbuntuLightText {
                            text: weatherForecastTime(weatherForecast2) + trsl.empty
                            color: "#c7d0d9"
                            font.pixelSize: 14
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.topMargin: 7
                            height: 20
                            elide: Text.ElideRight
                        }

                        UbuntuLightText {
                            text: weatherForecastTemperature(weatherForecast2) + trsl.empty
                            color: "white"
                            font.pixelSize: 20
                            font.bold: true
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.topMargin: 30
                            height: 28
                            elide: Text.ElideRight
                        }

                        UbuntuLightText {
                            text: weatherForecastText(weatherForecast2) + trsl.empty
                            color: "#e6edf3"
                            font.pixelSize: 16
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 7
                            height: 25
                            anchors.leftMargin: 5
                            anchors.rightMargin: 5
                            elide: Text.ElideRight
                        }
                    }

                    UbuntuLightText {
                        text: weatherDetailsText() + trsl.empty
                        color: "#e6edf3"
                        font.pixelSize: 16
                        anchors.left: parent.left
                        anchors.leftMargin: 24
                        anchors.right: parent.right
                        anchors.rightMargin: 24
                        anchors.top: weatherNowTile.bottom
                        anchors.topMargin: 8
                        height: 22
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }

                    UbuntuLightText {
                        text: weatherSunText() + trsl.empty
                        color: "#c7d0d9"
                        font.pixelSize: 15
                        anchors.left: parent.left
                        anchors.leftMargin: 24
                        anchors.right: parent.right
                        anchors.rightMargin: 24
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 10
                        height: 22
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }
                }

                Item {
                    width: parent.width
                    height: flowVisible ? safeNumber(flowHeight, 0) : 0
                    visible: flowVisible

                    Rectangle {
                        id: flowWrapper
                        width: flowWidth > 0 ? flowWidth : parent.width
                        height: flowHeight > 0 ? flowHeight : parent.height
                        color: flowColor

                        Repeater {
                            id: flowLineRepeater
                            model: flowLines

                            PathView {
                                id: pathView
                                visible: true
                                property variant line: modelData
                                property variant lineColor: modelData.lineColor || modelData.color || "#58d68d"
                                model: safeNumber(modelData.numberOfDots, 0)
                                path: Path {
                                    startX: safeNumber(pathView.line.startX, 0)
                                    startY: safeNumber(pathView.line.startY, 0)
                                    PathQuad {
                                        x: safeNumber(pathView.line.x, 0)
                                        y: safeNumber(pathView.line.y, 0)
                                        controlX: safeNumber(pathView.line.controlX, 0)
                                        controlY: safeNumber(pathView.line.controlY, 0)
                                    }
                                }
                                delegate: Rectangle {
                                    width: safeNumber(pathView.line.dotWidth, 2)
                                    height: safeNumber(pathView.line.dotHeight, 2)
                                    color: pathView.lineColor
                                }
                            }
                        }

                        Repeater {
                            model: flowItems

                            Rectangle {
                                x: safeNumber(modelData.leftMargin, safeNumber(modelData.x, 0))
                                y: safeNumber(modelData.topMargin, safeNumber(modelData.y, 0))
                                width: safeNumber(modelData.width, 100)
                                height: safeNumber(modelData.height, 100)
                                radius: safeNumber(modelData.radius, 50)
                                color: modelData.backgroundColor || "transparent"
                                border.color: modelData.borderColor || "transparent"
                                border.width: safeNumber(modelData.borderWidth, 2)

                                UbuntuLightText {
                                    text: (modelData.labelText || modelData.label || "") + trsl.empty
                                    font.pixelSize: safeNumber(modelData.labelSize, 14)
                                    font.bold: true
                                    color: modelData.labelColor || "#8d98a3"
                                    anchors.top: parent.top
                                    anchors.topMargin: safeNumber(modelData.labelTopMargin, -20)
                                    anchors.horizontalCenter: parent.horizontalCenter
                                }

                                UbuntuLightText {
                                    text: (modelData.state || modelData.text || "") + trsl.empty
                                    font.pixelSize: safeNumber(modelData.textSize, 16)
                                    font.bold: modelData.textBold === false ? false : true
                                    color: modelData.textColor || "white"
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    anchors.fill: parent
                                    anchors.leftMargin: 6
                                    anchors.rightMargin: 6
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }
                }

                Flow {
                    id: itemColumn
                    enabled: dashboardOnline
                    width: parent.width
                    spacing: 10
                    visible: items.length > 0
                    height: visible ? implicitHeight : 0
                    property int tileWidth: (width - spacing) / 2

                    Component {
                        id: mixedImageTileComponent

                        Image {
                            property variant tileItem: parent ? parent.tileItem : ({})
                            cache: false
                            anchors.fill: parent
                            source: tileItem.source || ""
                            fillMode: Image.PreserveAspectFit
                        }
                    }

                    Component {
                        id: mixedEntityTileComponent

                        Item {
                            property variant tileItem: parent ? parent.tileItem : ({})
                            anchors.fill: parent

                            Image {
                                anchors.fill: parent
                                source: "images/settings/act_btn.svg"
                                fillMode: Image.Stretch
                            }

                            UbuntuLightText {
                                text: itemName(tileItem) + trsl.empty
                                color: "white"
                                font.pixelSize: 17
                                elide: Text.ElideRight
                                anchors.left: parent.left
                                anchors.leftMargin: 14
                                anchors.right: parent.right
                                anchors.rightMargin: 14
                                anchors.top: parent.top
                                anchors.topMargin: 9
                            }

                            UbuntuLightText {
                                text: itemDetail(tileItem) + trsl.empty
                                color: itemColor(tileItem)
                                font.pixelSize: 15
                                elide: Text.ElideRight
                                anchors.left: parent.left
                                anchors.leftMargin: 14
                                anchors.right: parent.right
                                anchors.rightMargin: 14
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 8
                            }
                        }
                    }

                    Component {
                        id: mixedSwitchTileComponent

                        Item {
                            property variant tileItem: parent ? parent.tileItem : ({})
                            anchors.fill: parent

                            Image {
                                anchors.fill: parent
                                source: "images/settings/act_btn.svg"
                                fillMode: Image.Stretch
                            }

                            UbuntuLightText {
                                text: itemName(tileItem) + trsl.empty
                                color: "white"
                                font.pixelSize: 17
                                elide: Text.ElideRight
                                anchors.left: parent.left
                                anchors.leftMargin: 14
                                anchors.right: switchButton.left
                                anchors.rightMargin: 8
                                anchors.verticalCenter: parent.verticalCenter
                            }

                            BasicButton {
                                id: switchButton
                                width: 86
                                height: 36
                                anchors.right: parent.right
                                anchors.rightMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                checkable: true
                                checked: tileItem.state
                                style: CheckableButtonStyle {
                                    defaultImage: "images/ringtones/switch-bg_btn.svg"
                                    checkedImage: "images/ringtones/switch-bg_btn_p.svg"
                                    defaultIconLeft: "images/ringtones/switch_btn.svg"
                                    defaultIconRight: "images/ringtones/disable_icon.svg"
                                    checkedIconLeft: "images/ringtones/enable_icon.svg"
                                    checkedIconRight: "images/ringtones/switch_btn_p.svg"
                                }
                                onTouched: Api.dashboardAction(tileItem, status, page)
                            }
                        }
                    }

                    Component {
                        id: mixedButtonTileComponent

                        Item {
                            property variant tileItem: parent ? parent.tileItem : ({})
                            anchors.fill: parent

                            Image {
                                anchors.fill: parent
                                source: tileMouse.pressed ? "images/first_configuration/list_btn_p.svg" : "images/settings/act_btn.svg"
                                fillMode: Image.Stretch
                            }

                            UbuntuLightText {
                                text: itemName(tileItem) + trsl.empty
                                color: "white"
                                font.pixelSize: 18
                                elide: Text.ElideRight
                                anchors.left: parent.left
                                anchors.leftMargin: 18
                                anchors.right: parent.right
                                anchors.rightMargin: 14
                                anchors.top: parent.top
                                anchors.topMargin: 10
                            }

                            UbuntuLightText {
                                text: itemDetail(tileItem) + trsl.empty
                                color: itemColor(tileItem)
                                font.pixelSize: 15
                                elide: Text.ElideRight
                                anchors.left: parent.left
                                anchors.leftMargin: 18
                                anchors.right: parent.right
                                anchors.rightMargin: 14
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 8
                            }

                            BeepingMouseArea {
                                id: tileMouse
                                anchors.fill: parent
                                onClicked: Api.dashboardAction(tileItem, status, page)
                            }
                        }
                    }

                    Component {
                        id: mixedSliderTileComponent

                        Item {
                            property variant tileItem: parent ? parent.tileItem : ({})
                            anchors.fill: parent

                            Image {
                                anchors.fill: parent
                                source: "images/settings/act_btn.svg"
                                fillMode: Image.Stretch
                            }

                            UbuntuLightText {
                                text: itemName(tileItem) + trsl.empty
                                color: "white"
                                font.pixelSize: 17
                                elide: Text.ElideRight
                                anchors.left: parent.left
                                anchors.leftMargin: 14
                                anchors.right: minusButton.left
                                anchors.rightMargin: 8
                                anchors.top: parent.top
                                anchors.topMargin: 9
                            }

                            UbuntuLightText {
                                text: sliderValueText(tileItem) + trsl.empty
                                color: itemColor(tileItem)
                                font.pixelSize: 15
                                elide: Text.ElideRight
                                anchors.left: parent.left
                                anchors.leftMargin: 14
                                anchors.right: minusButton.left
                                anchors.rightMargin: 8
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 8
                            }

                            Item {
                                id: minusButton
                                width: 48
                                height: 42
                                anchors.right: plusButton.left
                                anchors.rightMargin: 8
                                anchors.verticalCenter: parent.verticalCenter

                                Image {
                                    anchors.fill: parent
                                    source: minusMouse.pressed ? "images/first_configuration/list_btn_p.svg" : "images/first_configuration/list_btn.svg"
                                    fillMode: Image.Stretch
                                }

                                UbuntuLightText {
                                    text: "-" + trsl.empty
                                    color: "white"
                                    font.pixelSize: 26
                                    anchors.centerIn: parent
                                }

                                BeepingMouseArea {
                                    id: minusMouse
                                    anchors.fill: parent
                                    onClicked: Api.dashboardSliderAction(tileItem, "decrement", status, page)
                                }
                            }

                            Item {
                                id: plusButton
                                width: 48
                                height: 42
                                anchors.right: parent.right
                                anchors.rightMargin: 10
                                anchors.verticalCenter: parent.verticalCenter

                                Image {
                                    anchors.fill: parent
                                    source: plusMouse.pressed ? "images/first_configuration/list_btn_p.svg" : "images/first_configuration/list_btn.svg"
                                    fillMode: Image.Stretch
                                }

                                UbuntuLightText {
                                    text: "+" + trsl.empty
                                    color: "white"
                                    font.pixelSize: 26
                                    anchors.centerIn: parent
                                }

                                BeepingMouseArea {
                                    id: plusMouse
                                    anchors.fill: parent
                                    onClicked: Api.dashboardSliderAction(tileItem, "increment", status, page)
                                }
                            }
                        }
                    }

                    Component {
                        id: mixedChoiceTileComponent

                        Item {
                            property variant tileItem: parent ? parent.tileItem : ({})
                            anchors.fill: parent

                            Image {
                                anchors.fill: parent
                                source: "images/settings/act_btn.svg"
                                fillMode: Image.Stretch
                            }

                            UbuntuLightText {
                                text: itemName(tileItem) + trsl.empty
                                color: "white"
                                font.pixelSize: 17
                                elide: Text.ElideRight
                                anchors.left: parent.left
                                anchors.leftMargin: 14
                                anchors.right: parent.right
                                anchors.rightMargin: 14
                                anchors.top: parent.top
                                anchors.topMargin: 9
                            }

                            UbuntuLightText {
                                text: itemDetail(tileItem) + trsl.empty
                                color: itemColor(tileItem)
                                font.pixelSize: 15
                                elide: Text.ElideRight
                                anchors.left: parent.left
                                anchors.leftMargin: 14
                                anchors.right: parent.right
                                anchors.rightMargin: 14
                                anchors.top: parent.top
                                anchors.topMargin: 34
                            }

                            Grid {
                                id: mixedOptionGrid
                                columns: 3
                                spacing: 6
                                anchors.left: parent.left
                                anchors.leftMargin: 14
                                anchors.right: parent.right
                                anchors.rightMargin: 14
                                anchors.top: parent.top
                                anchors.topMargin: 60
                                visible: tileItem.options && tileItem.options.length > 0
                                property int optionWidth: (width - (spacing * 2)) / 3

                                Repeater {
                                    model: tileItem.options || []

                                    Item {
                                        width: mixedOptionGrid.optionWidth
                                        height: 36

                                        Image {
                                            anchors.fill: parent
                                            source: Api.dashboardChoiceOptionValue(modelData) === String(tileItem.value) || optionMouse.pressed ? "images/first_configuration/list_btn_p.svg" : "images/first_configuration/list_btn.svg"
                                            fillMode: Image.Stretch
                                        }

                                        UbuntuLightText {
                                            text: Api.dashboardChoiceOptionLabel(modelData) + trsl.empty
                                            color: "white"
                                            font.pixelSize: Api.dashboardChoiceOptionLabel(modelData).length > 12 ? 13 : 15
                                            elide: Text.ElideRight
                                            horizontalAlignment: Text.AlignHCenter
                                            verticalAlignment: Text.AlignVCenter
                                            anchors.fill: parent
                                            anchors.leftMargin: 6
                                            anchors.rightMargin: 6
                                        }

                                        BeepingMouseArea {
                                            id: optionMouse
                                            anchors.fill: parent
                                            onClicked: Api.dashboardChoiceAction(tileItem, Api.dashboardChoiceOptionValue(modelData), status, page)
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Repeater {
                        model: items

                        Item {
                            id: mixedTile
                            property variant tileItem: modelData
                            property bool isSwitch: tileItem.kind === "switch"
                            property bool isButton: tileItem.kind === "button"
                            property bool isSlider: tileItem.kind === "slider"
                            property bool isChoice: tileItem.kind === "choice"
                            property bool isImage: tileItem.kind === "image"
                            property bool hasControls: tileItem.controls !== undefined
                            property bool isSensor: tileItem.details !== undefined && (tileItem.details.type === "sensor" || tileItem.details.type === "binary_sensor")
                            width: hasControls || isChoice || isImage || isSlider ? itemColumn.width : itemColumn.tileWidth
                            height: hasControls ? 104 : isSensor ? 94 : (isImage ? safeNumber(tileItem.height, 120) : (isChoice ? 64 + Math.ceil((tileItem.options ? tileItem.options.length : 0) / 3) * 42 : (isSlider || isButton ? 64 : 58)))

                            Loader {
                                anchors.fill: parent
                                property variant tileItem: mixedTile.tileItem
                                sourceComponent: mixedTile.isSensor ? sensorOverview : mixedTile.hasControls ? controlOverview : (mixedTile.isImage ? mixedImageTileComponent : (mixedTile.isChoice ? mixedChoiceTileComponent : (mixedTile.isSlider ? mixedSliderTileComponent : (mixedTile.isSwitch ? mixedSwitchTileComponent : (mixedTile.isButton ? mixedButtonTileComponent : mixedEntityTileComponent)))))
                            }
                        }
                    }
                }

                UbuntuLightText {
                    text: items.length === 0 && !flowVisible && !weatherVisible ? uiText("dashboard_empty") + trsl.empty : ""
                    color: "#f1c40f"
                    font.pixelSize: 18
                    width: parent.width
                    height: text.length > 0 ? 32 : 0
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }

        Row {
            id: pagerRow
            width: parent.width
            height: pageCount > 1 ? 38 : 0
            visible: pageCount > 1
            spacing: 10

            Item {
                width: 90
                height: parent.height

                Image {
                    anchors.fill: parent
                    source: previousMouse.pressed ? "images/first_configuration/list_btn_p.svg" : "images/first_configuration/list_btn.svg"
                    fillMode: Image.Stretch
                }

                UbuntuLightText {
                    text: "<" + trsl.empty
                    color: "white"
                    font.pixelSize: 22
                    anchors.centerIn: parent
                }

                BeepingMouseArea {
                    id: previousMouse
                    anchors.fill: parent
                    onClicked: Api.dashboardPreviousPage(status, page)
                }
            }

            UbuntuLightText {
                text: pageLabel + trsl.empty
                color: "#c7d0d9"
                font.pixelSize: 17
                width: parent.width - 200
                height: parent.height
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }

            Item {
                width: 90
                height: parent.height

                Image {
                    anchors.fill: parent
                    source: nextMouse.pressed ? "images/first_configuration/list_btn_p.svg" : "images/first_configuration/list_btn.svg"
                    fillMode: Image.Stretch
                }

                UbuntuLightText {
                    text: ">" + trsl.empty
                    color: "white"
                    font.pixelSize: 22
                    anchors.centerIn: parent
                }

                BeepingMouseArea {
                    id: nextMouse
                    anchors.fill: parent
                    onClicked: Api.dashboardNextPage(status, page)
                }
            }
        }

        UbuntuLightText {
            id: status
            text: ""
            color: "#c7d0d9"
            font.pixelSize: 16
            width: parent.width
            height: 22
            elide: Text.ElideRight
        }
    }
}
