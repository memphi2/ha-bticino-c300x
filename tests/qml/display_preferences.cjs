const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../..");
const jsRoot = process.env.C300X_DEVICE_JS_ROOT || path.join(root, "device_qml/js");

function runtime() {
    const requests = [];
    function Request() { this.headers = {}; }
    Request.prototype.open = function(method, url) { this.method = method; this.url = url; };
    Request.prototype.setRequestHeader = function(key, value) { this.headers[key] = value; };
    Request.prototype.send = function(body) { this.body = body; requests.push(this); };
    Request.prototype.abort = function() { this.aborted = true; this.finish(0, ""); };
    Request.prototype.finish = function(status, body) {
        this.status = status;
        this.responseText = JSON.stringify(body);
        this.readyState = 4;
        this.onreadystatechange();
    };
    const api = vm.createContext({XMLHttpRequest: Request});
    vm.runInContext(fs.readFileSync(path.join(jsRoot, "c300x_ha.js"), "utf8")
        .replace(/^\.pragma library\s*/, ""), api);
    const owner = {feedbackEnabled: true, ready: false, busy: false, stopped: false,
        uiBaseUrl: "http://127.0.0.1:18123", errorKey: "", deadline: {
            running: false, restart() { this.running = true; }, stop() { this.running = false; },
        }};
    Object.defineProperty(owner, "request", {
        set() { throw new Error("Qt 4 cannot retain XHR objects in a QML variant"); },
        get() { throw new Error("XHR must stay in JavaScript"); },
    });
    return {api, owner, requests};
}

{
    const {api, owner, requests} = runtime();
    api.saveDisplayPreferences(owner, false);
    assert.equal(requests.length, 0, "cannot write before reading confirmed preferences");
    api.loadDisplayPreferences(owner);
    api.loadDisplayPreferences(owner);
    assert.equal(requests.length, 1, "coalesce startup and settings entry");
    assert.equal(requests[0].method, "GET");
    assert.equal(requests[0].url, owner.uiBaseUrl + "/ui/preferences");
    assert.equal(owner.deadline.running, true);
    requests[0].finish(200, {ok: true, feedback_enabled: false});
    assert.equal(owner.feedbackEnabled, false);
    assert.equal(owner.ready, true);
    assert.equal(owner.deadline.running, false);
    api.loadDisplayPreferences(owner);
    api.saveDisplayPreferences(owner, false);
    api.saveDisplayPreferences(owner, "true");
    assert.equal(requests.length, 1, "no polling, unchanged saves or coercion");
    api.saveDisplayPreferences(owner, true);
    assert.equal(requests[1].method, "POST");
    assert.equal(requests[1].url, owner.uiBaseUrl + "/ui/preferences");
    assert.equal(requests[1].headers["X-C300X-UI"], "1");
    assert.deepEqual(JSON.parse(requests[1].body), {feedback_enabled: true});
    assert.equal(owner.feedbackEnabled, false, "do not claim a save before confirmation");
    api.saveDisplayPreferences(owner, true);
    assert.equal(requests.length, 2, "one command at a time");
    requests[1].finish(200, {ok: true, feedback_enabled: true});
    assert.equal(owner.feedbackEnabled, true);
}

for (const [status, body] of [[500, {ok: true, feedback_enabled: false}],
    [200, {}], [200, {ok: true, feedback_enabled: "false"}], [200, null]]) {
    const {api, owner, requests} = runtime();
    api.loadDisplayPreferences(owner);
    requests[0].finish(status, body);
    assert.equal(owner.feedbackEnabled, true);
    assert.equal(owner.ready, false);
    assert.equal(owner.busy, false);
    assert.equal(owner.errorKey, "display_settings_error");
    assert.equal(requests.length, 1, "failure does not cause automatic traffic");
    api.loadDisplayPreferences(owner);
    assert.equal(requests.length, 2, "reopening settings can retry a read");
}

for (const stopped of [false, true]) {
    const {api, owner, requests} = runtime();
    owner.ready = true;
    api.saveDisplayPreferences(owner, false);
    const lateCallback = requests[0].onreadystatechange;
    owner.stopped = stopped;
    api.cancelDisplayPreferences(owner);
    assert.equal(requests[0].aborted, true);
    assert.equal(owner.ready, false, "timeout is an ambiguous save, reread before another write");
    assert.equal(owner.feedbackEnabled, true);
    requests[0].finish(200, {ok: true, feedback_enabled: false});
    lateCallback();
    assert.equal(owner.feedbackEnabled, true, "cancelled completion cannot change bindings");
    api.loadDisplayPreferences(owner);
    assert.equal(requests.length, stopped ? 1 : 2);
    if (!stopped) {
        lateCallback();
        assert.equal(owner.busy, true, "late completion cannot clear the replacement request");
        requests[1].finish(200, {ok: true, feedback_enabled: false});
        assert.equal(owner.feedbackEnabled, false, "readback resolves an ambiguous save");
    }
}

{
    const {api, owner, requests} = runtime();
    api.loadDisplayPreferences(owner);
    api.cancelDisplayPreferences({stopped: true});
    assert.equal(requests[0].aborted, undefined, "a different owner cannot cancel this request");
    requests[0].finish(200, {ok: true, feedback_enabled: true});
    assert.equal(owner.ready, true);
}

function page(name, values) {
    const qml = fs.readFileSync(path.join(root, "device_qml", name), "utf8");
    const ctx = vm.createContext(values);
    vm.runInContext([...qml.matchAll(/^    function [\s\S]*?^    }/gm)]
        .map(m => m[0]).join("\n"), ctx);
    return ctx;
}

{
    const {api} = runtime();
    const p = page("HomeAssistant.qml", {Api: api,
        I18n: {text: (_, key) => key}, uiLanguage: "en",
        feedbackColorsEnabled: false, status: {}, selectedItem: null,
        runtimeGeneration: 0, dashboardLoading: false, dashboardRefreshAgain: false,
        currentPageIndex: 0, pageCount: 2, dashboardPages: [{items: []}, {items: []}]});
    const queued = [];
    p.page = p;
    api.getJson = (url, success, failure) => queued.push({success, failure});
    for (const kind of ["initial", "unchanged", "navigation"]) {
        if (kind === "navigation") {
            api.dashboardNextPage(p.status, p);
        } else {
            api.dashboard(p.status, p);
            queued.shift().success(kind === "unchanged" ? {not_modified: true}
                : {data: {pages: [{items: []}, {items: []}]}});
        }
        assert.equal(p.status.optionalFeedback, true, kind);
        assert.notEqual(p.status.text, "", "retain the underlying status");
        assert.equal(p.statusText(), "", "off hides the routine header message");
        p.feedbackColorsEnabled = true;
        assert.equal(p.statusText(), p.status.text, "on restores it without another request");
        p.feedbackColorsEnabled = false;
        for (const key of ["action_error", "stale_state", "sending", "state_unconfirmed"]) {
            api.setStatus(p.status, key, "#c7d0d9");
            assert.equal(p.statusText(), key, "errors and pending states never depend on color");
            assert.equal(p.status.optionalFeedback, false);
        }
        api.setStatus(p.status, "same text", "#58d68d", true);
        assert.equal(p.statusText(), "");
        api.setStatus(p.status, "same text", "#58d68d");
        assert.equal(p.statusText(), "same text", "reset metadata even for identical text and color");
    }
    let onEvent;
    api.startEventWatch = callback => {onEvent = callback;};
    p.startWatch();
    api.setStatus(p.status, "loaded", "#58d68d", true);
    onEvent({topic: "connection.error"});
    assert.equal(p.statusText(), "stale_state", "a watch failure resets prior optional feedback");
    api.dashboard(p.status, p);
    queued.shift().success({data: {pages: []}});
    assert.equal(p.statusText(), "no_dashboard_pages", "missing configuration remains visible");
    api.dashboard(p.status, p);
    queued.shift().failure("offline");
    assert.equal(p.statusText(), "stale_state", "fetch failures remain visible");
    const qml = fs.readFileSync(path.join(root, "device_qml/HomeAssistant.qml"), "utf8");
    assert.match(qml.slice(qml.lastIndexOf("id: status")), /text: statusText\(\)/);
    assert.match(qml, /text: selectedItem \? feedbackText\(selectedItem\) : statusText\(\)/,
        "the line under the notification list follows the switch like the header");
    for (const name of ["HomeAssistant.qml", "Alarm.qml"]) {
        assert.doesNotMatch(fs.readFileSync(path.join(root, "device_qml", name), "utf8"),
            /status\.(?:text|color)\s*=/, "all status writes reset the optional marker");
    }
}

{
    const {api, owner, requests} = runtime();
    const timer = () => ({running: false, restart() {this.running = true;}, stop() {this.running = false;}});
    Object.assign(owner, {touchToneEnabled: true, applyingTouchTone: false,
        touchToneRetry: timer(), touchToneReportDeadline: timer(),
        setTouchTone(value) { this.touchToneEnabled = value; }});
    api.watchTouchTone(owner);
    api.watchTouchTone(owner);
    assert.equal(requests.length, 1, "one sleeping GUI connection, not polling");
    assert.match(requests[0].url, /next\?enabled=1&session=[0-9a-f]{32}&revision=1$/);
    const command = {ok: true, id: "a".repeat(32), enabled: false, expires: Date.now() + 5000};
    requests[0].finish(200, command);
    assert.equal(owner.touchToneEnabled, false);
    assert.match(requests[1].url, /enabled=0&session=[0-9a-f]{32}&revision=2&completed=a{32}$/);
    owner.touchToneEnabled = true;
    api.reportTouchTone(owner);
    assert.equal(JSON.parse(requests[2].body).enabled, true);
    assert.equal(JSON.parse(requests[2].body).revision, 3);
    owner.touchToneEnabled = false;
    api.reportTouchTone(owner);
    assert.equal(requests.length, 3, "coalesce changes during a report");
    requests[2].finish(200, {ok: true});
    assert.equal(JSON.parse(requests[3].body).enabled, false);
    assert.equal(JSON.parse(requests[3].body).revision, 4);
    requests[3].finish(200, {ok: true});
    requests[1].finish(200, {...command, enabled: true, expires: Date.now() - 1});
    assert.equal(owner.touchToneEnabled, false, "expired commands cannot change the original GUI");
    assert.equal(owner.touchToneRetry.running, true);
    api.watchTouchTone(owner);
    const pending = requests.at(-1), late = pending.onreadystatechange;
    owner.stopped = true;
    api.stopTouchTone(owner);
    assert.equal(pending.aborted, true);
    late();
    assert.equal(owner.touchToneRetry.running, false);
    api.watchTouchTone(owner);
    assert.equal(requests.at(-1), pending, "unloaded GUI cannot reconnect");
}

for (const data of [{ok: true}, {ok: true, id: "../bad", enabled: true, expires: Date.now() + 5000},
    {ok: true, id: "a".repeat(32), enabled: "true", expires: Date.now() + 5000}]) {
    const {api, owner, requests} = runtime();
    const timer = {restart() {}, stop() {}};
    Object.assign(owner, {touchToneEnabled: false, touchToneRetry: timer, touchToneReportDeadline: timer,
        setTouchTone() {throw new Error("invalid GUI command was applied");}});
    api.watchTouchTone(owner);
    requests[0].finish(200, data);
    assert.equal(requests.length, 1);
}

{
    const p = page("HomeAssistant.qml", {feedbackColorsEnabled: false, dashboardOnline: true,
        status: {text: "Action failed", color: "#ff6b6b"},
        pendingEntity: "", controlInFlight: false, controlFeedback: [],
        Api: {feedbackState: entry => entry.state}, I18n: {text: (_, key) => key}, uiLanguage: "en"});
    const item = {entity_id: "switch.light", available: true};
    assert.equal(p.statusColor(), "#c7d0d9", "header and notification status follow the preference");
    for (const state of ["action_error", "state_confirmed", "sending", "state_unconfirmed"]) {
        p.controlFeedback = [{entity_id: item.entity_id, state}];
        assert.equal(p.feedbackColor(item), "#c7d0d9");
        assert.equal(p.readingColor(item), "#c7d0d9");
        assert.equal(p.feedbackText(item), state, "texts and errors are never suppressed");
    }
    p.dashboardOnline = false;
    assert.equal(p.statusColor(), "#ff6b6b", "connection status retains its warning color");
    assert.equal(p.feedbackColor(item), "#f1c40f", "connection warning remains visible");
    assert.equal(p.feedbackText(item), "stale_state");
    p.dashboardOnline = true;
    p.feedbackColorsEnabled = true;
    p.controlFeedback[0].state = "action_error";
    assert.equal(p.feedbackColor(item), "#ff6b6b");
    p.controlFeedback[0].state = "state_confirmed";
    assert.equal(p.feedbackColor(item), "#58d68d");
}
{
    const p = page("Alarm.qml", {feedbackColorsEnabled: false, activeFeedbackCommand: "arm_home",
        alarmOnline: true, alarmRawState: "triggered", commandPending: false});
    assert.equal(p.modeFeedbackVisible("arm_home"), false);
    assert.equal(p.modeFeedbackColor("arm_home"), "transparent");
    assert.equal(p.feedbackColor(), "#ff6b6b", "real alarm state must not be hidden");
    p.feedbackColorsEnabled = true;
    assert.equal(p.modeFeedbackVisible("arm_home"), true);
}
{
    // The switch "Status messages" off: the Alarm page hides what only confirms
    // that things work and keeps what the user has to act on. The state box
    // above the line still names a running command and the alarm state.
    const {api} = runtime();
    const noop = () => {};
    const p = page("Alarm.qml", {Api: api, I18n: {text: (_, key) => key}, uiLanguage: "en",
        feedbackColorsEnabled: false, status: {}, alarmState: {}, activeSince: {},
        alarmOnline: true, alarmConfigured: true, alarmRawState: "disarmed", alarmCommands: ["arm_home"],
        alarmCommandDetails: [], selectedCommand: "arm_home", commandPending: false, commandInFlight: false,
        commandAwaitedState: "", commandFeedback: "", commandFeedbackColor: "", activeFeedbackCommand: "",
        runtimeGeneration: 0, statusGeneration: 0, pinCode: "", bypassOffered: false,
        modeFeedbackTimer: {restart: noop}, delayedStatusRefresh: {restart: noop, stop: noop}});
    p.page = p;
    const reads = [];
    api.getJsonShared = (url, success, failure) => reads.push({success, failure});
    for (const key of ["checking", "sending", "ready_to_arm"]) {
        p.setCommandFeedback(key, "arm_home", "#58d68d");
        assert.notEqual(p.status.text, "", key);
        assert.equal(p.statusText(), "", key + " is routine and hidden with the switch off");
        p.feedbackColorsEnabled = true;
        assert.equal(p.statusText(), p.status.text, key + " shows again with the switch on");
        p.feedbackColorsEnabled = false;
    }
    for (const key of ["not_ready_to_arm", "pin_required", "invalid_code", "alarm_command_error", "bypass_open_sensors"]) {
        p.setCommandFeedback(key, "arm_home", "#ff6b6b");
        assert.equal(p.statusText(), p.status.text, key + " stays visible");
        assert.notEqual(p.statusText(), "");
    }
    for (const pending of [false, true]) {
        p.commandPending = p.commandInFlight = pending;
        api.status(p.status, p, p.alarmState, p.activeSince);
        reads.pop().success({alarm: {state: "disarmed", commands: ["arm_home"]}});
        assert.notEqual(p.status.text, "");
        assert.equal(p.statusText(), "", "a plain connected or sending line is routine");
        if (pending) assert.equal(p.feedbackTitle(), "sending", "the state box keeps naming the running command");
    }
    p.commandPending = p.commandInFlight = false;
    api.status(p.status, p, p.alarmState, p.activeSince);
    reads.pop().failure("API error: 503");
    assert.equal(p.statusText(), "status_error (503)", "a failed read stays visible");
    p.alarmOnline = true;
    p.alarmConfigured = false;
    p.alarmCommands = ["arm_home"];
    p.executeCommand("arm_home", false);
    assert.equal(p.statusText(), "alarm_not_configured");
    const source = fs.readFileSync(path.join(root, "device_qml/Alarm.qml"), "utf8");
    assert.match(source.slice(source.lastIndexOf("id: status")), /text: statusText\(\)/);
    const texts = vm.createContext({});
    vm.runInContext(fs.readFileSync(path.join(jsRoot, "c300x_i18n.js"), "utf8").replace(/^\.pragma library\s*/, ""), texts);
    assert.deepEqual(["de", "en", "it", "fr", "es"].map(language => texts.text(language, "ha_feedback_colors")),
        ["Statusmeldungen", "Status messages", "Messaggi di stato", "Messages d'état", "Mensajes de estado"]);
}
{
    const qml = fs.readFileSync(path.join(root, "device_qml/Alarm.qml"), "utf8");
    const color = qml.match(/color: (feedbackColorsEnabled \|\| !alarmOnline[^\n]+)/)[1];
    const values = vm.createContext({feedbackColorsEnabled: false, alarmOnline: true,
        status: {text: "Alarm command failed", color: "#ff6b6b"}});
    assert.equal(vm.runInContext(color, values), "#c7d0d9");
    assert.equal(values.status.text, "Alarm command failed");
    values.alarmOnline = false;
    assert.equal(vm.runInContext(color, values), "#ff6b6b");
    values.alarmOnline = true;
    values.feedbackColorsEnabled = true;
    assert.equal(vm.runInContext(color, values), "#ff6b6b");
}

function alarmPage(api, values) {
    const noop = () => {};
    const p = page("Alarm.qml", Object.assign({Api: api, I18n: {text: (_, key) => key}, uiLanguage: "en",
        feedbackColorsEnabled: false, status: {held: false}, alarmState: {}, activeSince: {},
        alarmOnline: true, alarmConfigured: true, alarmRawState: "disarmed", alarmCommands: ["arm_home"],
        alarmCommandDetails: [], selectedCommand: "arm_home", commandPending: false, commandInFlight: false,
        commandAwaitedState: "", commandFeedback: "", commandFeedbackColor: "", activeFeedbackCommand: "",
        runtimeGeneration: 0, statusGeneration: 0, pinCode: "", bypassOffered: false, lastStatusRefreshMs: 0,
        quickActionPending: false, quickActionGeneration: 0,
        modeFeedbackTimer: {restart: noop}, delayedStatusRefresh: {restart: noop, stop: noop}}, values || {}));
    p.page = p;
    return p;
}

{
    // A status the user has to read is not replaced by the routine line of
    // the next status read. It holds until its timer on the page releases it
    // after 30 seconds, whatever the station clock does meanwhile (it is set
    // by NTP after boot); a new command, another error or a failed read
    // replace it at once.
    const {api} = runtime();
    let now = 1000000;
    api.clock = () => now;
    vm.runInContext("Date.now = function() { return clock(); }", api);
    const p = alarmPage(api);
    const reads = [];
    api.getJsonShared = (url, success, failure) => reads.push({success, failure});
    const connected = () => {
        api.status(p.status, p, p.alarmState, p.activeSince);
        reads.pop().success({alarm: {state: "disarmed", commands: ["arm_home"]}});
    };
    for (const key of ["alarm_command_error", "pin_required", "not_ready_to_arm"]) {
        p.setCommandFeedback(key, "arm_home", "#ff6b6b");
        const shown = p.status.text;
        connected();
        assert.equal(p.statusText(), shown, key + " survives the next status read");
        for (const step of [29000, 86400000, -172800000]) {
            now += step;
            connected();
            assert.equal(p.statusText(), shown, key + " is still held when the clock moves by " + step);
        }
        assert.equal(p.status.held, true);
        p.status.held = false;
        connected();
        assert.equal(p.status.text, "ha_connected", key + " gives way after 30 seconds");
        assert.equal(p.statusText(), "", "and the routine line is hidden with the switch off");
    }
    api.setStatus(p.status, "action_error", "#ff6b6b");
    connected();
    assert.equal(p.statusText(), "action_error", "the quick-action error is held the same way");
    p.setCommandFeedback("sending", "arm_home", "#f1c40f");
    assert.equal(p.status.text, "sending: " + p.commandLabel("arm_home"), "a new command replaces a held error at once");
    p.commandPending = false;
    connected();
    assert.equal(p.status.text, "ha_connected", "and nothing is held after it");
    p.setCommandFeedback("alarm_command_error", "arm_home", "#ff6b6b");
    p.setCommandFeedback("pin_required", "arm_home", "#f1c40f");
    assert.match(p.status.text, /^pin_required/, "a newer prompt replaces the error");
    api.status(p.status, p, p.alarmState, p.activeSince);
    reads.pop().failure("API error: 503");
    assert.equal(p.statusText(), "status_error (503)", "a failed read replaces a held status");
    p.alarmOnline = true;
    connected();
    assert.equal(p.status.text, "ha_connected", "and is itself not held once Home Assistant answers again");
    api.setStatus(p.status, "", "#ff6b6b");
    assert.equal(p.status.held, false, "an empty line holds nothing");
    const alarm = fs.readFileSync(path.join(root, "device_qml/Alarm.qml"), "utf8");
    assert.match(alarm, /function aboutToShow\(\) \{[^}]*status\.held = false/, "opening the page starts fresh");
    assert.ok(alarm.includes("Timer { interval: 30000; running: status.held; onTriggered: status.held = false }"));
    assert.ok(!/heldUntil|Date\.now\(\) \+ 30000/.test(alarm + api.setStatus.toString()), "no wall clock in the hold");
}

{
    // The Home Assistant page has the same rule for its header line.
    const {api} = runtime();
    let now = 1000000;
    api.clock = () => now;
    vm.runInContext("Date.now = function() { return clock(); }", api);
    const p = page("HomeAssistant.qml", {Api: api, I18n: {text: (_, key) => key}, uiLanguage: "en",
        feedbackColorsEnabled: true, status: {held: false}, selectedItem: null,
        runtimeGeneration: 0, dashboardLoading: false, dashboardRefreshAgain: false,
        currentPageIndex: 0, pageCount: 1, dashboardPages: [{items: []}]});
    p.page = p;
    const queued = [];
    api.getJson = (url, success, failure) => queued.push({success, failure});
    const loaded = () => { api.dashboard(p.status, p); queued.shift().success({data: {pages: [{items: []}]}}); };
    api.setStatus(p.status, "action_error", "#ff6b6b");
    loaded();
    assert.equal(p.statusText(), "action_error", "an action error survives the next board read");
    now += 31000;
    loaded();
    assert.equal(p.statusText(), "action_error", "the clock alone releases nothing");
    p.status.held = false;
    loaded();
    assert.equal(p.statusText(), "board_loaded");
    api.dashboard(p.status, p);
    queued.shift().failure("offline");
    assert.equal(p.statusText(), "stale_state");
    loaded();
    assert.equal(p.statusText(), "board_loaded", "the offline line goes as soon as a read works again");
    const qml = fs.readFileSync(path.join(root, "device_qml/HomeAssistant.qml"), "utf8");
    assert.match(qml, /uiText\("stale_state"\), "#f1c40f", false, true\)/, "a lost event stream is a read result too");
    assert.match(qml, /function aboutToShow\(\) \{[^}]*status\.held = false/);
    assert.ok(qml.includes("Timer { interval: 30000; running: status.held; onTriggered: status.held = false }"));
}

{
    // The quick action on the Alarm page with "Status messages" off: a
    // success is routine and hidden, a failure stays visible.
    const {api} = runtime();
    const p = alarmPage(api);
    const sent = [], reads = [];
    api.getJson = (url, success, failure) => sent.push({url, success, failure});
    api.getJsonShared = (url, success, failure) => reads.push({success, failure});
    const item = {entity_id: "switch.gate", domain: "switch", kind: "switch"};
    api.dashboardAction(item, p.status, p, false);
    assert.match(sent[0].url, /^\/homeassistant\?domain=switch&service=toggle&entities=switch\.gate$/);
    assert.equal(p.quickActionPending, true);
    api.dashboardAction(item, p.status, p, false);
    assert.equal(sent.length, 1, "one quick action at a time");
    sent.shift().success({ok: true});
    assert.equal(p.status.text, "action_sent");
    assert.equal(p.statusText(), "", "ok is hidden with the switch off");
    assert.equal(reads.length, 1, "and the alarm status is read again");
    p.feedbackColorsEnabled = true;
    assert.equal(p.statusText(), "action_sent", "and shown with the switch on");
    p.feedbackColorsEnabled = false;
    api.dashboardAction(item, p.status, p, false);
    sent.shift().success({ok: false});
    assert.equal(p.statusText(), "action_error", "a refused action is visible");
    assert.equal(reads.length, 1, "without another status read");
    api.dashboardAction(item, p.status, p, false);
    sent.shift().failure("API error: 503");
    assert.equal(p.statusText(), "status_error (503)", "a failed request is visible");
    assert.equal(p.quickActionPending, false);
    api.dashboardAction({domain: "switch"}, p.status, p, false);
    assert.equal(p.statusText(), "invalid_action");
    assert.equal(sent.length, 0);
}

{
    // Alarm commands report through the page, which always has
    // setCommandFeedback; there is no second way to write the line.
    const source = fs.readFileSync(path.join(jsRoot, "c300x_ha.js"), "utf8");
    assert.doesNotMatch(source, /if \(pageItem\.setCommandFeedback\) \{/);
    const {api} = runtime();
    const p = alarmPage(api, {alarmCommandDetails: [{command: "arm_home", ready: false, blocking_sensor_count: 1}]});
    const sent = [];
    api.getJson = (url, success, failure) => sent.push({url, success, failure});
    api.alarmCommand("arm_home", "", p.status, p, p.alarmState, p.activeSince, false);
    assert.equal(sent.length, 0, "a blocked mode is not sent");
    assert.match(p.statusText(), /^not_ready_to_arm/);
    p.alarmCommandDetails = [{command: "arm_home", ready: true}];
    api.alarmCheck("arm_home", p.status, p);
    sent.shift().success({ok: true, ready: true});
    assert.match(p.status.text, /^ready_to_arm/);
    assert.equal(p.statusText(), "", "ready is routine");
    api.alarmCheck("arm_home", p.status, p);
    sent.shift().success({ok: true, ready: false, blocking_sensor_count: 1});
    assert.match(p.statusText(), /^not_ready_to_arm/);
}
console.log("display preferences: persistence protocol, lifecycle and feedback isolation passed");
