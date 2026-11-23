.pragma library

// One sleeping request, cancelled on vendor preemption; no deferred commands.
function create(owner) {
    var pending = null
    var lastId = ""
    function stop() {
        var request = pending
        pending = null
        if (request) { request.onreadystatechange = function() {}; request.abort() }
    }
    function start(completed, muted) {
        if (pending || owner.stopped || !owner.running || owner.blocked) return
        var request = new XMLHttpRequest()
        pending = request
        request.onreadystatechange = function() {
            if (request.readyState !== 4 || pending !== request) return
            pending = null
            if (owner.stopped || !owner.running || owner.blocked) return
            try {
                var data = request.status === 200 && request.responseText.length <= 1024
                    ? JSON.parse(request.responseText) : null
                if (data && data.ok === true && typeof data.id === "string" && /^[0-9a-f]{32}$/.test(data.id)
                    && data.id !== lastId && typeof data.muted === "boolean" && typeof data.expires === "number"
                    && isFinite(data.expires) && Date.now() < data.expires) {
                    lastId = data.id
                    start(data.id, owner.setMuted(data.muted))
                    return
                }
            } catch (error) {}
            owner.reconnectRinger()
        }
        try {
            var url = "http://127.0.0.1:8090/ui/ringer/next"
            if (completed) url += "?completed=" + completed + "&muted=" + (muted === true ? "1" : "0")
            request.open("GET", url, true)
            request.setRequestHeader("X-C300X-GUI", "ringer-v1")
            request.send()
        } catch (error) {
            stop()
            owner.reconnectRinger()
        }
    }
    return {start: start, stop: stop}
}
