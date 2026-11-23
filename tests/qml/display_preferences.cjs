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
    assert.match(qml, /text: selectedItem \? feedbackText\(selectedItem\) : status.text/);
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
console.log("display preferences: persistence protocol, lifecycle and feedback isolation passed");
