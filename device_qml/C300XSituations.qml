import QtQuick 1.1

Flickable {
    id: root
    property variant situations: ({})
    contentWidth: width
    contentHeight: content.height
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    C300XChecks {
        id: content
        width: root.width
        checks: root.situations && root.situations.checks ? root.situations.checks : []
        emptyText: root.situations && root.situations.empty_text ? root.situations.empty_text : ""
    }
}
