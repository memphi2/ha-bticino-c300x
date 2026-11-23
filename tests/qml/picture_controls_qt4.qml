import QtQuick 1.1
import "../../device_qml" as Device
import "../../device_qml/js/c300x_ringer.js" as Controls

Item {
    id: call
    property bool callInProgress: true
    property int brightness: 20
    property int contrast: 30
    property int color: 40
    // Load the real bridge, without opening a GUI network connection in this probe.
    Device.C300XRingerControl { stopped: true }
    Component.onCompleted: {
        var command = { id: "abc", picture: "read" }
        if (Controls.pictureReply(command, call) !== "&picture_id=abc&brightness=20&contrast=30&saturation=40")
            throw new Error("read failed")
        var keys = ["brightness", "contrast", "saturation"]
        for (var i = 0; i < keys.length; i++) {
            command.picture = keys[i]
            command.value = 10 * i
            if (Controls.pictureReply(command, call).indexOf("&" + keys[i] + "=" + command.value) < 0)
                throw new Error("write failed: " + keys[i])
        }
        call.callInProgress = false
        command.value = 90
        if (Controls.pictureReply(command, call) !== "&picture_id=abc" || call.color !== 20)
            throw new Error("inactive call changed")
        console.log("QT4_PICTURE_CONTROLS_PASS")
    }
}
