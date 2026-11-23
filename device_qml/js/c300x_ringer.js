// Deliberately not a shared library: each QML control owns its request.
// Qt4 QVariant conversion would discard the XHR wrapper and its methods.
var pendingRequest = null

// Run only on an explicit request, against the stock video page's current call.
function pictureReply(command, source) {
    var result = "&picture_id=" + command.id
    if (!source || !source.callInProgress) return result
    var key = command.picture
    if (key !== "read") {
        var value = command.value
        if (typeof value !== "number" || value < 0 || value > 100 || value % 10 !== 0)
            return result
        if (key === "brightness") source.brightness = value
        else if (key === "contrast") source.contrast = value
        else if (key === "saturation") source.color = value
        else return result
    }
    return result + "&brightness=" + source.brightness + "&contrast=" + source.contrast +
        "&saturation=" + source.color
}

function currentRequest() {
    return pendingRequest
}

function setRequest(request) {
    pendingRequest = request
}

function abort() {
    var request = pendingRequest
    pendingRequest = null
    if (request) {
        request.onreadystatechange = function() {}
        request.abort()
    }
}
