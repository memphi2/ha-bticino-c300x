.pragma library

// Qt 4 QVariant properties copy JS objects and cannot retain XHR identity or
// controller closures. Only the QObject owner crosses the QML boundary.
var runtimes = []

function runtimeFor(owner) {
    for (var i = 0; i < runtimes.length; i++) {
        if (runtimes[i].owner === owner) return runtimes[i]
    }
    return null
}

function attach(owner, io) {
    var runtime = {owner: owner, controller: createController(io), pendingRequest: null, ackRequest: null}
    runtimes.push(runtime)
    return runtime
}

function detach(owner) {
    for (var i = runtimes.length - 1; i >= 0; i--) {
        if (runtimes[i].owner === owner) runtimes.splice(i, 1)
    }
}

function integer(value, low, high) {
    return typeof value === "number" && isFinite(value) &&
        Math.floor(value) === value && value >= low && value <= high
}

function textLength(value) {
    if (typeof value !== "string") return -1
    var length = 0
    for (var i = 0; i < value.length; i++) {
        var code = value.charCodeAt(i)
        if (code === 0 || (code >= 0xdc00 && code <= 0xdfff)) return -1
        if (code >= 0xd800 && code <= 0xdbff) {
            var next = value.charCodeAt(++i)
            if (!(next >= 0xdc00 && next <= 0xdfff)) return -1
        }
        length += 1
    }
    return length
}

function validate(command, now) {
    if (!integer(now, 0, 9007199254740991) || !command || typeof command !== "object" || command instanceof Array) return null
    var fields = ["id", "notification_id", "revision", "severity", "title", "message",
        "wake_duration", "sound_duration", "expires_in", "remaining_ms", "expires", "message_expires"]
    var count = 0
    for (var key in command) {
        if (!Object.prototype.hasOwnProperty.call(command, key) || fields.indexOf(key) < 0) return null
        count += 1
    }
    if (count !== fields.length || typeof command.id !== "string" ||
            !/^[0-9a-f]{32}$/.test(command.id) || typeof command.revision !== "string" ||
            !/^[0-9a-f]{32}$/.test(command.revision) || typeof command.notification_id !== "string" ||
            !/^[a-z0-9_-]{1,64}$/.test(command.notification_id) ||
            ["info", "warning", "error"].indexOf(command.severity) < 0 ||
            textLength(command.title) < 0 || textLength(command.title) > 80 ||
            textLength(command.message) < 0 || textLength(command.message) > 500 ||
            !integer(command.wake_duration, 0, 300) || !integer(command.sound_duration, 0, 300) ||
            !integer(command.expires_in, 1, 604800) || !integer(command.remaining_ms, 1, 5000) ||
            !integer(command.expires, 1, 9007199254740991) || command.expires <= now ||
            !integer(command.message_expires, 1, 9007199254740991) || command.message_expires <= now) return null
    return command
}

function createController(io) {
    var active = null
    var generation = 0
    var stopped = false
    var seen = []
    var lastBeep = -Infinity
    var wakeRequest = null
    var ranks = {info: 0, warning: 1, error: 2}

    function current(item) {
        return !stopped && active === item && item.generation === generation && !io.blocked()
    }

    function cancelWake(item) {
        item.ownsNormal = false
        item.pendingWake = false
        item.wakeUntil = 0
    }

    function relinquish(item) {
        cancelWake(item)
        item.soundUntil = 0
    }

    function release(item) {
        var owned = item.ownsNormal
        item.ownsNormal = false
        item.pendingWake = false
        item.wakeUntil = 0
        if (owned && current(item) && io.screen() === io.normal) {
            item.releasing = true
            try { io.releaseNormal() } finally { item.releasing = false }
        }
    }

    function finish(mode) {
        var item = active
        if (!item) return null
        // Cancel scheduling before any firmware call can re-enter the controller.
        item.soundUntil = 0
        if (mode === "expiry") release(item)
        else relinquish(item)
        if (active !== item) return null
        generation += 1
        active = null
        io.hide()
        return item.command
    }

    function preempt() {
        finish("preempt")
    }

    function clock(item, minimum) {
        var now = io.now()
        if (!isFinite(now) || now < item.wall) { preempt(); return false }
        // QtQuick 1.1 has no verified monotonic-clock API. Rollback cancels;
        // timer progress also bounds the lifetime if the wall clock stalls.
        item.elapsed += Math.max(minimum || 0, now - item.wall)
        item.wall = now
        return true
    }

    function pulse(item) {
        if (!current(item) || item.elapsed >= item.soundUntil || !io.soundReady()) return
        if (!clock(item, 0)) return
        if (!item.soundStarted && item.elapsed >= item.deliveryUntil) { item.soundUntil = 0; return }
        var now = io.now()
        if (now - lastBeep < 1000) return
        lastBeep = now
        var played = false
        try {
            played = io.beep(function() {
                return current(item) && clock(item, 0) && item.elapsed < item.soundUntil &&
                    (item.soundStarted || item.elapsed < item.deliveryUntil)
            })
        } catch (error) { item.soundUntil = 0 }
        if (current(item) && played) item.soundStarted = true
    }

    function screenChanged() {
        if (stopped) return
        var item = active
        var state = io.screen()
        var requestedBy = wakeRequest
        if (state !== io.off) wakeRequest = null
        if (!item) return
        if (item.releasing) return
        if (!current(item) || !clock(item, 0)) { preempt(); return }
        if (item.pendingWake && requestedBy === item && state === io.normal && item.elapsed < item.deliveryUntil &&
                item.elapsed < item.wakeUntil) {
            item.pendingWake = false
            item.ownsNormal = true
        } else if (state !== io.normal) {
            // Only the initial ScreenOff-to-Normal wake can establish ownership.
            relinquish(item)
        }
    }

    function tick() {
        var item = active
        if (!item) return
        if (!current(item)) { preempt(); return }
        if (!clock(item, 250)) return
        if (item.elapsed >= item.visibleUntil) { finish("expiry"); return }
        if (item.pendingWake && item.elapsed >= item.deliveryUntil) cancelWake(item)
        if (item.elapsed >= item.wakeUntil) release(item)
        if (!current(item)) return
        if (item.wakeUntil > item.elapsed && !item.pendingWake && item.elapsed >= item.nextRefresh) {
            if (io.screen() !== io.normal) { relinquish(item); return }
            item.nextRefresh = item.elapsed + item.refreshEvery
            try { io.simulateClick() } catch (error) { preempt(); return }
        }
        pulse(item)
    }

    function userInteraction() {
        if (active) relinquish(active)
    }

    function receive(command) {
        var now = io.now()
        command = validate(command, now)
        if (stopped || !command) return false
        var revisionKey = command.notification_id + ":" + command.revision
        for (var i = 0; i < seen.length; i++) {
            if (seen[i].id === command.id || seen[i].revision === revisionKey) return false
        }
        seen.push({id: command.id, revision: revisionKey})
        if (seen.length > 64) seen.shift()
        if (io.blocked()) { preempt(); return false }
        if (active && ranks[command.severity] < ranks[active.command.severity]) return false
        // Replacements inherit an existing lease; never switch the display off
        // between two alerts, and never claim a pre-existing Normal state.
        var inherited = active && active.ownsNormal && io.screen() === io.normal
        if (active) finish("replace")
        if (stopped || io.blocked()) return false
        var lifetime = Math.min(command.expires_in * 1000, command.message_expires - now, 300000)
        var item = {
            command: command, generation: ++generation, wall: now, elapsed: 0,
            deliveryUntil: Math.min(command.remaining_ms, command.expires - now),
            visibleUntil: Math.min(lifetime, Math.max(30, command.wake_duration, command.sound_duration) * 1000),
            wakeUntil: Math.min(lifetime, command.wake_duration * 1000),
            soundUntil: Math.min(lifetime, command.sound_duration * 1000),
            pendingWake: false, ownsNormal: !!inherited, releasing: false, soundStarted: false, nextRefresh: 0,
            refreshEvery: Math.max(250, Math.min(5000, io.idleInterval() / 2))
        }
        active = item
        io.show(command)
        if (!current(item) || !clock(item, 0)) return false
        if (item.elapsed >= item.deliveryUntil) { preempt(); return false }
        var state = io.screen()
        if (state === io.off && wakeRequest) {
            // There is no verified API to cancel a native wake request. Do not
            // issue another or assign its eventual reply to a newer generation.
            cancelWake(item)
        } else if (item.wakeUntil > 0 && (state === io.off || state === io.normal)) {
            item.pendingWake = state === io.off
            if (item.pendingWake) wakeRequest = item
            item.nextRefresh = item.refreshEvery
            try { io.simulateClick() } catch (error) { preempt(); return false }
        } else if (!item.wakeUntil) release(item)
        if (current(item)) pulse(item)
        return true
    }

    function acknowledge() {
        var command = finish("ack")
        if (!command || stopped) return
        if (!io.blocked() && io.screen() === io.normal) {
            try { io.simulateClick() } catch (error) {}
        }
        if (!stopped) io.ack(command)
    }

    function destroy() {
        preempt()
        stopped = true
        generation += 1
    }

    return {receive: receive, tick: tick, preempt: preempt, userInteraction: userInteraction,
        screenChanged: screenChanged, acknowledge: acknowledge, destroy: destroy}
}
