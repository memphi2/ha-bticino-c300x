.pragma library

var BASE_URL = "http://127.0.0.1:8090"
var connections = []
var eventRevision = 0
var eventRequest = null
var eventWatching = false
var eventCallback = null
var eventOwner = null
var eventRetryTimer = null
var eventRetryDelay = 1000
var eventRecovering = false
var eventConnected = false
var eventRefreshInFlight = false
var eventGeneration = 0
var notificationGeneration = 0

function syncMemoModel(pageItem, textMemoType, callback) {
    syncMemoObjectModel(pageItem.model, textMemoType, callback)
}

function syncMemoObjectModel(model, textMemoType, callback) {
    getJson("/ui/memos", function(data) {
        syncObjectModel(model, data, textMemoType)
        if (callback) {
            callback(true, data)
        }
    }, function() {
        if (callback) {
            callback(false, null)
        }
    })
}

function syncHomeNotifications(pageItem, callback) {
    prepareEventRetry(pageItem)
    var generation = ++notificationGeneration
    var watchGeneration = eventGeneration
    var pending = 2
    var success = true

    function done(ok) {
        success = success && ok
        pending--
        if (pending === 0 && callback) {
            callback(success && generation === notificationGeneration && watchGeneration === eventGeneration)
        }
    }

    function current() {
        return pageItem && generation === notificationGeneration && watchGeneration === eventGeneration
    }

    getJson("/ui/answering-machine/messages", function(data) {
        if (current()) pageItem.externalUnreadMessages = unreadCountFromData(data)
        done(true)
    }, function() {
        if (current()) pageItem.externalUnreadMessages = -1
        done(false)
    })
    getJson("/ui/memos", function(data) {
        if (current()) pageItem.externalUnreadMemos = unreadCountFromData(data)
        done(true)
    }, function() {
        if (current()) pageItem.externalUnreadMemos = -1
        done(false)
    })
}

function startEventWatch(callback) {
    eventCallback = callback
    if (eventWatching === true) {
        return
    }
    if (eventRetryTimer) eventRetryTimer.stop()
    eventRetryDelay = 1000
    eventWatching = true
    requestNextEvent()
}

function stopEventWatch() {
    eventWatching = false
    eventCallback = null
    eventGeneration += 1
    eventRecovering = false
    eventConnected = false
    eventRefreshInFlight = false
    if (eventRetryTimer) eventRetryTimer.stop()
    var request = eventRequest
    eventRequest = null
    if (request) {
        request.onreadystatechange = function() {}
        removeConnection(request)
        if (request.readyState < 4) request.abort()
    }
}

function prepareEventRetry(pageItem) {
    if (!pageItem) return
    var timer = pageItem.memoEventRetryTimer || null
    if (eventOwner === pageItem && eventRetryTimer === timer) return
    if (eventOwner) stopEventWatch()
    eventOwner = pageItem
    // Qt 4 crashes when a shared script dynamically creates a QML object.
    // The page owns the declarative timer and its triggered handler instead.
    eventRetryTimer = timer
}

function scheduleEventRetry() {
    if (!eventWatching || !eventRetryTimer || eventRetryTimer.running) return
    eventRetryTimer.interval = eventRetryDelay
    eventRetryDelay = Math.min(eventRetryDelay * 2, 30000)
    eventRetryTimer.restart()
}

function retryEventWatch() {
    if (!eventWatching) return
    if (!eventRequest) requestNextEvent()
    else if (eventConnected && eventRecovering) refreshAfterReconnect()
}

function eventWatchFailed() {
    eventConnected = false
    if (eventOwner && eventOwner.externalUnreadMemos !== undefined) {
        eventOwner.externalUnreadMessages = -1
        eventOwner.externalUnreadMemos = -1
    }
    eventRecovering = true
    scheduleEventRetry()
}

function refreshAfterReconnect() {
    if (!eventOwner || eventRefreshInFlight || !eventWatching) return
    eventRefreshInFlight = true
    var generation = eventGeneration
    // Events missed during an outage need a full unread-count snapshot, even
    // when the first successful long poll reports changed=false.
    syncHomeNotifications(eventOwner, function(ok) {
        if (generation !== eventGeneration || !eventWatching) return
        eventRefreshInFlight = false
        if (!ok || !eventConnected) {
            scheduleEventRetry()
            return
        }
        eventRecovering = false
        eventRetryDelay = 1000
        if (eventRetryTimer) eventRetryTimer.stop()
        if (eventCallback) eventCallback({topic: "notifications"})
    })
}

function unreadCountFromData(data) {
    if (!data || data.ok === false || data.available === false || typeof data.unread !== "number") {
        return -1
    }
    return data.unread
}

function syncObjectModel(model, data, textMemoType) {
    if (!model || !model.binder || !data || data.ok !== true || data.available !== true) {
        return
    }
    var deleted = idSet(data.deleted)
    var known = memoSet(data.memos)
    for (var index = model.count - 1; index >= 0; index--) {
        var itemObject = model.binder.getObject(index)
        var key = memoObjectKey(itemObject, textMemoType)
        if (key !== "" && deleted[key] === true && known[key] !== true) {
            model.remove(itemObject)
        }
    }
}

function idSet(items) {
    var ids = {}
    if (!items || items.length === undefined) {
        return ids
    }
    for (var index = 0; index < items.length; index++) {
        if (typeof items[index] === "string") {
            ids[items[index]] = true
        }
    }
    return ids
}

function memoSet(items) {
    var known = {}
    if (!items || items.length === undefined) {
        return known
    }
    for (var index = 0; index < items.length; index++) {
        if (items[index] && items[index].id) {
            known[String(items[index].id)] = true
        }
    }
    return known
}

function memoObjectKey(itemObject, textMemoType) {
    if (!itemObject || itemObject.messageId === undefined) {
        return ""
    }
    var kind = itemObject.type === textMemoType ? "text" : "voice"
    return kind + "/memo_" + itemObject.messageId
}

function getJson(path, callback, errorCallback) {
    cleanupConnections()
    var xhr = new XMLHttpRequest()
    connections.push(xhr)
    xhr.startTime = Date.now()
    xhr.onreadystatechange = function() {
        if (xhr.readyState === 4) {
            removeConnection(xhr)
            if (xhr.status === 200) {
                try {
                    callback(JSON.parse(xhr.responseText))
                } catch (error) {
                    errorCallback("Invalid JSON")
                }
            } else {
                errorCallback("API error: " + xhr.status)
            }
        }
    }
    xhr.open("GET", BASE_URL + path)
    xhr.send()
}

function requestNextEvent() {
    cleanupConnections()
    if (eventWatching !== true || eventRequest !== null) {
        return
    }

    var xhr = new XMLHttpRequest()
    eventRequest = xhr
    xhr.startTime = Date.now()
    xhr.longPoll = true
    connections.push(xhr)
    xhr.onreadystatechange = function() {
        if (xhr.readyState !== 4) {
            return
        }
        removeConnection(xhr)
        if (eventRequest !== xhr || !eventWatching) return
        eventRequest = null
        if (xhr.status === 200 && eventWatching === true) {
            try {
                var data = JSON.parse(xhr.responseText)
                if (data && data.revision !== undefined) {
                    // The agent retains only the last topic, not a revision history.
                    data.missedRevisions = data.changed === true && Number(data.revision) !== eventRevision + 1
                    eventRevision = Number(data.revision)
                }
                eventConnected = true
                if (eventRecovering && (!eventRetryTimer || !eventRetryTimer.running)) refreshAfterReconnect()
                if (data && data.changed === true && eventCallback) {
                    eventCallback(data)
                }
                requestNextEvent()
            } catch (error) {
                eventWatchFailed()
            }
        } else if (eventWatching === true) {
            eventWatchFailed()
        }
    }
    xhr.open("GET", BASE_URL + "/ui/events/next?since=" + eventRevision)
    xhr.send()
}

function removeConnection(xhr) {
    var index = connections.length
    while (index--) {
        if (connections[index] === xhr) {
            connections.splice(index, 1)
            return
        }
    }
}

function cleanupConnections() {
    var pending = connections.slice(0)
    var index = pending.length
    while (index--) {
        var request = pending[index]
        if (request.longPoll === true && request === eventRequest && eventWatching === true) {
            continue
        }
        if (Date.now() - request.startTime > 3000) {
            if (request.readyState < 4) request.abort()
            removeConnection(request)
        }
    }
}
