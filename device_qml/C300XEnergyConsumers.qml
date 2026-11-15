import QtQuick 1.1
import Components 1.0
import Components.Styles 1.0
import "js/c300x_energy_consumers.js" as Consumers

Item {
    id: root
    objectName: "energyConsumers"
    property variant consumers: ({})
    property variant rows: Consumers.rows(consumers)
    property variant leftScale: null
    property variant rightScale: null
    property bool initialized: false
    property string statusText: consumers && consumers.status ? consumers.status : ""
    property int statusHeight: statusText ? 24 : 0
    property int axisHeight: 30
    property real rowHeight: Math.max(0, (height - statusHeight - axisHeight) / 5)
    onRowsChanged: if (initialized) updateScales()
    onVisibleChanged: if (initialized) updateScales()
    Component.onCompleted: { initialized = true; updateScales() }

    function updateScales() {
        shrink.stop()
        if (!visible) return
        if (rows.length === 0) { leftScale = null; rightScale = null; return }
        var now = new Date().getTime()
        leftScale = Consumers.scale(leftScale, Consumers.domain(rows.slice(0, 5)), now)
        rightScale = rows.length > 5 ? Consumers.scale(rightScale, Consumers.domain(rows.slice(5, 10)), now) : null
        var deadline = Math.min(leftScale.deadline || Infinity, rightScale && rightScale.deadline ? rightScale.deadline : Infinity)
        if (isFinite(deadline)) { shrink.interval = Math.max(1, deadline - now); shrink.start() }
    }

    Timer { id: shrink; objectName: "consumersShrink"; repeat: false; onTriggered: root.updateScales() }

    Repeater {
        model: 2
        Item {
            id: column
            objectName: "consumerColumn"
            property int columnIndex: index
            property variant entries: root.rows.slice(index * 5, index * 5 + 5)
            property variant axis: index === 0 ? root.leftScale : root.rightScale
            x: index * (width + 24)
            width: Math.max(0, (root.width - 24) / 2)
            height: root.height - root.statusHeight
            visible: entries.length > 0

            Rectangle { y: 23; width: parent.width; height: 1; color: "#c7d0d9" }
            Repeater {
                model: Consumers.ticks(column.axis, column.width)
                Item {
                    width: column.width; height: column.height
                    Rectangle {
                        x: Math.min(column.width - 1, modelData.point); y: 20
                        width: 1; height: Math.max(0, parent.height - y)
                        color: "#c7d0d9"; opacity: 0.22
                    }
                    UbuntuLightText {
                        objectName: "consumerTick"
                        x: modelData.x; width: modelData.width; height: 18
                        text: modelData.label; textFormat: Text.PlainText
                        color: "#e0eaf3"; font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                    }
                }
            }
            Repeater {
                model: column.entries
                Item {
                    id: row
                    objectName: "consumerRow"
                    property variant consumer: modelData
                    property real fraction: Consumers.position(consumer.watts, column.axis)
                    y: root.axisHeight + index * root.rowHeight
                    width: column.width; height: root.rowHeight
                    UbuntuLightText {
                        objectName: "consumerName"
                        width: Math.max(0, row.width - exactValue.width - 8)
                        height: Math.max(0, row.height - 6)
                        text: row.consumer.label; textFormat: Text.PlainText
                        color: "white"; font.pixelSize: 16
                        verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                    }
                    UbuntuLightText {
                        id: exactValue
                        objectName: "consumerValue"
                        anchors.right: parent.right
                        height: Math.max(0, row.height - 6)
                        text: row.consumer.value; textFormat: Text.PlainText
                        color: Consumers.finite(row.consumer.watts) ? "white" : "#c7d0d9"
                        font.pixelSize: text.length > 16 ? 12 : 16
                        font.bold: true
                        verticalAlignment: Text.AlignVCenter
                    }
                    Rectangle {
                        y: row.height - 5; width: row.width; height: 4
                        color: "#e0eaf3"; opacity: 0.15
                    }
                    Rectangle {
                        objectName: "consumerBar"
                        y: row.height - 5; width: row.fraction * row.width; height: 4
                        color: row.consumer.color
                        visible: Consumers.finite(row.consumer.watts) && row.consumer.watts > 0
                    }
                }
            }
        }
    }
    UbuntuLightText {
        anchors.fill: parent
        visible: root.rows.length === 0
        text: root.consumers && root.consumers.empty_text ? root.consumers.empty_text : "--"
        color: "#e0eaf3"; font.pixelSize: 18
        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap; elide: Text.ElideRight
    }
    UbuntuLightText {
        y: root.height - root.statusHeight; width: root.width; height: root.statusHeight
        visible: root.statusText !== "" && root.rows.length > 0
        text: root.statusText; textFormat: Text.PlainText
        color: "#c7d0d9"; font.pixelSize: 13
        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
