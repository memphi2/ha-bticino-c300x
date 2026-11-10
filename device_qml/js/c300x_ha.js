.pragma library

var BASE_URL = "http://127.0.0.1:8090"
var connections = []
var dashboardRevision = ""
var eventRevision = 0
var eventRequest = null
var eventWatching = false
var eventCallback = null

function status(statusItem, pageItem, alarmStateItem, activeSinceItem) {
    var generation = pageItem.runtimeGeneration
    var request = (pageItem.statusGeneration || 0) + 1
    pageItem.statusGeneration = request
    getJsonShared("/ui/state", function(data) {
        if (generation !== pageItem.runtimeGeneration || request !== pageItem.statusGeneration) return
        if (!pageItem.commandInFlight) pageItem.commandPending = false
        pageItem.alarmOnline = !!(data.alarm && data.alarm.state
            && data.alarm.state !== "unavailable" && data.alarm.state !== "unknown")
        if (pageItem.clearCommandFeedback) {
            pageItem.clearCommandFeedback()
        }
        if (pageItem.preventReturnToHomepage !== undefined) {
            pageItem.preventReturnToHomepage = data.preventReturnToHomepage === true
        }
        statusItem.text = uiText(pageItem, pageItem.commandPending ? "sending" : "ha_connected")
        statusItem.color = pageItem.commandPending ? "#f1c40f" : "#58d68d"
        if (data.alarm && data.alarm.state) {
            var previousState = pageItem.alarmRawState
            var previousCommand = pageItem.selectedCommand
            pageItem.alarmConfigured = true
            pageItem.alarmRawState = data.alarm.state
            if (previousState !== data.alarm.state) {
                pageItem.bypassOffered = false
            }
            pageItem.alarmCommandDetails = alarmCommandDetails(data.alarm)
            pageItem.alarmCommands = alarmCommands(data.alarm)
            pageItem.alarmOpenSensors = listOrEmpty(data.alarm.open_sensors)
            pageItem.alarmOpenSensorCount = positiveNumber(data.alarm.open_sensor_count, pageItem.alarmOpenSensors.length)
            if (pageItem.setAlarmDelayRemaining) {
                pageItem.setAlarmDelayRemaining(positiveNumber(data.alarm.delay_remaining, 0))
            }
            if (pageItem.alarmCommands.length > 0 && !contains(pageItem.alarmCommands, pageItem.selectedCommand)) {
                pageItem.selectedCommand = pageItem.alarmCommands[0]
            }
            var currentCommand = commandForState(data.alarm.state)
            if (previousState !== data.alarm.state && currentCommand && contains(pageItem.alarmCommands, currentCommand)) {
                pageItem.selectedCommand = currentCommand
            }
            if (pageItem.statusApplied) pageItem.statusApplied(previousState, previousCommand)
            alarmStateItem.text = alarmLabel(data.alarm.state, pageItem)
            if (activeSinceItem) {
                activeSinceItem.text = formatActiveSince(data.alarm.active_since, pageItem) || data.alarm.active_since_label || ""
            }
            if (pageItem.refreshCommandReadiness) {
                pageItem.refreshCommandReadiness()
            }
        } else {
            pageItem.alarmConfigured = false
            pageItem.alarmRawState = "unknown"
            pageItem.alarmCommandDetails = []
            pageItem.alarmCommands = []
            pageItem.alarmOpenSensors = []
            pageItem.alarmOpenSensorCount = 0
            pageItem.bypassOffered = false
            if (pageItem.setAlarmDelayRemaining) {
                pageItem.setAlarmDelayRemaining(0)
            }
            alarmStateItem.text = uiText(pageItem, "not_configured")
            if (activeSinceItem) {
                activeSinceItem.text = ""
            }
        }
        pageItem.alarmPageItem = alarmPageItem(data.alarm_page_entity)
    }, function(error) {
        if (generation !== pageItem.runtimeGeneration || request !== pageItem.statusGeneration) return
        if (!pageItem.commandInFlight) pageItem.commandPending = false
        pageItem.alarmOnline = false
        pageItem.watchFailed = true
        pageItem.pinCode = ""
        alarmStateItem.text = uiText(pageItem, "offline")
        if (activeSinceItem) activeSinceItem.text = ""
        // Every other status goes through uiText. This one used to print the
        // raw transport string, so the device showed English technical text
        // such as "API error: 503" in a translated interface. The code stays
        // visible because it names the cause exactly, but the sentence around
        // it is the user's language.
        statusItem.text = statusErrorText(pageItem, error)
        statusItem.color = "#ff6b6b"
        if (pageItem.setAlarmDelayRemaining) {
            pageItem.setAlarmDelayRemaining(0)
        }
    })
}

function statusErrorText(pageItem, error) {
    var text = uiText(pageItem, "status_error")
    var code = String(error).replace(/[^0-9]/g, "")
    return code.length > 0 ? text + " (" + code + ")" : text
}

function dashboard(statusItem, pageItem) {
    var generation = pageItem.runtimeGeneration
    if (pageItem.dashboardLoading || pageItem.interactionActive || pageItem.listScrolling) {
        pageItem.dashboardRefreshAgain = true
        return
    }
    pageItem.dashboardLoading = true
    var path = "/homeassistant"
    if (dashboardRevision.length > 0 && pageItem.dashboardPages && pageItem.dashboardPages.length > 0) {
        path += "?revision=" + encodeURIComponent(dashboardRevision)
    }
    getJson(path, function(data) {
        if (generation !== pageItem.runtimeGeneration) return
        pageItem.dashboardLoading = false
        if (pageItem.interactionActive) {
            pageItem.dashboardRefreshAgain = true
            return
        }
        pageItem.dashboardOnline = true
        if (data && data.not_modified === true) {
            statusItem.text = uiText(pageItem, "board_loaded")
            statusItem.color = "#58d68d"
            finishDashboardRefresh(statusItem, pageItem)
            return
        }
        if (data && data.revision !== undefined) {
            dashboardRevision = String(data.revision)
        }
        var pages = dashboardPages(data)
        assignDashboardValue(pageItem, "notifications", listOrEmpty(data.notifications))
        if (pageItem.notifications.length === 0) pageItem.notificationsOpen = false
        pageItem.preventReturnToHomepage = data.preventReturnToHomepage === true
        assignDashboardValue(pageItem, "dashboardPages", pages)
        pageItem.pageCount = pages.length
        if (pageItem.currentPageIndex >= pages.length) {
            pageItem.currentPageIndex = 0
        }
        loadDashboardPage(statusItem, pageItem)
        statusItem.text = pages.length > 0 ? uiText(pageItem, "board_loaded") : uiText(pageItem, "no_dashboard_pages")
        statusItem.color = pages.length > 0 ? "#58d68d" : "#f1c40f"
        if (pageItem.refreshSelectedItem) pageItem.refreshSelectedItem()
        finishDashboardRefresh(statusItem, pageItem)
    }, function(error) {
        if (generation !== pageItem.runtimeGeneration) return
        pageItem.dashboardLoading = false
        pageItem.dashboardRefreshAgain = false
        pageItem.dashboardOnline = false
        pageItem.watchFailed = true
        dashboardRevision = ""
        if (!pageItem.controlInFlight) pageItem.pendingEntity = ""
        statusItem.text = uiText(pageItem, "stale_state")
        statusItem.color = "#f1c40f"
    })
}

function finishDashboardRefresh(statusItem, pageItem) {
    if (pageItem.dashboardRefreshAgain) {
        pageItem.dashboardRefreshAgain = false
        dashboard(statusItem, pageItem)
    } else if (!pageItem.controlInFlight) {
        pageItem.pendingEntity = ""
        confirmDashboardFeedback(pageItem)
    }
}

// Nothing ever removes a feedback entry: setDashboardFeedback only replaces the
// one for the same entity and aboutToHide keeps the list so a warning survives
// until the user comes back. So a command that HA accepts but never reflects
// would keep its tile on "action sent" for the rest of the session. Entries are
// stamped and aged where they are read, which needs no periodic sweep and
// cannot drop information a late confirmation still wants.
var FEEDBACK_UNCONFIRMED_MS = 15000
var FEEDBACK_DISCARD_MS = 60000

function setDashboardFeedback(pageItem, entityId, state, expected) {
    var feedback = listOrEmpty(pageItem.controlFeedback).slice(0)
    for (var i = feedback.length - 1; i >= 0; i--) {
        if (feedback[i].entity_id === entityId) feedback.splice(i, 1)
    }
    feedback.push({entity_id: entityId, state: state, expected: expected || null, at: Date.now()})
    pageItem.controlFeedback = feedback.slice(-32)
}

function feedbackState(entry) {
    if (!entry) return ""
    var age = Date.now() - (entry.at || 0)
    if (age >= FEEDBACK_DISCARD_MS) return ""
    if (entry.state === "action_sent" && age >= FEEDBACK_UNCONFIRMED_MS) return "state_unconfirmed"
    return entry.state
}

function dashboardExpectation(item, control, value) {
    if (control.command === "toggle" || (!control.command && item.kind === "switch")) {
        return {command: "toggle", value: !item.state}
    }
    if (control.kind === "number" || control.kind === "choice" || control.kind === "boolean") {
        var expected = {command: control.command, value: value, kind: control.kind}
        if (item.entity_id.indexOf("light.") === 0 || (item.entity_id.indexOf("fan.") === 0 && control.command === "percentage")) {
            expected.power = (control.command !== "brightness" && control.command !== "percentage") || Number(value) !== 0
        }
        return expected
    }
    if (control.command === "open_cover" || control.command === "close_cover" || control.command === "stop_cover") {
        return {command: control.command}
    }
    return null
}

function dashboardExpectationMatches(item, expected) {
    if (!item || item.available === false || !expected) return false
    if (expected.command === "toggle") return item.state === expected.value
    if (expected.power !== undefined && item.state !== expected.power) return false
    var activity = item.details ? item.details.activity : ""
    if (expected.command === "open_cover") return activity === "opening" || (item.details && item.details.position === 100)
    if (expected.command === "close_cover") return activity === "closing" || activity === "closed"
    if (expected.command === "stop_cover") return activity === "open" || activity === "closed"
    var controls = listOrEmpty(item.controls)
    for (var i = 0; i < controls.length; i++) {
        var control = controls[i]
        if (control.command !== expected.command || control.value === null || control.value === undefined) continue
        if (control.active === false) return false
        if (expected.kind === "number") {
            return Math.abs(Number(control.value) - Number(expected.value)) < 0.000001
        }
        return String(control.value) === String(expected.value)
    }
    return false
}

function confirmDashboardFeedback(pageItem) {
    var feedback = listOrEmpty(pageItem.controlFeedback)
    var updated = feedback.slice(0)
    var changed = false
    var pages = listOrEmpty(pageItem.dashboardPages)
    for (var i = 0; i < feedback.length; i++) {
        if (!feedback[i].expected || feedbackState(feedback[i]) === "") continue
        for (var p = 0; p < pages.length; p++) {
            var items = listOrEmpty(pages[p].items)
            for (var j = 0; j < items.length; j++) {
                if (items[j].entity_id === feedback[i].entity_id && dashboardExpectationMatches(items[j], feedback[i].expected)) {
                    updated[i] = {entity_id: feedback[i].entity_id, state: "state_confirmed", expected: null, at: Date.now()}
                    changed = true
                }
            }
        }
    }
    if (changed) pageItem.controlFeedback = updated
}

function dashboardControl(item, control, value, statusItem, pageItem) {
    if (!item || !control || item.available === false || !pageItem.dashboardOnline || pageItem.pendingEntity) return
    var generation = pageItem.runtimeGeneration
    var commandGeneration = ++pageItem.commandGeneration
    var expected = dashboardExpectation(item, control, value)
    pageItem.pendingEntity = item.entity_id
    pageItem.controlInFlight = true
    setDashboardFeedback(pageItem, item.entity_id, "sending", expected)
    var path = "/homeassistant?domain=" + encodeURIComponent(item.domain || "c300x") + "&service=toggle&entities="
        + encodeURIComponent(item.entity_id + (control.command ? ":" + control.command : ""))
    if (value !== null && value !== undefined) path += "&option=" + encodeURIComponent(value)
    getJson(path, function(data) {
        if (generation !== pageItem.runtimeGeneration || commandGeneration !== pageItem.commandGeneration) return
        pageItem.controlInFlight = false
        if (!data || data.ok !== true) {
            pageItem.pendingEntity = ""
            setDashboardFeedback(pageItem, item.entity_id, "action_error")
            statusItem.text = uiText(pageItem, "action_error")
            statusItem.color = "#ff6b6b"
            return
        }
        setDashboardFeedback(pageItem, item.entity_id, "action_sent", expected)
        dashboard(statusItem, pageItem)
    }, function() {
        if (generation !== pageItem.runtimeGeneration || commandGeneration !== pageItem.commandGeneration) return
        pageItem.controlInFlight = false
        pageItem.pendingEntity = ""
        setDashboardFeedback(pageItem, item.entity_id, "state_unconfirmed")
        statusItem.text = uiText(pageItem, "state_unconfirmed")
        statusItem.color = "#f1c40f"
    })
}

function homeButtons(callback) {
    getJsonShared("/ui/state", function(data) {
        if (callback) {
            callback(
                data && data.alarm_configured === true,
                data && data.dashboard_available === true,
                true
            )
        }
    }, function() {
        if (callback) {
            callback(false, false, false)
        }
    })
}

function dashboardNextPage(statusItem, pageItem) {
    if (pageItem.pageCount <= 1) {
        return
    }
    pageItem.currentPageIndex = pageItem.currentPageIndex + 1
    if (pageItem.currentPageIndex >= pageItem.pageCount) {
        pageItem.currentPageIndex = 0
    }
    loadDashboardPage(statusItem, pageItem)
}

function dashboardPreviousPage(statusItem, pageItem) {
    if (pageItem.pageCount <= 1) {
        return
    }
    pageItem.currentPageIndex = pageItem.currentPageIndex - 1
    if (pageItem.currentPageIndex < 0) {
        pageItem.currentPageIndex = pageItem.pageCount - 1
    }
    loadDashboardPage(statusItem, pageItem)
}

function dashboardAction(item, statusItem, pageItem, refreshDashboard) {
    if (!item || !item.entity_id || !item.domain) {
        statusItem.text = uiText(pageItem, "invalid_action")
        statusItem.color = "#ff6b6b"
        return
    }
    if (refreshDashboard !== false) {
        dashboardControl(item, {command: ""}, null, statusItem, pageItem)
        return
    }
    var generation = pageItem.runtimeGeneration
    if (pageItem.quickActionPending) return
    pageItem.quickActionPending = true
    var quickGeneration = pageItem.quickActionGeneration
    var path = "/homeassistant?domain=" + encodeURIComponent(item.domain)
        + "&service=toggle&entities=" + encodeURIComponent(item.entity_id)
    getJson(path, function(data) {
        if (generation !== pageItem.runtimeGeneration) return
        if (quickGeneration !== pageItem.quickActionGeneration) return
        pageItem.quickActionPending = false
        statusItem.text = data.ok ? uiText(pageItem, "action_sent") : uiText(pageItem, "action_error")
        statusItem.color = data.ok ? "#58d68d" : "#ff6b6b"
        if (data.ok && pageItem.refreshAlarmStatus) {
            pageItem.refreshAlarmStatus(true)
        }
    }, function(error) {
        if (generation !== pageItem.runtimeGeneration) return
        if (quickGeneration !== pageItem.quickActionGeneration) return
        pageItem.quickActionPending = false
        statusItem.text = error
        statusItem.color = "#ff6b6b"
    })
}

function dashboardSliderAction(item, direction, statusItem, pageItem) {
    if (!item || !item.entity_id || !direction) {
        statusItem.text = uiText(pageItem, "invalid_action")
        statusItem.color = "#ff6b6b"
        return
    }
    dashboardControl(item, {command: direction}, null, statusItem, pageItem)
}

function dashboardChoiceAction(item, option, statusItem, pageItem) {
    if (!item || !item.entity_id || option === undefined || option === null) {
        statusItem.text = uiText(pageItem, "invalid_action")
        statusItem.color = "#ff6b6b"
        return
    }
    dashboardControl(item, {command: ""}, option, statusItem, pageItem)
}

function dashboardChoiceOptionLabel(option) {
    if (option && option.label !== undefined && option.label !== null) {
        return String(option.label)
    }
    return String(option || "")
}

function dashboardChoiceOptionValue(option) {
    if (option && option.value !== undefined && option.value !== null) {
        return String(option.value)
    }
    return String(option || "")
}


function alarmPageItem(source) {
    if (!source || !source.entity_id || !source.domain) {
        return null
    }
    var item = {
        "kind": source.kind || "entity",
        "domain": source.domain,
        "entity_id": source.entity_id,
        "name": source.name || source.entity_id,
        "state": source.state === true,
        "state_label": ""
    }
    if (source.name_key) {
        item.name_key = source.name_key
    }
    if (source.hasOwnProperty && source.hasOwnProperty("state_label")) {
        item.state_label = source.state_label
    } else if (source.label) {
        item.state_label = source.label
    }
    if (source.color) {
        item.color = source.color
    }
    return item
}


function alarmCommand(command, code, statusItem, pageItem, alarmStateItem, activeSinceItem, force) {
    if (pageItem.commandPending || pageItem.alarmOnline === false) return
    if (!force && !alarmCommandReady(pageItem.alarmCommandDetails, command)) {
        if (pageItem.setCommandFeedback) {
            pageItem.setCommandFeedback("not_ready_to_arm", command, "#ff6b6b")
        } else {
            statusItem.text = alarmBlockingText(pageItem.alarmCommandDetails, command, pageItem)
            statusItem.color = "#ff6b6b"
        }
        return
    }
    var generation = pageItem.runtimeGeneration
    pageItem.commandPending = true
    pageItem.commandInFlight = true
    var path = "/ui/alarm/command?command=" + encodeURIComponent(command)
    if (code && code.length > 0) {
        path += "&code=" + encodeURIComponent(code)
    }
    if (force) {
        path += "&force=true"
    }
    getJson(path, function(data) {
        if (generation !== pageItem.runtimeGeneration) return
        pageItem.commandInFlight = false
        pageItem.commandPending = false
        if (applyAlarmCommandResult(data, command, statusItem, pageItem)) {
            return
        }
        if (data.ok) {
            pageItem.commandPending = true
            if (pageItem.setCommandFeedback) {
                pageItem.setCommandFeedback("sending", command, "#f1c40f")
            } else {
                statusItem.text = uiText(pageItem, "sending")
                statusItem.color = "#f1c40f"
            }
            pageItem.bypassOffered = false
            if (command === "disarm" && pageItem.setAlarmDelayRemaining) {
                pageItem.setAlarmDelayRemaining(0)
            }
            if (pageItem.refreshSoon) {
                pageItem.refreshSoon()
            } else {
                status(statusItem, pageItem, alarmStateItem, activeSinceItem)
            }
            return
        }
        setErrorFeedback(command, statusItem, pageItem)
    }, function() {
        if (generation !== pageItem.runtimeGeneration) return
        pageItem.commandInFlight = false
        pageItem.commandPending = false
        setErrorFeedback(command, statusItem, pageItem)
    })
}

function alarmCheck(command, statusItem, pageItem) {
    if (pageItem.commandPending || pageItem.alarmOnline === false) return
    var generation = pageItem.runtimeGeneration
    pageItem.commandPending = true
    pageItem.commandInFlight = true
    var path = "/ui/alarm/command?command=" + encodeURIComponent(command) + "&check=true"
    getJson(path, function(data) {
        if (generation !== pageItem.runtimeGeneration) return
        pageItem.commandInFlight = false
        pageItem.commandPending = false
        if (applyAlarmCommandResult(data, command, statusItem, pageItem)) {
            return
        }
        if (data && data.ok === true) {
            mergeAlarmCommandDetail(pageItem, command, {
                "ready": data.ready !== false,
                "blocking_sensors": listOrEmpty(data.blocking_sensors),
                "blocking_sensor_count": positiveNumber(data.blocking_sensor_count, 0)
            })
            if (pageItem.refreshCommandReadiness) {
                pageItem.refreshCommandReadiness()
            }
            if (data.ready === false) {
                if (pageItem.setCommandFeedback) {
                    pageItem.setCommandFeedback("not_ready_to_arm", command, "#ff6b6b")
                } else {
                    statusItem.text = uiText(pageItem, "not_ready_to_arm")
                    statusItem.color = "#ff6b6b"
                }
            } else if (pageItem.setCommandFeedback) {
                pageItem.setCommandFeedback("ready_to_arm", command, "#58d68d")
            } else {
                statusItem.text = uiText(pageItem, "ready_to_arm")
                statusItem.color = "#58d68d"
            }
            return
        }
        setErrorFeedback(command, statusItem, pageItem)
    }, function() {
        if (generation !== pageItem.runtimeGeneration) return
        pageItem.commandInFlight = false
        pageItem.commandPending = false
        setErrorFeedback(command, statusItem, pageItem)
    })
}

function applyAlarmCommandResult(data, command, statusItem, pageItem) {
    if (!data || data.ok !== false) {
        return false
    }
    if (data.error === "not_ready_to_arm") {
        mergeAlarmCommandDetail(pageItem, command, data)
        pageItem.bypassOffered = true
        if (pageItem.refreshCommandReadiness) {
            pageItem.refreshCommandReadiness()
        }
        if (pageItem.clearCommandFeedback) {
            pageItem.clearCommandFeedback()
        }
        if (pageItem.flashCommandButton) {
            pageItem.flashCommandButton(command, "#ff6b6b")
        }
        statusItem.text = ""
        statusItem.color = "#ff6b6b"
        if (pageItem.setCommandFeedback && !pageItem.bypassVisible()) {
            pageItem.setCommandFeedback("not_ready_to_arm", command, "#ff6b6b")
        }
        return true
    }
    if (data.error === "invalid_code") {
        if (pageItem.setCommandFeedback) {
            pageItem.setCommandFeedback("invalid_code", command, "#ff6b6b")
        } else {
            statusItem.text = uiText(pageItem, "invalid_code")
            statusItem.color = "#ff6b6b"
        }
        return true
    }
    if (data.error === "alarm_state_unchanged" || data.error === "alarm_command_rejected") {
        setErrorFeedback(command, statusItem, pageItem)
        return true
    }
    return false
}

function setErrorFeedback(command, statusItem, pageItem) {
    if (pageItem.setCommandFeedback) {
        pageItem.setCommandFeedback("alarm_command_error", command, "#ff6b6b")
        return
    }
    statusItem.text = uiText(pageItem, "alarm_command_error")
    statusItem.color = "#ff6b6b"
}

function mergeAlarmCommandDetail(pageItem, command, update) {
    var current = listOrEmpty(pageItem.alarmCommandDetails)
    var merged = []
    var found = false
    for (var i = 0; i < current.length; i++) {
        var item = copyObject(current[i])
        if (item.command === command) {
            item.ready = update.ready === true
            item.blocking_sensors = listOrEmpty(update.blocking_sensors)
            item.blocking_sensor_count = positiveNumber(update.blocking_sensor_count, item.blocking_sensors.length)
            found = true
        }
        merged.push(item)
    }
    if (!found) {
        merged.push({
            "command": command,
            "ready": update.ready === true,
            "blocking_sensors": listOrEmpty(update.blocking_sensors),
            "blocking_sensor_count": positiveNumber(update.blocking_sensor_count, listOrEmpty(update.blocking_sensors).length)
        })
    }
    pageItem.alarmCommandDetails = merged
}

function copyObject(source) {
    var result = {}
    if (!source) {
        return result
    }
    for (var key in source) {
        result[key] = source[key]
    }
    return result
}

function alarmLabel(raw, pageItem) {
    if (raw === "disarmed") return uiText(pageItem, "disarmed")
    if (raw === "armed_home") return uiText(pageItem, "armed_home") + " " + uiText(pageItem, "active")
    if (raw === "armed_away") return uiText(pageItem, "armed_away") + " " + uiText(pageItem, "active")
    if (raw === "armed_night") return uiText(pageItem, "armed_night") + " " + uiText(pageItem, "active")
    if (raw === "armed_custom_bypass") return uiText(pageItem, "armed_custom_bypass") + " " + uiText(pageItem, "active")
    if (raw === "armed_vacation") return uiText(pageItem, "armed_vacation") + " " + uiText(pageItem, "active")
    if (raw === "arming") return uiText(pageItem, "arming")
    if (raw === "pending") return uiText(pageItem, "pending")
    if (raw === "triggered") return uiText(pageItem, "triggered")
    if (raw === "unavailable") return uiText(pageItem, "offline")
    return uiText(pageItem, "unknown")
}

function alarmCommands(alarm) {
    if (alarm.commands && alarm.commands.length !== undefined) {
        var commands = []
        for (var i = 0; i < alarm.commands.length; i++) {
            if (alarm.commands[i].command) {
                commands.push(alarm.commands[i].command)
            }
        }
        return commands
    }
    return ["arm_home", "arm_away", "arm_night", "arm_vacation"]
}

function alarmCommandDetails(alarm) {
    var details = []
    if (alarm.commands && alarm.commands.length !== undefined) {
        for (var i = 0; i < alarm.commands.length; i++) {
            if (alarm.commands[i].command) {
                details.push(alarm.commands[i])
            }
        }
    }
    return details
}

function alarmCommandRequiresCode(details, command) {
    if (!details || details.length === undefined) {
        return false
    }
    for (var i = 0; i < details.length; i++) {
        if (details[i].command === command) {
            return details[i].code_required === true
        }
    }
    return false
}

function alarmCommandReady(details, command) {
    var detail = alarmCommandDetail(details, command)
    if (!detail) {
        return true
    }
    if (positiveNumber(detail.blocking_sensor_count, 0) > 0) {
        return false
    }
    if (listOrEmpty(detail.blocking_sensors).length > 0) {
        return false
    }
    return detail.ready !== false
}

function alarmCommandHasBlockers(details, command) {
    var detail = alarmCommandDetail(details, command)
    if (!detail) {
        return false
    }
    return positiveNumber(detail.blocking_sensor_count, 0) > 0
        || listOrEmpty(detail.blocking_sensors).length > 0
}

function alarmBlockingText(details, command, pageItem) {
    var detail = alarmCommandDetail(details, command)
    if (!detail || alarmCommandReady(details, command)) {
        return uiText(pageItem, "ready_to_arm")
    }
    var sensors = listOrEmpty(detail.blocking_sensors)
    if (sensors.length === 0) {
        return uiText(pageItem, "not_ready_to_arm")
    }
    var names = []
    var maxNames = sensors.length
    for (var i = 0; i < maxNames; i++) {
        names.push(sensors[i].name || sensors[i].entity_id || uiText(pageItem, "unknown"))
    }
    var count = positiveNumber(detail.blocking_sensor_count, sensors.length)
    var suffix = count > names.length ? " +" + (count - names.length) : ""
    return uiText(pageItem, "sensor_open") + ": " + names.join(", ") + suffix
}

function alarmOpenSensorsText(pageItem) {
    var sensors = listOrEmpty(pageItem.alarmOpenSensors)
    if (sensors.length === 0) {
        return ""
    }
    var names = []
    var maxNames = sensors.length
    for (var i = 0; i < maxNames; i++) {
        names.push(sensors[i].name || sensors[i].entity_id || uiText(pageItem, "unknown"))
    }
    var count = positiveNumber(pageItem.alarmOpenSensorCount, sensors.length)
    var suffix = count > names.length ? " +" + (count - names.length) : ""
    return uiText(pageItem, "sensor_open") + ": " + names.join(", ") + suffix
}

function alarmCommandDetail(details, command) {
    if (!details || details.length === undefined) {
        return null
    }
    for (var i = 0; i < details.length; i++) {
        if (details[i].command === command) {
            return details[i]
        }
    }
    return null
}

function commandForState(raw) {
    if (raw === "arming") return "disarm"
    if (raw === "pending") return "disarm"
    if (raw === "triggered") return "disarm"
    if (raw === "armed_home") return "arm_home"
    if (raw === "armed_away") return "arm_away"
    if (raw === "armed_night") return "arm_night"
    if (raw === "armed_custom_bypass") return "arm_custom_bypass"
    if (raw === "armed_vacation") return "arm_vacation"
    return ""
}

function contains(values, wanted) {
    for (var i = 0; i < values.length; i++) {
        if (values[i] === wanted) return true
    }
    return false
}

function dashboardPages(data) {
    if (!isList(data && data.data && data.data.pages)) {
        return []
    }
    return data.data.pages
}

function sameDashboardValue(previous, value) {
    if (previous === value) return true
    if (previous === null || value === null) return false
    var kind = typeof previous
    if (kind !== typeof value) return false
    // Strings carry a length too, so primitives must be settled before isList.
    if (kind !== "object") return false
    var previousIsList = isList(previous)
    if (previousIsList !== isList(value)) return false
    if (previousIsList) {
        if (previous.length !== value.length) return false
        for (var i = 0; i < previous.length; i++) {
            if (!sameDashboardValue(previous[i], value[i])) return false
        }
        return true
    }
    var surplus = 0
    for (var previousKey in previous) {
        if (!sameDashboardValue(previous[previousKey], value[previousKey])) return false
        surplus++
    }
    for (var valueKey in value) {
        surplus--
    }
    return surplus === 0
}

function assignDashboardValue(target, key, value) {
    // target[key] is a QML variant: reading it converts the stored value back
    // into JavaScript, so read it once. Comparing structurally stops at the
    // first difference, where JSON.stringify had to build two complete strings
    // of the whole dashboard on every event-driven refresh.
    //
    // Reusing unchanged elements of a changed list used to happen here. It
    // cannot work: assigning to a variant property copies the whole structure
    // into a QVariant, so element identity is lost anyway. Skipping an
    // unchanged value entirely, below, is what actually preserves identity.
    if (sameDashboardValue(target[key], value)) return
    target[key] = value
}

function loadDashboardPage(statusItem, pageItem) {
    var pageData = currentDashboardPage(pageItem)
    var flow = pageData.flow || {}
    var flowItems = listOrEmpty(flow.items)
    var flowLines = listOrEmpty(flow.lines)
    assignDashboardValue(pageItem, "badges", listOrEmpty(pageData.badges))
    assignDashboardValue(pageItem, "items", dashboardMixedItems(pageData.items))
    applyWeather(pageItem, pageData.weather)
    assignDashboardValue(pageItem, "flowItems", flowItems)
    assignDashboardValue(pageItem, "flowLines", flowLines)
    pageItem.flowWidth = positiveNumber(flow.width, 0)
    pageItem.flowHeight = positiveNumber(flow.height, 0)
    pageItem.flowColor = flow.color || "transparent"
    pageItem.flowVisible = flowItems.length > 0 || flowLines.length > 0
    if (pageItem.flowVisible && pageItem.flowHeight <= 0) {
        pageItem.flowHeight = 150
    }
    pageItem.pageTitle = dashboardPageTitle(pageData)
    pageItem.pageLabel = pageItem.pageCount > 1 ? uiText(pageItem, "page") + " " + (pageItem.currentPageIndex + 1) + "/" + pageItem.pageCount : ""
    if (pageItem.pageCount > 0) {
        statusItem.text = uiText(pageItem, "page") + " " + (pageItem.currentPageIndex + 1) + " " + uiText(pageItem, "status_loaded")
        statusItem.color = "#58d68d"
    }
}

function currentDashboardPage(pageItem) {
    if (!pageItem.dashboardPages || pageItem.dashboardPages.length === 0) {
        return {}
    }
    if (pageItem.currentPageIndex < 0 || pageItem.currentPageIndex >= pageItem.dashboardPages.length) {
        pageItem.currentPageIndex = 0
    }
    return pageItem.dashboardPages[pageItem.currentPageIndex] || {}
}

function dashboardPageTitle(pageData) {
    if (!pageData) {
        return ""
    }
    var title = pageData.title || pageData.name || ""
    return title === "C300X" || title === "Home Assistant" ? "" : title
}

function applyWeather(pageItem, source) {
    if (!source || source.available === undefined) {
        pageItem.weatherVisible = false
        pageItem.weatherTitle = ""
        pageItem.weatherCondition = ""
        pageItem.weatherConditionKey = ""
        pageItem.weatherTemperature = ""
        pageItem.weatherHumidity = ""
        pageItem.weatherWind = ""
        pageItem.weatherForecast = ""
        assignDashboardValue(pageItem, "weatherForecast1", {})
        assignDashboardValue(pageItem, "weatherForecast2", {})
        pageItem.weatherSun = ""
        pageItem.weatherSunrise = ""
        pageItem.weatherSunset = ""
        pageItem.weatherUpdated = ""
        pageItem.weatherColor = "#58d68d"
        return
    }
    pageItem.weatherVisible = true
    pageItem.weatherTitle = source.title || uiText(pageItem, "weather")
    pageItem.weatherConditionKey = source.condition_key || source.condition || "unknown"
    pageItem.weatherCondition = pageItem.uiWeather ? pageItem.uiWeather(pageItem.weatherConditionKey, source.condition || "") : (source.condition || uiText(pageItem, "unknown"))
    pageItem.weatherTemperature = source.temperature || ""
    pageItem.weatherHumidity = source.humidity || ""
    pageItem.weatherWind = source.wind || ""
    pageItem.weatherForecast = source.forecast || ""
    assignDashboardValue(pageItem, "weatherForecast1", source.forecast_1 || {})
    assignDashboardValue(pageItem, "weatherForecast2", source.forecast_2 || {})
    pageItem.weatherSun = source.sun || ""
    pageItem.weatherSunrise = source.sunrise || ""
    pageItem.weatherSunset = source.sunset || ""
    pageItem.weatherUpdated = source.updated || ""
    pageItem.weatherColor = source.color || "#58d68d"
}

function dashboardItems(source, kind) {
    source = listOrEmpty(source)
    var target = []
    for (var i = 0; i < source.length; i++) {
        if (!source[i].entity_id || !source[i].domain) {
            continue
        }
        var item = {
            "kind": kind,
            "domain": source[i].domain,
            "entity_id": source[i].entity_id,
            "name": source[i].name || source[i].entity_id,
            "state": source[i].state === true
        }
        if (source[i].hasOwnProperty && source[i].hasOwnProperty("state_label")) {
            item.state_label = source[i].state_label
        } else if (source[i].label) {
            item.state_label = source[i].label
        }
        if (source[i].color) {
            item.color = source[i].color
        }
        target.push(item)
    }
    return target
}

function dashboardMixedItems(source) {
    source = listOrEmpty(source)
    var target = []
    for (var i = 0; i < source.length; i++) {
        var kind = source[i].kind || ""
        var normalized = []
        if (kind === "slider") {
            normalized = dashboardSliders([source[i]])
        } else if (kind === "choice") {
            normalized = dashboardChoices([source[i]])
        } else if (kind === "image") {
            normalized = dashboardImages([source[i]])
        } else {
            normalized = dashboardItems([source[i]], kind || "entity")
        }
        if (normalized.length > 0) {
            normalized[0].available = source[i].available !== false
            if (source[i].details) normalized[0].details = source[i].details
            if (source[i].controls !== undefined) {
                normalized[0].controls = listOrEmpty(source[i].controls)
                normalized[0].available = source[i].available !== false
                normalized[0].current_temperature = source[i].current_temperature
                normalized[0].temperature_unit = source[i].temperature_unit || ""
            }
            target.push(normalized[0])
        }
    }
    return target
}

function dashboardDetailControls(item) {
    var controls = item ? listOrEmpty(item.controls) : []
    var result = []
    var hasPalette = false
    var cover = item && item.details && item.details.type === "cover"
    for (var i = 0; i < controls.length; i++) {
        if (controls[i].command === "color") hasPalette = true
    }
    for (var j = 0; j < controls.length; j++) {
        var control = controls[j]
        if (cover && (control.command === "open_cover" || control.command === "stop_cover" || control.command === "close_cover")) continue
        if (hasPalette && (control.command === "hue" || control.command === "saturation")) continue
        result.push(control)
    }
    return result
}

function dashboardControlByCommand(item, command) {
    var controls = item ? listOrEmpty(item.controls) : []
    for (var i = 0; i < controls.length; i++) {
        if (controls[i].command === command) return controls[i]
    }
    return null
}

function dashboardDetailSections(item) {
    if (!item || !item.details) return []
    if (item.details.type === "light" && dashboardControlByCommand(item, "color_temp_kelvin") && dashboardControlByCommand(item, "color")) {
        return ["white_mode", "color_mode"]
    }
    if (item.details.type === "climate") {
        var controls = listOrEmpty(item.controls)
        for (var i = 0; i < controls.length; i++) {
            if (!isMainClimateControl(controls[i])) return ["main_controls", "more_controls"]
        }
    }
    return []
}

function isMainClimateControl(control) {
    return control.command === "temperature" || control.command === "target_temp_low" || control.command === "target_temp_high" || control.command === "hvac_mode"
}

function dashboardVisibleControls(item, section) {
    var controls = dashboardDetailControls(item)
    var sections = dashboardDetailSections(item)
    var result = []
    for (var i = 0; i < controls.length; i++) {
        var control = controls[i]
        if (item && item.details && (item.details.type === "light" || item.details.type === "fan") && control.command === "toggle") continue
        if (sections.length > 0 && item.details.type === "light") {
            if (section === "color_mode" && control.command === "color_temp_kelvin") continue
            if (section !== "color_mode" && control.command === "color") continue
        }
        if (sections.length > 0 && item.details.type === "climate") {
            if (isMainClimateControl(control) === (section === "more_controls")) continue
        }
        result.push(control)
    }
    return result
}

function dashboardCoverControls(item) {
    var controls = item ? listOrEmpty(item.controls) : []
    var result = []
    var commands = ["open_cover", "stop_cover", "close_cover"]
    for (var i = 0; i < commands.length; i++) {
        for (var j = 0; j < controls.length; j++) {
            if (controls[j].command === commands[i]) result.push(controls[j])
        }
    }
    return result
}

function dashboardSliders(source) {
    source = listOrEmpty(source)
    var target = []
    for (var i = 0; i < source.length; i++) {
        if (!source[i].entity_id) {
            continue
        }
        target.push({
            "kind": "slider",
            "domain": source[i].domain || "c300x",
            "entity_id": source[i].entity_id,
            "name": source[i].name || source[i].entity_id,
            "state": false,
            "state_label": source[i].state_label || source[i].label || "",
            "value": Number(source[i].value || 0),
            "min": Number(source[i].min || 0),
            "max": Number(source[i].max || 100),
            "step": Number(source[i].step || 1)
        })
    }
    return target
}

function dashboardChoices(source) {
    source = listOrEmpty(source)
    var target = []
    for (var i = 0; i < source.length; i++) {
        if (!source[i].entity_id) {
            continue
        }
        target.push({
            "kind": "choice",
            "domain": source[i].domain || "c300x",
            "entity_id": source[i].entity_id,
            "name": source[i].name || source[i].entity_id,
            "state": false,
            "state_label": source[i].state_label || source[i].value || "",
            "value": source[i].value || "",
            "options": dashboardChoiceOptions(source[i].options)
        })
    }
    return target
}

function dashboardChoiceOptions(source) {
    source = listOrEmpty(source)
    var target = []
    for (var i = 0; i < source.length; i++) {
        if (source[i] && source[i].value !== undefined) {
            target.push({
                "label": source[i].label !== undefined ? String(source[i].label) : String(source[i].value),
                "value": String(source[i].value)
            })
        } else if (source[i] !== undefined && source[i] !== null) {
            target.push({
                "label": String(source[i]),
                "value": String(source[i])
            })
        }
    }
    return target
}

function dashboardImages(source) {
    source = listOrEmpty(source)
    var images = []
    for (var i = 0; i < source.length; i++) {
        if (!source[i].source) {
            continue
        }
        images.push({
            "kind": "image",
            "source": imageSource(source[i].source),
            "width": positiveNumber(source[i].width, 220),
            "height": positiveNumber(source[i].height, 120)
        })
    }
    return images
}

function imageSource(source) {
    source = String(source || "")
    return source
}

function positiveNumber(value, fallbackValue) {
    var numberValue = Number(value)
    if (isNaN(numberValue) || numberValue <= 0) {
        return fallbackValue
    }
    return numberValue
}

function isList(value) {
    return value && value.length !== undefined
}

function listOrEmpty(value) {
    return isList(value) ? value : []
}

function formatActiveSince(value, pageItem) {
    if (!value || value.length < 16) {
        return ""
    }
    return uiText(pageItem, "since") + " " + value.substring(8, 10) + "." + value.substring(5, 7) + ". " + value.substring(11, 16)
}

function uiText(pageItem, key) {
    if (pageItem && pageItem.uiText) {
        return pageItem.uiText(key)
    }
    return key
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
    var request = eventRequest
    eventRequest = null
    if (request) {
        request.onreadystatechange = function() {}
        removeConnection(request)
        if (request.readyState < 4) request.abort()
    }
}

function stopDashboardRuntime() {
    stopEventWatch()
    // Before the aborts: an abort completes its request, and a completed
    // request would otherwise start the next queued one that is being torn
    // down here.
    forwardQueue = []
    forwardActive = null
    while (connections.length > 0) {
        var request = connections.pop()
        request.onreadystatechange = function() {}
        if (request.readyState < 4) request.abort()
    }
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
        if (eventRequest !== xhr) return
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
                if (eventCallback) eventCallback({topic: "connection.error"})
            }
        } else if (eventWatching === true) {
            eventWatching = false
            if (eventCallback) eventCallback({topic: "connection.error"})
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

// Every request this function sends is forwarded to Home Assistant by the
// agent, which keeps exactly one of them in flight: forward_to_homeassistant
// stores the client socket in display_client_fd and answers a second request
// with 503 display_command_pending until the first one is done or the Home
// Assistant timeout expires.
//
// That collision is avoidable rather than worth reporting, because this
// library is its only producer. The four forwarding routes are loopback only,
// so nothing off the device can take the slot, all of them are reached from
// here, and QML shares one instance of a .pragma library across the home,
// alarm and dashboard pages. Waking from standby used to collide reliably: the
// home page refreshes its dynamic buttons when it becomes visible, and opening
// the alarm or dashboard page in that window hit the busy slot.
//
// The event long poll deliberately does not go through here. It has its own
// request and its own waiter slots in the agent, and it blocks for seconds by
// design, so serialising it would stall every other request behind it.
var FORWARD_QUEUE_LIMIT = 8
var forwardActive = null
var forwardQueue = []

function getJson(path, callback, errorCallback) {
    forwardRequest(path, callback, errorCallback, "")
}

function getJsonShared(path, callback, errorCallback) {
    // For an idempotent read only. Such a request answers every caller the
    // same way, so two pages asking for the same path at the same time share
    // one round trip instead of taking the slot twice - waking from standby
    // asks /ui/state from the home page and from the page being opened.
    // Commands never come through here: folding two of them would execute one
    // and silently drop the other.
    if (forwardActive !== null && forwardActive.sharedPath === path) {
        forwardActive.waiters.push({callback: callback, errorCallback: errorCallback})
        return
    }
    for (var i = 0; i < forwardQueue.length; i++) {
        if (forwardQueue[i].sharedPath === path) {
            forwardQueue[i].waiters.push({callback: callback, errorCallback: errorCallback})
            return
        }
    }
    forwardRequest(path, callback, errorCallback, path)
}

function forwardRequest(path, callback, errorCallback, sharedPath) {
    cleanupConnections()
    var entry = {
        path: path,
        sharedPath: sharedPath,
        waiters: [{callback: callback, errorCallback: errorCallback}]
    }
    if (forwardActive !== null) {
        if (forwardQueue.length >= FORWARD_QUEUE_LIMIT) {
            // Unreachable while each page keeps one request in flight. Report
            // it rather than drop it, so a pressed button never goes silent.
            if (errorCallback) errorCallback("queue full")
            return
        }
        forwardQueue.push(entry)
        return
    }
    sendForward(entry)
}

function sendForward(entry) {
    var xhr = new XMLHttpRequest()
    xhr.sharedPath = entry.sharedPath
    xhr.waiters = entry.waiters
    forwardActive = xhr
    connections.push(xhr)
    xhr.startTime = Date.now()
    xhr.onreadystatechange = function() {
        if (xhr.readyState !== 4) {
            return
        }
        removeConnection(xhr)
        try {
            deliverForward(xhr)
        } finally {
            // Even a callback that throws has to hand the slot on, or the
            // whole display would stop talking to the agent.
            finishForward(xhr)
        }
    }
    xhr.open("GET", BASE_URL + entry.path)
    xhr.send()
}

function deliverForward(xhr) {
    var waiters = xhr.waiters
    // Taken before the first callback runs: a callback can start the next
    // request, and an answered read must not still collect waiters.
    xhr.waiters = []
    xhr.sharedPath = ""
    var data = null
    var failure = ""
    if (xhr.status === 200) {
        try {
            data = JSON.parse(xhr.responseText)
        } catch (error) {
            failure = "Invalid JSON"
        }
    } else {
        failure = "API error: " + xhr.status
    }
    for (var i = 0; i < waiters.length; i++) {
        try {
            if (failure.length === 0) {
                try {
                    waiters[i].callback(data)
                } catch (error) {
                    if (waiters[i].errorCallback) waiters[i].errorCallback("Invalid JSON")
                }
            } else if (waiters[i].errorCallback) {
                waiters[i].errorCallback(failure)
            }
        } catch (error) {
            // One page's broken handler must not keep the pages sharing this
            // answer from being told.
        }
    }
}

function finishForward(xhr) {
    if (forwardActive !== xhr) {
        return
    }
    forwardActive = null
    if (forwardQueue.length === 0) {
        return
    }
    sendForward(forwardQueue.shift())
}

function cleanupConnections() {
    var pending = connections.slice(0)
    var i = pending.length
    while (i--) {
        var request = pending[i]
        if (request.longPoll === true && request === eventRequest && eventWatching === true) {
            continue
        }
        if (Date.now() - request.startTime > 10000) {
            if (request.readyState < 4) request.abort()
            removeConnection(request)
        }
    }
}
