import QtQuick 1.1

Item {
    id: root
    property variant situations: ({})
    clip: true
    Flickable {
        id: list
        width: parent.width - (contentHeight > height ? 9 : 0)
        height: Math.floor((root.height + 8) / 52) * 52 - 8
        contentWidth: width
        contentHeight: content.height
        interactive: contentHeight > height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        onMovementEnded: contentY = Math.max(0, Math.min(contentHeight - height, Math.round(contentY / 52) * 52))
        C300XChecks {
            id: content
            width: list.width
            checks: root.situations && root.situations.checks ? root.situations.checks : []
            emptyText: root.situations && root.situations.empty_text ? root.situations.empty_text : ""
        }
    }
    Rectangle {
        anchors.right: parent.right
        y: list.visibleArea.yPosition * list.height
        width: 3
        height: list.visibleArea.heightRatio * list.height
        visible: list.contentHeight > list.height
        color: "white"
        opacity: 0.6
    }
}
