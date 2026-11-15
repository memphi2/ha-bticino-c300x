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
        errorKey: "", deadline: {
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
