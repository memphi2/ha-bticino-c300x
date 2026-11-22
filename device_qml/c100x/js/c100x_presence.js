.pragma library

// The socket advertises presence; only a fresh challenge proves event-loop progress.
function create(owner) {
    var pending = null
    var probe = ""
    function stop() {
        owner.presenceRetry.stop()
        var request = pending
        pending = null
        probe = ""
        if (request) { request.onreadystatechange = function() {}; request.abort() }
    }
    function eligible() {
        return owner.running && !owner.stopped && owner.vendorReady && owner.displayReady
            && /^[0-9a-f]{64}$/.test(owner.generation)
    }
    function start() {
        if (pending || !eligible()) return
        var request = new XMLHttpRequest()
        pending = request
        request.onreadystatechange = function() {
            if (request.readyState !== 4 || pending !== request) return
            pending = null
            if (eligible()) {
                probe = ""
                if (request.status === 200 && typeof request.responseText === "string" && request.responseText.length < 256) {
                    try {
                        var reply = JSON.parse(request.responseText)
                        if (reply.ok === true && /^[0-9a-f]{32}$/.test(reply.probe)) probe = reply.probe
                    } catch (error) {}
                }
                owner.presenceRetry.interval = request.status === 200 ? 100 : 30000
                owner.presenceRetry.restart()
            }
        }
        try {
            request.open("GET", "http://127.0.0.1:8090/ui/c100x/presence/next?generation="
                         + owner.generation + "&blocked=" + (owner.blocked ? "1" : "0")
                         + (probe ? "&probe=" + probe : ""), true)
            probe = ""
            request.setRequestHeader("X-C100X-GUI", "presence-v1")
            request.send()
        } catch (error) {
            stop()
            if (eligible()) { owner.presenceRetry.interval = 30000; owner.presenceRetry.restart() }
        }
    }
    function sync() { stop(); start() }
    return {start: start, stop: stop, sync: sync}
}
