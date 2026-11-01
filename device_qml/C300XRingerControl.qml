import QtQuick 1.1
import BtClass 1.0

Item {
    id: control
    property variant pendingRequest: null
    property bool stopped: false

    function waitForCommand(completed, muted) {
        if (stopped || pendingRequest)
            return
        var request = new XMLHttpRequest()
        pendingRequest = request
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE || stopped)
                return
            pendingRequest = null
            if (request.status === 200) {
                try {
                    var command = JSON.parse(request.responseText)
                    if (command.ok === true && typeof command.id === "string" &&
                            /^[0-9a-f]{32}$/.test(command.id) &&
                            typeof command.muted === "boolean" &&
                            typeof command.expires === "number" &&
                            new Date().getTime() < command.expires) {
                        if (command.muted)
                            global.audioState.enableState(AudioState.RingtoneMute)
                        else
                            global.audioState.disableState(AudioState.RingtoneMute)
                        waitForCommand(command.id,
                            global.audioState.isStateEnabled(AudioState.RingtoneMute))
                        return
                    }
                } catch (error) {}
            }
            reconnect.start()
        }
        var url = "http://127.0.0.1:8090/ui/ringer/next"
        if (completed)
            url += "?completed=" + completed + "&muted=" + (muted ? "1" : "0")
        request.open("GET", url, true)
        request.setRequestHeader("X-C300X-GUI", "ringer-v1")
        request.send()
    }

    Timer {
        id: reconnect
        interval: 30000
        repeat: false
        onTriggered: control.waitForCommand()
    }

    Component.onCompleted: waitForCommand()
    Component.onDestruction: {
        stopped = true
        reconnect.stop()
        if (pendingRequest)
            pendingRequest.abort()
    }
}
