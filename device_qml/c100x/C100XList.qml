import QtQuick 2.7

ListView {
    id: root
    property bool c100xScroll: true
    C100XMore { x: (root.width - width) / 2; shown: root.contentY > root.originY + 1; up: true }
    C100XMore {
        x: (root.width - width) / 2
        y: root.height - height
        shown: root.contentY < root.originY + root.contentHeight - root.height - 1
    }
}
