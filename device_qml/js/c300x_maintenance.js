// Per page instance. Late responses must not update a reopened settings tab.
var active = null

function cancel(panel, timer) {
    var previous = active
    active = null
    timer.stop()
    panel.busy = false
    if (previous) previous.abort()
}

function request(panel, timer, path, payload) {
    if (active) return
    var xhr = new XMLHttpRequest()
    active = xhr
    panel.busy = true
    if (path === "/ssh") panel.sshKnown = false
    panel.status = ""
    function finish(data) {
        if (active !== xhr) return
        active = null
        timer.stop()
        panel.busy = false
        if (!data || data.ok !== true) {
            panel.status = "display_settings_error"
        } else if (path === "") {
            panel.canReboot = data.reboot === true
            panel.canRemove = data.remove === true
            if (data.ssh === true) request(panel, timer, "/ssh", null)
        } else if (path === "/ssh") {
            panel.sshKnown = typeof data.running === "boolean"
            panel.sshRunning = data.running === true
        } else {
            panel.canReboot = panel.canRemove = panel.sshKnown = false
            panel.status = "maintenance_accepted"
        }
    }
    try {
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== 4 || active !== xhr) return
            var data = null
            if (xhr.status >= 200 && xhr.status < 300) {
                try { data = JSON.parse(xhr.responseText) } catch (ignore) {}
            }
            finish(data)
        }
        xhr.open(payload ? "POST" : "GET", "http://127.0.0.1:8090/ui/maintenance" + path, true)
        xhr.setRequestHeader("x-c300x-ui", "settings-v1")
        if (payload) xhr.setRequestHeader("Content-Type", "application/json")
        timer.restart()
        xhr.send(payload ? JSON.stringify(payload) : "")
    } catch (error) { finish(null) }
}
