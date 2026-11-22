import QtQuick 2.7

Item {
    id: probe
    width: 800
    height: 480
    property int submissions: 0
    property string submittedValue: ""
    HomeAssistant { id: host; visible: false }
    C300XDetailControl {
        id: detail
        width: 760
        hostPage: host
        onSubmitted: { probe.submissions++; probe.submittedValue = value }
    }
    function findSlider(item) {
        if (item.objectName === "c100xNumericSlider") return item
        var children = item.children || []
        for (var i = 0; i < children.length; i++) {
            var found = findSlider(children[i])
            if (found) return found
        }
        return null
    }
    function require(condition, message) {
        if (!condition) throw new Error(message)
    }
    function exercise() {
        detail.control = {kind: "number", command: "temperature", min: 5, max: 27, step: 3, value: 17}
        var slider = findSlider(detail)
        require(slider !== null, "missing real detail slider")
        slider.activate()
        require(detail.preview === 17 && submissions === 0, "edit must start at current value")
        slider.adjust(1)
        require(detail.preview === 20 && submissions === 0, "one key must mean one step")
        slider.cancel()
        require(detail.preview === 17 && submissions === 0 && !host.interactionActive, "cancel must restore preview")
        slider.activate()
        require(detail.preview === 17, "re-entry must use readback, not cancelled edit")
        for (var i = 0; i < 12; i++) slider.adjust(1)
        require(detail.preview === 26, "unaligned upper limit must use last complete step")
        for (i = 0; i < 12; i++) slider.adjust(-1)
        require(detail.preview === 5, "lower limit must be reachable")
        slider.adjust(1)
        slider.activate()
        require(submissions === 1 && submittedValue === "8" && !host.interactionActive, "confirm must submit once")

        detail.control = {kind: "number", command: "temperature", min: 15, max: 30, step: 0.5, value: 21.5}
        slider.activate()
        require(detail.preview === 21.5, "fractional current value lost")
        slider.adjust(-1)
        require(detail.preview === 21, "fractional step lost")
        slider.cancel()
        require(detail.preview === 21.5 && submissions === 1, "fractional cancel submitted")

        detail.control = {kind: "number", command: "temperature", min: 15, max: 30, step: 0.5, value: null}
        slider.activate()
        require(detail.preview === 15 && submissions === 1, "unknown value must start at minimum without submitting")
        slider.cancel()
    }
}
