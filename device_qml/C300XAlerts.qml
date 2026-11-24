import QtQuick 1.1
import BtObjects 2.0
import BtClass 1.0
import "js/c300x_alerts.js" as Alerts
import "js/c300x_i18n.js" as I18n
import "js/c300x_ha.js" as Api

Item {
    id: root
    property bool blocked: true
    property bool stopped: false
    property variant notice: null
    property int pollGeneration: 0
    property int resumeAttempts: 5
    property int runtimeGeneration: 0
    property bool acknowledging: false
    property bool ackFailed: false
    property string uiLanguage: trsl.language
    property string acknowledgeLabel: uiText("dismiss_notification")
    property color accent: !notice || notice.severity === "info" ? "#68baff" : notice.severity === "warning" ? "#f1c40f" : "#ff6b6b"
    onBlockedChanged: updateGuard()
    onVisibleChanged: updateGuard()

    function uiText(key) {
        return I18n.text(uiLanguage, key)
    }

    function severityText() {
        return notice ? (notice.severity === "info" ? "i  " : "!  ") + uiText("alert_" + notice.severity) : ""
    }

    function canListen() {
        return !stopped && !blocked && visible && !!Alerts.runtimeFor(root)
    }

    function canConnect() {
        return !stopped && !!Alerts.runtimeFor(root)
    }

    function updateGuard() {
        preempt()
    }

    function abortPoll() {
        pollGeneration += 1
        var runtime = Alerts.runtimeFor(root)
        if (!runtime) return
        var request = runtime.pendingRequest
        runtime.pendingRequest = null
        if (request) { request.onreadystatechange = function() {}; request.abort() }
    }

    function preempt() {
        abortPoll()
        reconnect.stop()
        resume.stop()
        var runtime = Alerts.runtimeFor(root)
        if (runtime) runtime.controller.preempt()
        // Call hooks can run before their guard bindings change, or without a
        // guard transition. Yield once for both bindings and socket teardown.
        resumeAttempts = 5
        if (canConnect()) resume.restart()
    }

    function userInteraction() {
        var runtime = Alerts.runtimeFor(root)
        if (runtime) runtime.controller.userInteraction()
    }

    function acknowledge() {
        var runtime = Alerts.runtimeFor(root)
        if (runtime) runtime.controller.acknowledge()
    }

    function screenChanged() {
        var runtime = Alerts.runtimeFor(root)
        if (runtime) runtime.controller.screenChanged()
    }

    function tick() {
        var runtime = Alerts.runtimeFor(root)
        if (runtime) runtime.controller.tick()
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
        var runtime = Alerts.runtimeFor(root)
        if (!canConnect() || runtime.pendingRequest) return
        reconnect.stop()
        resume.stop()
        var generation = pollGeneration
        // A protected connection only advertises presence, never commands.
        var protectedRequest = !canListen()
        var request = new XMLHttpRequest()
        runtime.pendingRequest = request
        request.onreadystatechange = function() {
            if (!canConnect() || Alerts.runtimeFor(root) !== runtime || generation !== pollGeneration || runtime.pendingRequest !== request || request.readyState !== XMLHttpRequest.DONE) return
            runtime.pendingRequest = null
            var valid = false
            if (!protectedRequest && canListen() && request.status === 200 && request.responseText.length <= 16384) {
                try {
                    var command = JSON.parse(request.responseText)
                    valid = !!Alerts.validate(command, new Date().getTime())
                    if (valid) runtime.controller.receive(command)
                } catch (error) { valid = false }
            }
            if (!canConnect() || generation !== pollGeneration) return
            if (valid) { resumeAttempts = 5; waitForCommand() }
            else if (request.status === 409 && resumeAttempts > 0) {
                resumeAttempts -= 1
                resume.restart()
            } else reconnect.restart()
        }
        try {
            request.open("GET", Api.baseUrl() + "/ui/alerts/next" + (protectedRequest ? "?protected=1" : ""), true)
            request.setRequestHeader("X-C300X-GUI", "alerts-v1")
            request.send()
        } catch (error) {
            runtime.pendingRequest = null
            request.onreadystatechange = function() {}
            request.abort()
            if (canConnect() && generation === pollGeneration) reconnect.restart()
        }
    }

    function sendAcknowledgement(command) {
        var runtime = Alerts.runtimeFor(root)
        if (stopped || !runtime) return
        abortAcknowledgement()
        var token = {}
        runtime.ackToken = token
        acknowledging = true
        var option = JSON.stringify({revision: command.revision, action_id: null})
        var path = "/homeassistant?domain=c300x&service=toggle&entities=" +
            encodeURIComponent("notification." + command.notification_id) + "&option=" + encodeURIComponent(option)
        function complete(success) {
            if (!stopped && Alerts.runtimeFor(root) === runtime && runtime.ackToken === token) finishAcknowledgement(success)
        }
        ackTimeout.restart()
        try {
            Api.getJson(path, function(data) { complete(!!data && data.ok === true) },
                function() { complete(false) }, Api.commandScope(root, ""))
        } catch (error) { complete(false) }
    }

    function finishAcknowledgement(success) {
        var runtime = Alerts.runtimeFor(root)
        if (!runtime || !runtime.ackToken) return
        abortAcknowledgement()
        ackFailed = !success
        runtime.controller.acknowledged(success)
    }

    function abortAcknowledgement() {
        ackTimeout.stop()
        Api.cancelPageCommands(root)
        runtimeGeneration += 1
        var runtime = Alerts.runtimeFor(root)
        if (runtime) runtime.ackToken = null
        acknowledging = false
        ackFailed = false
    }

    function initialize() {
        if (stopped || Alerts.runtimeFor(root)) return
        Alerts.attach(root, {
            now: function() { return new Date().getTime() },
            blocked: function() { return root.blocked || root.stopped || !root.visible },
            screen: function() { return global.screenState.state },
            normal: ScreenState.Normal, off: ScreenState.ScreenOff,
            idleInterval: function() { return global.screenState.screensaverInterval },
            simulateClick: function() { global.screenState.simulateClick() },
            releaseNormal: function() { global.screenState.disableState(ScreenState.Normal) },
            soundReady: function() { return root.soundReady() },
            beep: function(guard) { return root.shortBeep(guard) },
            show: function(command) { root.abortAcknowledgement(); root.notice = command; messageScroll.contentY = 0; effects.restart() },
            hide: function() { root.abortAcknowledgement(); effects.stop(); root.notice = null },
            ack: function(command) { root.sendAcknowledgement(command) }
        })
        waitForCommand()
    }

    function shutdown() {
        stopped = true
        var runtime = Alerts.runtimeFor(root)
        if (runtime) runtime.controller.destroy()
        effects.stop()
        reconnect.stop()
        resume.stop()
        abortAcknowledgement()
        abortPoll()
        Alerts.detach(root)
    }

    Connections {
        target: global.screenState
        onStateChangedInt: root.screenChanged()
    }
    Timer { id: effects; interval: 250; repeat: true; onTriggered: root.tick() }
    Timer { id: reconnect; interval: 30000; repeat: false; onTriggered: root.waitForCommand() }
    Timer { id: resume; interval: 100; repeat: false; onTriggered: root.waitForCommand() }
    Timer { id: ackTimeout; interval: 10000; repeat: false; onTriggered: root.finishAcknowledgement(false) }
    Component.onCompleted: initialize()
    Component.onDestruction: shutdown()

    MouseArea {
        anchors.fill: parent
        enabled: !!root.notice && !root.blocked
        onPressed: {
            root.userInteraction()
            mouse.accepted = false
        }
    }

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
            text: root.severityText()
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
                text: root.acknowledging ? root.uiText("sending") : root.ackFailed ? root.uiText("alert_ack_retry") : root.acknowledgeLabel
                textFormat: Text.PlainText
                font.pixelSize: root.ackFailed ? 18 : 22; color: root.ackFailed ? "#ffd166" : "white"
                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            MouseArea {
                id: acknowledgeMouse
                anchors.fill: parent
                enabled: !root.acknowledging
                onPressed: root.userInteraction()
                onClicked: root.acknowledge()
            }
        }
    }
}
