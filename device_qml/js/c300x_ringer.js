// Deliberately not a shared library: each QML control owns its request.
// Qt4 QVariant conversion would discard the XHR wrapper and its methods.
var pendingRequest = null

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
