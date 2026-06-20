.pragma library

var BASE_URL = "http://127.0.0.1:8090"
var connections = []
var dashboardRevision = ""
var eventRevision = 0
var eventRequest = null
var eventWatching = false
var eventCallback = null

function status(statusItem, pageItem, alarmStateItem, activeSinceItem) {
    getJson("/ui/state", function(data) {
        if (pageItem.clearCommandFeedback) {
            pageItem.clearCommandFeedback()
        }
        statusItem.text = uiText(pageItem, "ha_connected")
        statusItem.color = "#58d68d"
        if (data.alarm && data.alarm.state) {
            var previousState = pageItem.alarmRawState
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
            if (currentCommand && contains(pageItem.alarmCommands, currentCommand)) {
                pageItem.selectedCommand = currentCommand
            }
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
        statusItem.text = error
        statusItem.color = "#ff6b6b"
        if (pageItem.setAlarmDelayRemaining) {
            pageItem.setAlarmDelayRemaining(0)
        }
    })
}

function dashboard(statusItem, pageItem) {
    var path = "/homeassistant"
    if (dashboardRevision.length > 0) {
        path += "?revision=" + encodeURIComponent(dashboardRevision)
    }
    getJson(path, function(data) {
        if (data && data.not_modified === true) {
            statusItem.text = uiText(pageItem, "board_loaded")
            statusItem.color = "#58d68d"
            return
        }
        if (data && data.revision !== undefined) {
            dashboardRevision = String(data.revision)
        }
        var pages = dashboardPages(data)
        pageItem.preventReturnToHomepage = data.preventReturnToHomepage === true
        pageItem.dashboardPages = pages
        pageItem.pageCount = pages.length
        if (pageItem.currentPageIndex >= pages.length) {
            pageItem.currentPageIndex = 0
        }
        loadDashboardPage(statusItem, pageItem)
        statusItem.text = pages.length > 0 ? uiText(pageItem, "board_loaded") : uiText(pageItem, "no_dashboard_pages")
        statusItem.color = pages.length > 0 ? "#58d68d" : "#f1c40f"
    }, function(error) {
        statusItem.text = error
        statusItem.color = "#ff6b6b"
        pageItem.dashboardPages = []
        pageItem.badges = []
        pageItem.items = []
        pageItem.switches = []
        pageItem.entities = []
        pageItem.sliders = []
        pageItem.choices = []
        pageItem.buttons = []
        pageItem.images = []
        pageItem.flowItems = []
        pageItem.flowLines = []
        pageItem.flowVisible = false
        pageItem.weatherVisible = false
        pageItem.pageCount = 0
        pageItem.pageTitle = ""
        pageItem.pageLabel = ""
    })
}

function homeButtons(callback) {
    getJson("/ui/state", function(data) {
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
    var path = "/homeassistant?domain=" + encodeURIComponent(item.domain)
        + "&service=toggle&entities=" + encodeURIComponent(item.entity_id)
    getJson(path, function(data) {
        statusItem.text = data.ok ? uiText(pageItem, "action_sent") : uiText(pageItem, "action_error")
        statusItem.color = data.ok ? "#58d68d" : "#ff6b6b"
        if (refreshDashboard !== false) {
            dashboard(statusItem, pageItem)
        }
    }, function(error) {
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
    var path = "/homeassistant?domain=c300x&service=toggle&entities="
        + encodeURIComponent(item.entity_id + ":" + direction)
    getJson(path, function(data) {
        statusItem.text = data.ok ? uiText(pageItem, "action_sent") : uiText(pageItem, "action_error")
        statusItem.color = data.ok ? "#58d68d" : "#ff6b6b"
        dashboard(statusItem, pageItem)
    }, function(error) {
        statusItem.text = error
        statusItem.color = "#ff6b6b"
    })
}

function dashboardChoiceAction(item, option, statusItem, pageItem) {
    if (!item || !item.entity_id || option === undefined || option === null) {
        statusItem.text = uiText(pageItem, "invalid_action")
        statusItem.color = "#ff6b6b"
        return
    }
    var path = "/homeassistant?domain=c300x&service=toggle&entities="
        + encodeURIComponent(item.entity_id)
        + "&option=" + encodeURIComponent(option)
    getJson(path, function(data) {
        statusItem.text = data.ok ? uiText(pageItem, "action_sent") : uiText(pageItem, "action_error")
        statusItem.color = data.ok ? "#58d68d" : "#ff6b6b"
        dashboard(statusItem, pageItem)
    }, function(error) {
        statusItem.text = error
        statusItem.color = "#ff6b6b"
    })
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
        return {
            "kind": "button",
            "domain": "c300x",
            "entity_id": "stair_light",
            "name_key": "stair_light",
            "name": "stair_light",
            "state": false,
            "state_label": ""
        }
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
    if (!force && !alarmCommandReady(pageItem.alarmCommandDetails, command)) {
        if (pageItem.setCommandFeedback) {
            pageItem.setCommandFeedback("not_ready_to_arm", command, "#ff6b6b")
        } else {
            statusItem.text = alarmBlockingText(pageItem.alarmCommandDetails, command, pageItem)
            statusItem.color = "#ff6b6b"
        }
        return
    }
    var path = "/ui/alarm/command?command=" + encodeURIComponent(command)
    if (code && code.length > 0) {
        path += "&code=" + encodeURIComponent(code)
    }
    if (force) {
        path += "&force=true"
    }
    getJson(path, function(data) {
        if (applyAlarmCommandResult(data, command, statusItem, pageItem)) {
            return
        }
        if (data.ok) {
            if (pageItem.setCommandFeedback) {
                pageItem.setCommandFeedback("alarm_command_sent", command, "#58d68d")
            } else {
                statusItem.text = uiText(pageItem, "alarm_command_sent")
                statusItem.color = "#58d68d"
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
        setErrorFeedback(command, statusItem, pageItem)
    })
}

function alarmCheck(command, statusItem, pageItem) {
    var path = "/ui/alarm/command?command=" + encodeURIComponent(command) + "&check=true"
    getJson(path, function(data) {
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

function loadDashboardPage(statusItem, pageItem) {
    var pageData = currentDashboardPage(pageItem)
    var flow = pageData.flow || {}
    var flowItems = listOrEmpty(flow.items)
    var flowLines = listOrEmpty(flow.lines)
    pageItem.badges = listOrEmpty(pageData.badges)
    pageItem.items = dashboardMixedItems(pageData.items)
    pageItem.switches = []
    pageItem.entities = []
    pageItem.sliders = []
    pageItem.choices = []
    pageItem.buttons = []
    pageItem.images = []
    applyWeather(pageItem, pageData.weather)
    pageItem.flowItems = flowItems
    pageItem.flowLines = flowLines
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
        pageItem.weatherSun = ""
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
    pageItem.weatherSun = source.sun || ""
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
            target.push(normalized[0])
        }
    }
    return target
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
    if (eventRequest && eventRequest.readyState < 4) {
        eventRequest.abort()
    }
    if (eventRequest) {
        removeConnection(eventRequest)
    }
    eventRequest = null
}

function stopDashboardRuntime() {
    stopEventWatch()
    var i = connections.length
    while (i--) {
        if (connections[i].readyState < 4) {
            connections[i].abort()
        }
        connections.splice(i, 1)
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
                    if (errorCallback) {
                        errorCallback("Invalid JSON")
                    }
                }
            } else {
                if (errorCallback) {
                    errorCallback("API error: " + xhr.status)
                }
            }
        }
    }
    xhr.open("GET", BASE_URL + path)
    xhr.send()
}

function cleanupConnections() {
    var i = connections.length
    while (i--) {
        if (connections[i].longPoll === true) {
            continue
        }
        if (Date.now() - connections[i].startTime > 3000) {
            if (connections[i].readyState < 4) {
                connections[i].abort()
            }
            connections.splice(i, 1)
        }
    }
}
