.pragma library

// A sleeping request proves this generation is alive; guard changes revoke it.
function create(owner) {
    var pending = null
    function stop() {
        owner.presenceRetry.stop()
        var request = pending
        pending = null
        if (request) { request.onreadystatechange = function() {}; request.abort() }
    }
    function eligible() {
        return owner.running && !owner.stopped && owner.vendorReady
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
                owner.presenceRetry.interval = request.status === 200 ? 100 : 30000
                owner.presenceRetry.restart()
            }
        }
        try {
            request.open("GET", "http://127.0.0.1:8090/ui/c100x/presence/next?generation="
                         + owner.generation + "&blocked=" + (owner.blocked ? "1" : "0"), true)
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
