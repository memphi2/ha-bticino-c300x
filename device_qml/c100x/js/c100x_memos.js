.pragma library

function textEntries(data) {
    if (!data || data.ok !== true || typeof data.available !== "boolean" || !(data.memos instanceof Array)
            || data.memos.length > 128) throw new Error("invalid memo snapshot")
    var result = [], seen = {}
    for (var i = 0; i < data.memos.length; i++) {
        var entry = data.memos[i]
        if (!entry || ["text", "voice"].indexOf(entry.kind) < 0) throw new Error("invalid memo kind")
        if (entry.kind === "voice") continue
        if (typeof entry.id !== "string" || !/^text\/memo_[0-9]+$/.test(entry.id) || seen[entry.id]
                || entry.has_text !== true || typeof entry.text !== "string" || entry.text.length > 512
                || (entry.date !== null && (typeof entry.date !== "string" || entry.date.length > 128))
                || [true, false, null].indexOf(entry.read) < 0 || typeof entry.text_truncated !== "boolean")
            throw new Error("invalid text memo")
        seen[entry.id] = true
        result.push({id: entry.id, text: entry.text, date: entry.date || "", unread: entry.read === false,
                     truncated: entry.text_truncated})
    }
    if (result.length > 64) throw new Error("too many text memos")
    return result
}

function create(page, requestFactory) {
    var pending = null
    var stopped = false
    function stop() {
        page.deadline.stop()
        var request = pending
        pending = null
        if (request) { request.onreadystatechange = function() {}; request.abort() }
        page.busy = false
    }
    function fail() {
        stop()
        page.failed = true
    }
    function load() {
        stop()
        if (stopped || !page.visible || page.blocked) return
        page.resetInput()
        page.selectedMemo = null
        page.entries = []
        page.failed = false
        page.busy = true
        var request = requestFactory ? requestFactory() : new XMLHttpRequest()
        pending = request
        request.onreadystatechange = function() {
            if (pending !== request || stopped || !page.visible || page.blocked || request.readyState !== 4) return
            page.deadline.stop()
            pending = null
            page.busy = false
            try {
                if (request.status !== 200 || request.responseText.length > 262144) throw new Error("invalid response")
                var data = JSON.parse(request.responseText)
                var entries = textEntries(data)
                page.available = data.available
                page.entries = data.available ? entries : []
            } catch (error) { page.failed = true }
        }
        try {
            request.open("GET", "http://127.0.0.1:8090/ui/memos", true)
            page.deadline.restart()
            request.send()
        } catch (error) { fail() }
    }
    return {load: load, stop: stop, timeout: fail, destroy: function() { stopped = true; stop() }}
}
