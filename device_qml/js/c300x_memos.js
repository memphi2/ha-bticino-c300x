.pragma library

var BASE_URL = "http://127.0.0.1:8090"
var connections = []
var eventRevision = 0
var eventRequest = null
var eventWatching = false
var eventCallback = null

function syncMemoModel(pageItem, textMemoType, callback) {
    syncMemoObjectModel(pageItem.model, textMemoType, callback)
}

function syncMemoObjectModel(model, textMemoType, callback) {
    getJson("/ui/memos", function(data) {
        syncObjectModel(model, data && data.memos, textMemoType)
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
    var pending = 2
    var success = true

    function done(ok) {
        success = success && ok
        pending--
        if (pending === 0 && callback) {
            callback(success)
        }
    }

    getJson("/ui/answering-machine/messages", function(data) {
        if (pageItem) {
            pageItem.externalUnreadMessages = unreadCountFromData(data)
        }
        done(true)
    }, function() {
        done(false)
    })
    getJson("/ui/memos", function(data) {
        if (pageItem) {
            pageItem.externalUnreadMemos = unreadCountFromData(data)
        }
        done(true)
    }, function() {
        done(false)
    })
}

function unreadCountFromPath(path, callback) {
    getJson(path, function(data) {
        if (callback) {
            callback(true, unreadCountFromData(data))
        }
    }, function() {
        if (callback) {
            callback(false, 0)
        }
    })
}

function startEventWatch(callback) {
    eventCallback = callback
    if (eventWatching === true) {
        return
    }
    eventWatching = true
    requestNextEvent()
}

function stopEventWatch() {
    eventWatching = false
    eventCallback = null
    if (eventRequest && eventRequest.readyState < 4) {
        eventRequest.abort()
    }
    if (eventRequest) {
        removeConnection(eventRequest)
    }
    eventRequest = null
}

function unreadCountFromData(data) {
    if (data && data.unread !== undefined) {
        return Number(data.unread)
    }
    return 0
}

function syncObjectModel(model, memos, textMemoType) {
    var known = memoSet(memos)
    if (!model || !model.binder) {
        return
    }
    for (var index = model.count - 1; index >= 0; index--) {
        var itemObject = model.binder.getObject(index)
        var key = memoObjectKey(itemObject, textMemoType)
        if (key !== "" && known[key] !== true) {
            model.remove(itemObject)
        }
    }
}

function unreadCount(model, textMemoType) {
    var count = 0
    if (!model || !model.binder) {
        return 0
    }
    for (var index = 0; index < model.count; index++) {
        var itemObject = model.binder.getObject(index)
        if (
            itemObject
            && itemObject.type === textMemoType
            && itemObject.isRead === false
        ) {
            count++
        }
    }
    return count
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
        eventRequest = null
        if (xhr.status === 200 && eventWatching === true) {
            try {
                var data = JSON.parse(xhr.responseText)
                if (data && data.revision !== undefined) {
                    eventRevision = Number(data.revision)
                }
                if (data && data.changed === true && eventCallback) {
                    eventCallback(data)
                }
                requestNextEvent()
            } catch (error) {
                eventWatching = false
            }
        } else if (eventWatching === true) {
            eventWatching = false
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
    var index = connections.length
    while (index--) {
        if (connections[index].longPoll === true) {
            continue
        }
        if (Date.now() - connections[index].startTime > 3000) {
            if (connections[index].readyState < 4) {
                connections[index].abort()
            }
            connections.splice(index, 1)
        }
    }
}
