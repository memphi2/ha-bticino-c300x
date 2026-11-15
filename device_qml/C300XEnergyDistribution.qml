import QtQuick 1.1
import Components 1.0
import Components.Styles 1.0

Item {
    id: root
    objectName: "energyDistribution"
    property variant distribution: ({})
    property variant leftNodes: bounded(distribution ? distribution.left : undefined)
    property variant rightNodes: bounded(distribution ? distribution.right : undefined)
    property bool complete: distribution && distribution.complete === true
    property string statusText: distribution && distribution.status ? distribution.status :
                                (!complete ? (distribution && distribution.empty_text ? distribution.empty_text : "--") : "")
    property int statusHeight: statusText ? 36 : 8
    property real plotHeight: Math.max(0, height - statusHeight)
    property int labelWidth: 174
    property int labelGap: 12
    property int junctionWidth: 16
    property real bandWidth: Math.max(0, (width - junctionWidth) / 2 - labelWidth - labelGap)
    property real powerHeight: Math.max(0, plotHeight / 3 - 8)
    property real junctionY: (plotHeight - powerHeight) / 2
    property bool hasFlow: total(leftNodes) > 0 || total(rightNodes) > 0

    function bounded(value) {
        return value && typeof value !== "string" && value.length !== undefined ? value.slice(0, 3) : []
    }

    function normalized(value) {
        return typeof value === "number" && isFinite(value) ? Math.max(0, Math.min(1, value)) : 0
    }

    function total(nodes) {
        var size = 0
        for (var i = 0; i < nodes.length; i++) size += normalized(nodes[i].size)
        return size
    }

    function currentValue(node) {
        return node && node.value !== undefined && node.value !== null && node.value !== "" ? String(node.value) : "--"
    }

    Repeater {
        model: 2
        Item {
            id: side
            property bool incoming: index === 0
            property variant nodes: incoming ? root.leftNodes : root.rightNodes
            width: root.width
            height: root.plotHeight

            Repeater {
                model: side.nodes
                Item {
                    id: band
                    property variant node: modelData
                    property real rowCenter: (index + 0.5) * root.plotHeight / side.nodes.length
                    property real thickness: root.normalized(node.size) * root.powerHeight
                    property real outerY: rowCenter - thickness / 2
                    property real innerY: root.junctionY + Math.min(root.normalized(node.start),
                                                        1 - root.normalized(node.size)) * root.powerHeight
                    property color bandColor: node.color ? node.color : "#b3d9f2"
                    width: root.width
                    height: root.plotHeight

                    Item {
                        x: side.incoming ? root.labelWidth + root.labelGap : (root.width + root.junctionWidth) / 2
                        width: root.bandWidth
                        height: root.plotHeight

                        Repeater {
                            // Each side terminates at the shared junction; no source-to-load attribution.
                            model: root.complete && band.thickness > 0 ? 24 : 0
                            Rectangle {
                                objectName: "distributionSlice"
                                property real t: (index + 0.5) / 24
                                property real eased: t * t * (3 - 2 * t)
                                property real position: side.incoming ? eased : 1 - eased
                                x: Math.floor(index * root.bandWidth / 24)
                                y: band.outerY + (band.innerY - band.outerY) * position
                                width: Math.ceil((index + 1) * root.bandWidth / 24) - x
                                height: band.thickness
                                color: band.bandColor
                            }
                        }
                    }

                    UbuntuLightText {
                        x: side.incoming ? 0 : root.width - root.labelWidth
                        y: band.rowCenter - 22
                        width: root.labelWidth
                        height: 22
                        text: band.node.label || ""
                        color: "#e0eaf3"
                        font.pixelSize: 16
                        horizontalAlignment: side.incoming ? Text.AlignRight : Text.AlignLeft
                        elide: Text.ElideRight
                    }

                    UbuntuLightText {
                        x: side.incoming ? 0 : root.width - root.labelWidth
                        y: band.rowCenter
                        width: root.labelWidth
                        height: 22
                        text: root.currentValue(band.node)
                        color: "white"
                        font.pixelSize: 18
                        font.bold: true
                        horizontalAlignment: side.incoming ? Text.AlignRight : Text.AlignLeft
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }

    Rectangle {
        objectName: "distributionJunction"
        visible: root.complete && root.hasFlow
        x: (root.width - root.junctionWidth) / 2
        y: root.junctionY
        width: root.junctionWidth
        height: root.powerHeight * Math.min(1, Math.max(root.total(root.leftNodes), root.total(root.rightNodes)))
        color: "#dfebf4"
    }

    UbuntuLightText {
        visible: root.complete && !root.hasFlow
        x: root.labelWidth + root.labelGap
        y: (root.plotHeight - height) / 2
        width: Math.max(0, root.width - 2 * x)
        height: 40
        text: root.distribution && root.distribution.empty_text ? root.distribution.empty_text : ""
        color: "#e0eaf3"
        font.pixelSize: 16
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
        elide: Text.ElideRight
    }

    UbuntuLightText {
        visible: root.statusText !== ""
        y: root.plotHeight
        width: root.width
        height: root.statusHeight
        text: root.statusText
        color: root.complete ? "#e0eaf3" : "#ffe2a6"
        font.pixelSize: 14
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
        elide: Text.ElideRight
    }
}
