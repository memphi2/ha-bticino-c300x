import QtQuick 1.1
import Components 1.0
import Components.Styles 1.0

Item {
    id: root
    property variant leaveHome: ({})
    property variant checks: leaveHome && leaveHome.checks ? leaveHome.checks : []
    property variant actions: leaveHome && leaveHome.actions ? leaveHome.actions : []
    property variant alarm: leaveHome && leaveHome.alarm ? leaveHome.alarm : null
    property bool busy: false
    property bool online: true
    property string pendingActionId: ""
    signal actionRequested(variant item)
    signal alarmRequested()
    clip: true
    onLeaveHomeChanged: clearConfirmation()
    onBusyChanged: clearConfirmation()
    onOnlineChanged: clearConfirmation()
    onVisibleChanged: if (!visible) clearConfirmation()

    function clearConfirmation() {
        pendingActionId = ""
        confirmationTimer.stop()
    }

    function requestAction(item) {
        if (busy || !online || !visible) { clearConfirmation(); return }
        if (pendingActionId === item.entity_id) {
            clearConfirmation()
            actionRequested(item)
        } else {
            pendingActionId = item.entity_id
            confirmationTimer.restart()
        }
    }

    Timer {
        id: confirmationTimer
        interval: 8000
        repeat: false
        onTriggered: root.clearConfirmation()
    }

    Flickable {
        id: list
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.height
        interactive: contentHeight > height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        Column {
            id: content
            width: parent.width
            spacing: 8
            C300XChecks {
                width: content.width
                checks: root.checks
                emptyText: root.leaveHome && root.leaveHome.empty_text ? root.leaveHome.empty_text : ""
            }
            Item {
                width: content.width
                height: visible ? 54 : 0
                visible: !!root.alarm
                opacity: root.online && root.alarm && root.alarm.available ? 1 : 0.5
                Image {
                    anchors.fill: parent
                    source: "images/settings/act_btn.svg"
                    fillMode: Image.Stretch
                }
                UbuntuLightText {
                    anchors.fill: parent
                    anchors.margins: 10
                    text: root.alarm ? root.alarm.name + "  |  " + root.alarm.state_label : ""
                    font.pixelSize: 20
                    color: "white"
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                BeepingMouseArea {
                    id: alarmMouse
                    anchors.fill: parent
                    enabled: !root.busy && root.online && root.alarm && root.alarm.available
                    onClicked: { root.clearConfirmation(); root.alarmRequested() }
                }
            }
            Repeater {
                model: root.actions
                Item {
                    width: content.width
                    height: 54
                    property bool confirming: root.pendingActionId === modelData.entity_id
                    opacity: root.busy || !root.online ? 0.5 : 1
                    Image {
                        width: confirming ? parent.width * 0.68 - 8 : parent.width
                        height: parent.height
                        source: "images/settings/act_btn.svg"
                        fillMode: Image.Stretch
                    }
                    UbuntuLightText {
                        x: 10
                        width: (confirming ? parent.width * 0.68 - 8 : parent.width) - 20
                        height: parent.height
                        text: confirming ? root.leaveHome.confirm_label + ": " + modelData.name : modelData.name
                        textFormat: Text.PlainText
                        font.pixelSize: 20
                        color: "white"
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }
                    BeepingMouseArea {
                        id: actionMouse
                        width: confirming ? parent.width * 0.68 - 8 : parent.width
                        height: parent.height
                        enabled: !root.busy && root.online
                        onClicked: root.requestAction(modelData)
                    }
                    Item {
                        anchors.right: parent.right
                        width: parent.width * 0.32
                        height: parent.height
                        visible: confirming
                        Image { anchors.fill: parent; source: "images/settings/act_btn.svg"; fillMode: Image.Stretch }
                        UbuntuLightText {
                            anchors.fill: parent
                            anchors.margins: 8
                            text: root.leaveHome.cancel_label
                            font.pixelSize: 18
                            color: "white"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                        BeepingMouseArea { id: cancelMouse; anchors.fill: parent; onClicked: root.clearConfirmation() }
                    }
                }
            }
        }
    }
}
