import QtQuick 1.1
import BtObjects 2.0
import BtClass 1.0
import "js/c300x_alerts.js" as Alerts

Item {
    id: root
    property bool blocked: true
    property bool stopped: false
    property variant controller: null
    property variant notice: null
    property variant pendingRequest: null
    property variant ackRequest: null
    property string acknowledgeLabel: "OK"
    property color accent: !notice || notice.severity === "info" ? "#68baff" : notice.severity === "warning" ? "#f1c40f" : "#ff6b6b"
    onBlockedChanged: if (blocked) preempt()
    onVisibleChanged: if (!visible) preempt()

    function preempt() {
        if (controller) controller.preempt()
    }

    function userInteraction() {
        if (controller) controller.userInteraction()
    }

    function acknowledge() {
        if (controller) controller.acknowledge()
    }

    function soundReady() {
        var audio = global.audioState
        return !stopped && !blocked && !audio.audioAccess &&
            (audio.state === AudioState.Idle || audio.state === AudioState.Beep ||
             audio.state === AudioState.RingtoneMute)
    }

    function shortBeep(stillCurrent) {
        if (!stillCurrent() || !soundReady()) return false
        var audio = global.audioState
        var prior = audio.isStateEnabled(AudioState.Beep)
        try {
            if (!prior) audio.enableState(AudioState.Beep)
            if (stillCurrent() && soundReady()) { global.beep(); return true }
        } finally {
            // Restore only our temporary low-priority RAM flag, never a call state.
            if (!prior) audio.disableState(AudioState.Beep)
        }
        return false
    }

    function waitForCommand() {
        if (stopped || pendingRequest) return
        var request = new XMLHttpRequest()
        pendingRequest = request
        request.onreadystatechange = function() {
            if (stopped || pendingRequest !== request || request.readyState !== XMLHttpRequest.DONE) return
            pendingRequest = null
            var valid = false
            if (request.status === 200 && request.responseText.length <= 16384) {
                try {
                    var command = JSON.parse(request.responseText)
                    valid = !!Alerts.validate(command, new Date().getTime())
                    if (valid && controller) controller.receive(command)
                } catch (error) { valid = false }
            }
            if (valid) waitForCommand()
            else reconnect.restart()
        }
        try {
            request.open("GET", "http://127.0.0.1:8090/ui/alerts/next", true)
            request.setRequestHeader("X-C300X-GUI", "alerts-v1")
            request.send()
        } catch (error) {
            pendingRequest = null
            request.onreadystatechange = function() {}
            request.abort()
            if (!stopped) reconnect.restart()
        }
    }

    function sendAcknowledgement(command) {
        if (stopped) return
        abortAcknowledgement()
        var request = new XMLHttpRequest()
        ackRequest = request
        request.onreadystatechange = function() {
            if (stopped || ackRequest !== request || request.readyState !== XMLHttpRequest.DONE) return
            ackRequest = null
            ackTimeout.stop()
        }
        var option = JSON.stringify({revision: command.revision, action_id: null})
        var url = "http://127.0.0.1:8090/homeassistant?domain=c300x&service=toggle&entities=" +
            encodeURIComponent("notification." + command.notification_id) + "&option=" + encodeURIComponent(option)
        try {
            request.open("GET", url, true)
            ackTimeout.restart()
            request.send()
        } catch (error) { abortAcknowledgement() }
    }

    function abortAcknowledgement() {
        ackTimeout.stop()
        var request = ackRequest
        ackRequest = null
        if (request) { request.onreadystatechange = function() {}; request.abort() }
    }

    function initialize() {
        controller = Alerts.createController({
            now: function() { return new Date().getTime() },
            blocked: function() { return root.blocked || root.stopped || !root.visible },
            screen: function() { return global.screenState.state },
            normal: ScreenState.Normal, off: ScreenState.ScreenOff,
            idleInterval: function() { return global.screenState.screensaverInterval },
            simulateClick: function() { global.screenState.simulateClick() },
            releaseNormal: function() { global.screenState.disableState(ScreenState.Normal) },
            soundReady: function() { return root.soundReady() },
            beep: function(guard) { return root.shortBeep(guard) },
            show: function(command) { root.notice = command; messageScroll.contentY = 0; effects.restart() },
            hide: function() { effects.stop(); root.notice = null },
            ack: function(command) { root.sendAcknowledgement(command) }
        })
        waitForCommand()
    }

    function shutdown() {
        stopped = true
        if (controller) controller.destroy()
        effects.stop()
        reconnect.stop()
        abortAcknowledgement()
        var request = pendingRequest
        pendingRequest = null
        if (request) { request.onreadystatechange = function() {}; request.abort() }
        controller = null
    }

    Connections {
        target: global.screenState
        onStateChangedInt: if (root.controller) root.controller.screenChanged()
    }
    Timer { id: effects; interval: 250; repeat: true; onTriggered: if (root.controller) root.controller.tick() }
    Timer { id: reconnect; interval: 30000; repeat: false; onTriggered: root.waitForCommand() }
    Timer { id: ackTimeout; interval: 10000; repeat: false; onTriggered: root.abortAcknowledgement() }
    Component.onCompleted: initialize()
    Component.onDestruction: shutdown()

    Rectangle {
        id: panel
        visible: !!root.notice && !root.blocked
        anchors.centerIn: parent
        width: Math.max(0, parent.width - 24)
        height: Math.max(0, Math.min(parent.height - 24, 370))
        color: "#176196"
        border.color: root.accent
        border.width: 2
        radius: 4
        clip: true
        MouseArea { anchors.fill: parent; onPressed: root.userInteraction() }
        Text {
            id: severityLabel
            x: 16; y: 10; width: parent.width - 32; height: 30
            text: !root.notice ? "" : root.notice.severity === "info" ? "i  Info" : root.notice.severity === "warning" ? "!  Warning" : "!  Error"
            textFormat: Text.PlainText
            font.pixelSize: 20
            color: root.accent
            elide: Text.ElideRight
        }
        Text {
            id: titleLabel
            x: 16; y: 44; width: parent.width - 32; height: 58
            text: root.notice ? root.notice.title : ""
            textFormat: Text.PlainText
            font.pixelSize: 22
            color: "white"
            wrapMode: Text.Wrap
            elide: Text.ElideRight
            maximumLineCount: 2
        }
        Flickable {
            id: messageScroll
            x: 16; y: 108; width: parent.width - 32
            height: Math.max(0, acknowledgeButton.y - y - 12)
            contentWidth: width; contentHeight: messageLabel.height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            onMovementStarted: root.userInteraction()
            Text {
                id: messageLabel
                width: messageScroll.width
                text: root.notice ? root.notice.message : ""
                textFormat: Text.PlainText
                font.pixelSize: 20
                color: "white"
                wrapMode: Text.Wrap
            }
            MouseArea { anchors.fill: parent; onPressed: root.userInteraction() }
        }
        Rectangle {
            id: acknowledgeButton
            x: 16; y: parent.height - 64; width: parent.width - 32; height: 48
            color: acknowledgeMouse.pressed ? "#124974" : "#207cb6"
            border.color: "white"; radius: 4
            Text {
                anchors.fill: parent; anchors.margins: 8
                text: root.acknowledgeLabel
                textFormat: Text.PlainText
                font.pixelSize: 22; color: "white"
                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            MouseArea {
                id: acknowledgeMouse
                anchors.fill: parent
                onPressed: root.userInteraction()
                onClicked: root.acknowledge()
            }
        }
    }
}
