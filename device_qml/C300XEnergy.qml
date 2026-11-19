import QtQuick 1.1
import Components 1.0
import Components.Styles 1.0
import "js/c300x_energy.js" as EnergyChart

Item {
    id: root
    signal pressing(variant area)
    signal canceling(variant area)
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
    property variant hoursAxis: hours && hours.axis ? hours.axis : ({})
    property variant nodes: energy && energy.nodes ? energy.nodes : ({})
    property variant sumRows: listOf(energy ? energy.sums : undefined)
    property int sumsHeight: Math.ceil(sumRows.length / 2) * 22
    property bool sumCosts: hasCosts()
    property int barsHeight: Math.max(40, bodyHeight - 56 - sumsHeight)
    property int balanceGap: bodyHeight < 220 ? 4 : 12
    property int axisWidth: 62
    property variant powerHistory: ({})
    property variant powerAxis: powerHistory && powerHistory.axis ? powerHistory.axis : ({})
    property variant powerSeries: listOf(powerHistory ? powerHistory.series : undefined)
    property int legendHeight: Math.ceil(powerSeries.length / 2) * 22
    property int selectedHour: -1
    property int selectedPower: -1
    property int powerBuckets: EnergyChart.count(powerSeries)
    onShownChanged: { selectedHour = -1; selectedPower = -1 }
    onVisibleChanged: { if (!visible) { selectedHour = -1; selectedPower = -1 } }
    onPowerHistoryChanged: selectedPower = -1
    onEnergyChanged: syncPower()
    Component.onCompleted: syncPower()

    function syncPower() {
        var next = energy && energy.power ? energy.power : ({})
        if (!next.revision || !powerHistory || next.revision !== powerHistory.revision) powerHistory = next
    }

    function listOf(value) {
        return value && typeof value !== "string" && value.length !== undefined ? value : []
    }

    function hasView(id) {
        for (var i = 0; i < views.length; i++) {
            if (views[i].id === id) return true
        }
        return false
    }

    function hasCosts() {
        var rows = sumRows
        for (var i = 0; i < rows.length; i++) {
            if (rows[i].cost) return true
        }
        return false
    }

    function hasNode(key) {
        var all = nodes
        return all && all[key] ? true : false
    }

    function node(key) {
        var all = nodes
        return all && all[key] ? all[key] : ({})
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
                property color flowColor: info.color ? info.color : "transparent"
                property bool upright: modelData === "solar" || modelData === "battery"
                property int flow: present && info.flow ? info.flow : 0
                property int centerX: Math.floor(root.width / 2)
                property int centerY: Math.floor(bodyHeight / 2)
                property int laneWidth: Math.floor((root.width - 3 * boxWidth) / 2) - 12
                property bool leftLane: modelData === "solar" || modelData === "grid"
                visible: present
                z: upright ? 0 : 1
                x: leftLane ? boxWidth + 12 : root.width - boxWidth - 12 - laneWidth
                y: (upright ? root.slotY(modelData) + boxHeight / 2 : centerY) - 1
                width: laneWidth
                height: 3

                Rectangle {
                    x: link.upright ? 0 : (modelData === "grid" ? -12 : link.centerX - link.x)
                    width: link.upright ? link.width : link.centerX - boxWidth
                    height: 3
                    color: link.flowColor
                    opacity: link.flow === 0 ? 0.35 : 1
                }

                // Side branches leave room below every arrow, even with notifications and tabs.
                Rectangle {
                    visible: link.upright
                    x: modelData === "solar" ? 0 : link.width - 3
                    y: Math.min(0, link.centerY - 1 - link.y)
                    width: 3
                    height: Math.abs(link.centerY - 1 - link.y) + 3
                    color: link.flowColor
                    opacity: link.flow === 0 ? 0.35 : 1
                }

                Rectangle {
                    visible: link.upright
                    x: modelData === "solar" ? 0 : link.centerX - link.x
                    y: link.centerY - 1 - link.y
                    width: modelData === "solar" ? link.centerX - link.x : link.x + link.width - link.centerX
                    height: 3
                    color: link.flowColor
                    opacity: link.flow === 0 ? 0.35 : 1
                }

                UbuntuLightText {
                    id: flowArrow
                    visible: link.flow !== 0
                    anchors.centerIn: parent
                    width: 20
                    height: 20
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: "\u25B6"
                    font.pixelSize: 18
                    color: link.flowColor
                    rotation: (modelData === "solar" ? 180 : 0) + (link.flow < 0 ? 180 : 0)
                }

                UbuntuLightText {
                    id: flowPower
                    anchors.top: flowArrow.bottom
                    anchors.topMargin: 2
                    anchors.horizontalCenter: flowArrow.horizontalCenter
                    width: link.width - 8
                    height: 22
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    text: link.present && link.info.power ? link.info.power : ""
                    color: link.flowColor
                    font.pixelSize: 17
                    font.bold: true
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
                    width: parent.width - 20
                    text: box.present ? box.info.label : ""
                    color: "#c7d0d9"
                    font.pixelSize: 15
                    elide: Text.ElideRight
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
        id: todayView
        width: parent.width
        height: bodyHeight
        visible: shown === "today"

        UbuntuLightText {
            id: barsTop
            width: root.axisWidth - 8
            height: 18
            text: hoursAxis.unit ? hoursAxis.unit : "kWh"
            color: "white"
            font.pixelSize: 13
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideRight
        }

        Item {
            id: bars
            anchors.top: barsTop.bottom
            anchors.topMargin: 10
            x: root.axisWidth
            width: parent.width - x - 8
            height: barsHeight
            property real slotWidth: width / 24
            property int tickLabelStep: Math.max(1, Math.ceil((root.listOf(hoursAxis.ticks).length - 1) * 16 / height))
            property int tickLabelBase: {
                var ticks = root.listOf(hoursAxis.ticks)
                for (var i = 0; i < ticks.length; i++) if (ticks[i].value === 0) return i
                return 0
            }

            Rectangle {
                anchors.fill: parent
                color: "#041b3b"
                opacity: 0.45
            }

            Repeater {
                model: root.listOf(hoursAxis.ticks)

                Item {
                    y: Math.round((1 - modelData.position) * bars.height)
                    width: bars.width
                    height: 1

                    Rectangle {
                        width: parent.width
                        height: 1
                        color: "white"
                        opacity: modelData.value === 0 ? 0.65 : 0.23
                    }

                    UbuntuLightText {
                        visible: (index - bars.tickLabelBase) % bars.tickLabelStep === 0
                        x: -root.axisWidth
                        y: -7
                        width: root.axisWidth - 8
                        height: 15
                        text: modelData.label
                        color: "white"
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignRight
                        elide: Text.ElideRight
                    }
                }
            }

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
                        model: root.shown === "today" ? root.series : []

                        Rectangle {
                            objectName: "energyHourBar"
                            property variant segment: EnergyChart.barSegment(root.series, slot.hour, index, root.hoursAxis, slot.height)
                            x: 2
                            width: Math.max(1, slot.width - 4)
                            height: segment.height
                            y: segment.y
                            color: modelData.color
                        }
                    }
                }
            }
            Rectangle {
                objectName: "energyHourMarker"
                visible: root.selectedHour >= 0
                x: root.selectedHour * bars.slotWidth
                width: bars.slotWidth
                height: parent.height
                color: "transparent"
                border.color: "white"
                border.width: 1
            }
            MouseArea {
                objectName: "energyHoursTap"
                anchors.fill: parent
                enabled: root.series.length > 0
                onClicked: root.selectedHour = EnergyChart.bucket(mouseX, width, 24)
            }
        }

        Repeater {
            model: [0, 6, 12, 18, 24]

            UbuntuLightText {
                x: bars.x + modelData * bars.slotWidth - (modelData === 24 ? width : modelData === 0 ? 0 : width / 2)
                width: 40
                height: 17
                anchors.top: bars.bottom
                anchors.topMargin: 1
                text: (modelData < 10 ? "0" : "") + modelData + ":00"
                color: "white"
                font.pixelSize: 12
                horizontalAlignment: modelData === 24 ? Text.AlignRight : modelData === 0 ? Text.AlignLeft : Text.AlignHCenter
            }
        }

        C300XEnergySums {
            id: sums
            anchors.top: bars.bottom
            anchors.topMargin: 26
            width: parent.width
            visible: root.selectedHour < 0
            rows: root.sumRows
            costs: root.sumCosts
        }

        C300XEnergyReadout {
            anchors.fill: parent
            visible: root.selectedHour >= 0
            axisWidth: root.axisWidth
            rowsY: sums.y
            interval: EnergyChart.interval(root.selectedHour, 60, 24)
            rows: visible ? EnergyChart.todayRows(root.hours, root.sumRows, root.selectedHour) : []
            onDismissed: root.selectedHour = -1
        }
    }

    Item {
        id: powerView
        width: parent.width
        height: bodyHeight
        visible: shown === "power"

        UbuntuLightText {
            width: root.axisWidth - 8
            height: 18
            text: powerAxis.unit ? powerAxis.unit : "W"
            color: "white"
            font.pixelSize: 13
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideRight
        }

        UbuntuLightText {
            x: root.axisWidth
            visible: root.selectedPower < 0
            width: parent.width - x - 8
            height: 18
            text: powerHistory.label ? powerHistory.label : ""
            color: "#e3e9f1"
            font.pixelSize: 13
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideRight
        }

        Item {
            id: powerPlot
            x: root.axisWidth
            y: 28
            width: parent.width - x - 8
            height: Math.max(40, bodyHeight - y - 26 - root.legendHeight)

            Rectangle {
                anchors.fill: parent
                color: "#041b3b"
                opacity: 0.45
            }

            Repeater {
                model: root.listOf(powerAxis.ticks)

                Item {
                    y: Math.round((1 - modelData.position) * powerPlot.height)
                    width: powerPlot.width
                    height: 1

                    Rectangle {
                        width: parent.width
                        height: 1
                        color: "white"
                        opacity: modelData.value === 0 ? 0.65 : 0.23
                    }

                    UbuntuLightText {
                        x: -root.axisWidth
                        y: -7
                        width: root.axisWidth - 8
                        height: 15
                        text: modelData.label
                        color: "white"
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignRight
                        elide: Text.ElideRight
                    }
                }
            }

            Item {
                anchors.fill: parent
                clip: true

                Repeater {
                    model: root.shown === "power" ? root.powerSeries : []

                    Item {
                        id: curve
                        property variant points: EnergyChart.points(modelData.values, root.powerAxis)
                        property variant dots: root.listOf(modelData.dots)
                        property color curveColor: modelData.color
                        anchors.fill: parent

                        Repeater {
                            model: Math.max(0, curve.points.length - 1)

                            Rectangle {
                                property variant a: curve.points[index]
                                property variant b: curve.points[index + 1]
                                property bool connected: a !== null && a !== undefined && b !== null && b !== undefined
                                property real dx: connected ? powerPlot.width / curve.points.length : 0
                                property real dy: connected ? (a - b) * powerPlot.height : 0
                                visible: connected
                                x: connected ? (index + 0.5) * powerPlot.width / curve.points.length : 0
                                y: connected ? (1 - a) * powerPlot.height - 1 : 0
                                width: Math.sqrt(dx * dx + dy * dy)
                                height: 2
                                color: curve.curveColor
                                rotation: Math.atan2(dy, dx) * 180 / Math.PI
                                transformOrigin: Item.TopLeft
                                smooth: true
                            }
                        }

                        Repeater {
                            model: curve.dots

                            Rectangle {
                                x: (modelData + 0.5) * powerPlot.width / curve.points.length - 2
                                y: (1 - curve.points[modelData]) * powerPlot.height - 2
                                width: 4
                                height: 4
                                radius: 2
                                color: curve.curveColor
                            }
                        }
                    }
                }
            }

            UbuntuLightText {
                visible: root.powerSeries.length === 0
                anchors.fill: parent
                anchors.margins: 12
                text: powerHistory.empty_text ? powerHistory.empty_text : ""
                font.pixelSize: 18
                color: "white"
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                wrapMode: Text.WordWrap
                elide: Text.ElideRight
            }
            Rectangle {
                objectName: "energyPowerMarker"
                visible: root.selectedPower >= 0
                x: root.powerBuckets > 0 ? (root.selectedPower + 0.5) * parent.width / root.powerBuckets : 0
                width: 1
                height: parent.height
                color: "white"
                opacity: 0.65
            }
            MouseArea {
                objectName: "energyPowerTap"
                anchors.fill: parent
                enabled: root.powerBuckets > 0 && EnergyChart.timestamp(root.powerHistory, 0) !== "--"
                onClicked: root.selectedPower = EnergyChart.bucket(mouseX, width, root.powerBuckets)
            }
        }

        Repeater {
            model: root.listOf(powerHistory.times)

            UbuntuLightText {
                property real position: modelData.position
                x: powerPlot.x + position * powerPlot.width - (position === 1 ? width : position === 0 ? 0 : width / 2)
                y: powerPlot.y + powerPlot.height + 3
                width: 40
                height: 17
                text: modelData.label
                color: "white"
                font.pixelSize: 12
                horizontalAlignment: position === 1 ? Text.AlignRight : position === 0 ? Text.AlignLeft : Text.AlignHCenter
            }
        }

        Grid {
            id: powerLegend
            visible: root.selectedPower < 0
            x: root.axisWidth
            y: powerPlot.y + powerPlot.height + 26
            width: parent.width - x
            height: root.legendHeight
            columns: 2
            spacing: 0

            Repeater {
                model: root.powerSeries

                Item {
                    width: powerLegend.width / 2
                    height: 22

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 22
                        height: 3
                        color: modelData.color
                    }

                    UbuntuLightText {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: 30
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.label
                        font.pixelSize: 14
                        color: "white"
                        elide: Text.ElideRight
                    }
                }
            }
        }

        C300XEnergyReadout {
            anchors.fill: parent
            visible: root.selectedPower >= 0
            axisWidth: root.axisWidth
            rowsY: powerLegend.y
            interval: EnergyChart.timestamp(root.powerHistory, root.selectedPower)
            rows: visible ? EnergyChart.powerRows(root.powerHistory, root.selectedPower) : []
            onDismissed: root.selectedPower = -1
        }
    }

    Loader {
        id: consumersLoader
        width: parent.width
        height: bodyHeight
        source: root.visible && shown === "consumers" ? "C300XEnergyConsumers.qml" : ""
        Binding {
            target: consumersLoader.item
            property: "consumers"
            value: root.energy && root.energy.consumers ? root.energy.consumers : ({})
            when: consumersLoader.status === Loader.Ready
        }
    }

    Column {
        id: balanceView
        width: parent.width
        height: bodyHeight
        visible: shown === "balance"
        spacing: root.balanceGap

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
                    anchors.fill: parent
                    anchors.margins: 6
                    text: modelData.label
                    color: "white"
                    font.pixelSize: root.views.length > 4 ? 16 : 18
                    font.bold: root.shown === modelData.id
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
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
                    onPressed: root.pressing(tabMouse)
                    onCanceled: root.canceling(tabMouse)
                    onClicked: root.view = modelData.id
                }
            }
        }
    }
}
