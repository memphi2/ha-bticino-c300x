import QtQuick 1.1
import Components 1.0
import Components.Styles 1.0

Item {
    id: root
    property variant energy: ({})
    property string view: ""
    property variant views: listOf(energy ? energy.views : undefined)
    property string shown: hasView(view) ? view : (views.length > 0 ? views[0].id : "")
    property int tabHeight: views.length > 1 ? 40 : 0
    property int bodyHeight: Math.max(0, height - tabHeight - (tabHeight > 0 ? 8 : 0))
    property int boxWidth: 168
    property int boxHeight: 76
    property variant hours: energy && energy.hours ? energy.hours : ({})
    property variant series: listOf(hours ? hours.series : undefined)
    property real hoursMax: hours && hours.max > 0 ? hours.max : 0
    property int barsHeight: Math.max(40, Math.floor(bodyHeight * 0.42))

    function listOf(value) {
        return value && typeof value !== "string" && value.length !== undefined ? value : []
    }

    function hasView(id) {
        for (var i = 0; i < views.length; i++) {
            if (views[i].id === id) return true
        }
        return false
    }

    function hasNode(key) {
        var nodes = energy ? energy.nodes : undefined
        return nodes && nodes[key] ? true : false
    }

    function node(key) {
        return hasNode(key) ? energy.nodes[key] : ({})
    }

    function slotX(key) {
        if (key === "grid") return 0
        if (key === "home") return width - boxWidth
        return Math.floor((width - boxWidth) / 2)
    }

    function slotY(key) {
        if (key === "solar") return 0
        if (key === "battery") return bodyHeight - boxHeight
        return Math.floor((bodyHeight - boxHeight) / 2)
    }

    function lineText(info, index) {
        var lines = listOf(info ? info.lines : undefined)
        return index < lines.length ? lines[index] : ""
    }

    function stacked(hour, upto) {
        var total = 0
        for (var i = 0; i <= upto && i < series.length; i++) {
            var values = listOf(series[i].values)
            total += hour < values.length ? Math.max(0, values[hour]) : 0
        }
        return total
    }

    function barPixels(value) {
        return hoursMax > 0 ? Math.round(Math.min(1, value / hoursMax) * barsHeight) : 0
    }

    Item {
        width: parent.width
        height: bodyHeight
        visible: shown === "now"

        Repeater {
            model: ["solar", "grid", "home", "battery"]

            Item {
                id: link
                property variant info: root.node(modelData)
                property bool present: root.hasNode(modelData)
                property bool upright: modelData === "solar" || modelData === "battery"
                property int flow: present && info.flow ? info.flow : 0
                property int centerX: Math.floor(root.width / 2)
                property int centerY: Math.floor(bodyHeight / 2)
                visible: present
                x: upright ? centerX - 1 : (modelData === "grid" ? boxWidth : centerX)
                y: upright ? (modelData === "solar" ? boxHeight : centerY) : centerY - 1
                width: upright ? 3 : centerX - boxWidth
                height: upright ? centerY - boxHeight : 3

                Rectangle {
                    anchors.fill: parent
                    color: link.present ? link.info.color : "transparent"
                    opacity: link.flow === 0 ? 0.35 : 1
                }

                UbuntuLightText {
                    visible: link.flow !== 0
                    anchors.centerIn: parent
                    text: "\u25B6"
                    font.pixelSize: 18
                    color: link.present ? link.info.color : "white"
                    rotation: (modelData === "solar" ? 90 : modelData === "battery" ? 270 : 0) + (link.flow < 0 ? 180 : 0)
                }
            }
        }

        Repeater {
            model: ["solar", "grid", "home", "battery"]

            Item {
                id: box
                property variant info: root.node(modelData)
                property bool present: root.hasNode(modelData)
                visible: present
                x: root.slotX(modelData)
                y: root.slotY(modelData)
                width: boxWidth
                height: boxHeight

                Image {
                    anchors.fill: parent
                    source: "images/settings/act_btn.svg"
                    fillMode: Image.Stretch
                }

                Rectangle {
                    anchors.fill: parent
                    color: "transparent"
                    border.width: 2
                    border.color: box.present ? box.info.color : "transparent"
                }

                UbuntuLightText {
                    id: boxLabel
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.leftMargin: 10
                    anchors.topMargin: 6
                    width: parent.width - 20 - boxPower.paintedWidth - 6
                    text: box.present ? box.info.label : ""
                    color: "#c7d0d9"
                    font.pixelSize: 15
                    elide: Text.ElideRight
                }

                UbuntuLightText {
                    id: boxPower
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.rightMargin: 10
                    anchors.topMargin: 5
                    text: box.present && box.info.power ? box.info.power : ""
                    color: box.present ? box.info.color : "white"
                    font.pixelSize: 17
                    font.bold: true
                }

                UbuntuLightText {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: boxLabel.bottom
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    anchors.topMargin: root.lineText(box.info, 1).length > 0 ? 1 : 8
                    text: root.lineText(box.info, 0)
                    color: "white"
                    font.pixelSize: 18
                    elide: Text.ElideRight
                }

                UbuntuLightText {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    anchors.bottomMargin: 5
                    text: root.lineText(box.info, 1)
                    color: "#c7d0d9"
                    font.pixelSize: 16
                    elide: Text.ElideRight
                }
            }
        }
    }

    Item {
        width: parent.width
        height: bodyHeight
        visible: shown === "today"

        UbuntuLightText {
            id: barsTop
            text: hours && hours.label ? hours.label : ""
            color: "#c7d0d9"
            font.pixelSize: 13
        }

        Item {
            id: bars
            anchors.top: barsTop.bottom
            anchors.topMargin: 2
            width: parent.width
            height: barsHeight
            property int slotWidth: Math.floor(width / 24)

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: "#c7d0d9"
            }

            Repeater {
                model: 24

                Item {
                    id: slot
                    property int hour: index
                    x: index * bars.slotWidth
                    width: bars.slotWidth
                    height: bars.height

                    Repeater {
                        model: root.series

                        Rectangle {
                            x: 3
                            width: slot.width - 6
                            height: root.barPixels(root.stacked(slot.hour, index)) - root.barPixels(root.stacked(slot.hour, index - 1))
                            y: slot.height - root.barPixels(root.stacked(slot.hour, index))
                            color: modelData.color
                        }
                    }
                }
            }
        }

        Repeater {
            model: [0, 6, 12, 18]

            UbuntuLightText {
                x: modelData * bars.slotWidth + 3
                anchors.top: bars.bottom
                anchors.topMargin: 1
                text: modelData + ":00"
                color: "#c7d0d9"
                font.pixelSize: 13
            }
        }

        Grid {
            id: sums
            anchors.top: bars.bottom
            anchors.topMargin: 22
            width: parent.width
            columns: 2
            spacing: 4
            property int cellWidth: Math.floor((width - spacing) / 2)

            Repeater {
                model: root.listOf(energy ? energy.sums : undefined)

                Item {
                    width: sums.cellWidth
                    height: 24

                    Rectangle {
                        id: sumMark
                        anchors.verticalCenter: parent.verticalCenter
                        width: 10
                        height: 10
                        radius: 2
                        color: modelData.color
                    }

                    UbuntuLightText {
                        id: sumCost
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        width: 78
                        horizontalAlignment: Text.AlignRight
                        text: modelData.cost ? modelData.cost : ""
                        color: "#c7d0d9"
                        font.pixelSize: 15
                    }

                    UbuntuLightText {
                        id: sumValue
                        anchors.right: sumCost.left
                        anchors.rightMargin: 6
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.value
                        color: "white"
                        font.pixelSize: 16
                    }

                    UbuntuLightText {
                        anchors.left: sumMark.right
                        anchors.leftMargin: 8
                        anchors.right: sumValue.left
                        anchors.rightMargin: 6
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.label
                        color: "#c7d0d9"
                        font.pixelSize: 16
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }

    Column {
        id: balanceView
        width: parent.width
        height: bodyHeight
        visible: shown === "balance"
        spacing: 12

        Repeater {
            model: root.listOf(energy ? energy.balance : undefined)

            Item {
                id: balanceRow
                property bool hasRatio: modelData.ratio !== undefined
                width: balanceView.width
                height: hasRatio ? 50 : 30

                UbuntuLightText {
                    anchors.left: parent.left
                    anchors.right: balanceValue.left
                    anchors.rightMargin: 10
                    text: modelData.label
                    color: "#c7d0d9"
                    font.pixelSize: 19
                    elide: Text.ElideRight
                }

                UbuntuLightText {
                    id: balanceValue
                    anchors.right: parent.right
                    text: modelData.value
                    color: "white"
                    font.pixelSize: 21
                    font.bold: true
                }

                Item {
                    id: track
                    visible: balanceRow.hasRatio
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 12

                    Rectangle {
                        anchors.fill: parent
                        color: "black"
                        opacity: 0.35
                    }

                    Rectangle {
                        width: Math.round(track.width * Math.max(0, Math.min(1, balanceRow.hasRatio ? modelData.ratio : 0)))
                        height: parent.height
                        color: modelData.color
                    }
                }
            }
        }
    }

    Row {
        id: tabs
        anchors.bottom: parent.bottom
        width: parent.width
        height: tabHeight
        visible: tabHeight > 0
        spacing: 10
        property int tabWidth: views.length > 0 ? Math.floor((width - spacing * (views.length - 1)) / views.length) : 0

        Repeater {
            model: root.views

            Item {
                width: tabs.tabWidth
                height: tabs.height

                Image {
                    anchors.fill: parent
                    source: tabMouse.pressed || root.shown === modelData.id ? "images/settings/list_btn.svg" : "images/settings/act_btn.svg"
                    fillMode: Image.Stretch
                }

                UbuntuLightText {
                    anchors.centerIn: parent
                    text: modelData.label
                    color: "white"
                    font.pixelSize: 18
                    font.bold: root.shown === modelData.id
                }

                Rectangle {
                    visible: root.shown === modelData.id
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 3
                    color: "white"
                }

                BeepingMouseArea {
                    id: tabMouse
                    anchors.fill: parent
                    onClicked: root.view = modelData.id
                }
            }
        }
    }
}
