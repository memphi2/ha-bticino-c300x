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
    headerLabel: uiText("home_assistant") + trsl.empty

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

    function aboutToShow() {
        Api.dashboard(status, page)
    }

    function aboutToHide() {
        Api.stopDashboardRuntime()
    }

    function handleScreenOff() {
        Api.stopDashboardRuntime()
        return preventReturnToHomepage
    }

    function itemName(item) {
        return item.name || item.entity_id || uiText("action")
    }

    function itemDetail(item) {
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

    Column {
        anchors.top: header.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.topMargin: 18
        anchors.leftMargin: 36
        anchors.rightMargin: 36
        anchors.bottomMargin: 18
        spacing: 9

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
            height: parent.height - badgeGrid.height - pagerRow.height - status.height - 32
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
                    width: parent.width
                    spacing: 10
                    visible: items.length > 0
                    height: visible ? childrenRect.height : 0
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
                            width: isChoice || isImage || isSlider ? itemColumn.width : itemColumn.tileWidth
                            height: isImage ? safeNumber(tileItem.height, 120) : (isChoice ? 64 + Math.ceil((tileItem.options ? tileItem.options.length : 0) / 3) * 42 : (isSlider || isButton ? 64 : 58))

                            Loader {
                                anchors.fill: parent
                                property variant tileItem: mixedTile.tileItem
                                sourceComponent: mixedTile.isImage ? mixedImageTileComponent : (mixedTile.isChoice ? mixedChoiceTileComponent : (mixedTile.isSlider ? mixedSliderTileComponent : (mixedTile.isSwitch ? mixedSwitchTileComponent : (mixedTile.isButton ? mixedButtonTileComponent : mixedEntityTileComponent))))
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
