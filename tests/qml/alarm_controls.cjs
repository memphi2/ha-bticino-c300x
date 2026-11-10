const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = path.resolve(__dirname, "../..");

function library(name) {
    const context = vm.createContext({Date, JSON, Math, XMLHttpRequest() {}});
    vm.runInContext(fs.readFileSync(path.join(root, "device_qml/js", name), "utf8")
        .replace(/^\.pragma library\s*/, ""), context);
    return context;
}
const Api = library("c300x_ha.js");
const I18n = library("c300x_i18n.js");
const qml = fs.readFileSync(path.join(root, "device_qml/Alarm.qml"), "utf8");
const methods = [...qml.matchAll(/^    function [\s\S]*?^    }/gm)]
    .map(match => match[0]).join("\n");

function page() {
    const noop = () => {};
    const context = vm.createContext({
        Api, I18n, Date, Math, uiLanguage: "en", pinCode: "", pinRequested: false,
        alarmOnline: true, alarmConfigured: true, alarmRawState: "disarmed",
        alarmCommands: ["arm_home", "arm_away", "disarm"], alarmCommandDetails: [],
        alarmOpenSensors: [], alarmOpenSensorCount: 0, alarmDelayRemaining: 0,
        selectedCommand: "arm_home", selectedCommandReady: true,
        selectedCommandBlockedBySensors: false, selectedCommandStatus: "",
        bypassOffered: false, activeFeedbackCommand: "", commandFeedback: "",
        commandFeedbackColor: "", commandPending: false, commandInFlight: false,
        runtimeGeneration: 0, statusGeneration: 0, lastStatusRefreshMs: 0,
        alarmPageItem: null, pageActive: true, watchFailed: false,
        preventReturnToHomepage: false, status: {}, alarmState: {}, activeSince: {},
        modeFeedbackTimer: {restart: noop}, delayedStatusRefresh: {restart: noop, stop: noop},
    });
    context.page = context;
    vm.runInContext(methods, context);
    return context;
}

let pending = [];
Api.getJson = (url, success, error) => pending.push({url, success, error});
function state(p, raw = "disarmed") {
    Api.status(p.status, p, p.alarmState, p.activeSince);
    pending.pop().success({alarm: {state: raw, commands: p.alarmCommandDetails},
        preventReturnToHomepage: false, alarm_page_entity: null});
}
const p = page();
p.alarmCommandDetails = [
    {command: "arm_home", code_required: false},
    {command: "arm_away", code_required: true},
    {command: "disarm", code_required: true},
];
assert.equal(p.keypadVisible(), false);
p.selectCommand("arm_away");
assert.equal(p.keypadVisible(), true);
assert.equal(pending.length, 0);
p.appendDigit("1");
state(p);
assert.equal(p.selectedCommand, "arm_away", "unchanged status preserves chosen PIN mode");
assert.equal(p.pinCode, "1");
p.submitPin();
const command = pending.shift();
assert.match(command.url, /command=arm_away&code=1$/);
assert.equal(p.pinCode, "");
assert.equal(p.commandPending, true);
state(p);
assert.equal(p.commandPending, true, "status cannot unlock an in-flight command");
p.selectCommand("arm_home");
assert.equal(pending.length, 0, "no duplicate or competing command");
command.success({ok: true, state: "arming"});
assert.equal(p.commandPending, true, "wait for confirmed status, not just ACK");
state(p, "arming");
assert.equal(p.commandPending, false);
assert.equal(p.keypadVisible(), false);
state(p, "pending");
assert.equal(p.selectedCommand, "disarm");
assert.equal(p.keypadVisible(), true);
p.appendDigit("2");
p.pausePage();
assert.equal(p.pinCode, "");
assert.equal(p.keypadVisible(), false);
assert.equal(p.pageActive, false);

const q = page();
q.alarmCommandDetails = p.alarmCommandDetails;
q.selectCommand("arm_home");
assert.equal(pending.length, 1, "no-code mode executes directly");
const late = pending.shift();
q.pausePage();
late.success({ok: true});
assert.equal(q.commandPending, false, "late command callback ignored after hide");
q.alarmOnline = true;
q.pageActive = true;
Api.status(q.status, q, q.alarmState, q.activeSince);
const stale = pending.shift();
state(q, "armed_away");
stale.success({alarm: {state: "disarmed", commands: q.alarmCommandDetails}});
assert.equal(q.alarmRawState, "armed_away", "out-of-order status ignored");
Api.status(q.status, q, q.alarmState, q.activeSince);
pending.shift().error("offline");
assert.equal(q.alarmOnline, false);
assert.equal(q.watchFailed, true, "status failure schedules recovery even with a healthy event watch");
assert.equal(q.alarmState.text, "Offline");
// The status line is the only one that used to print the raw transport string,
// so a translated interface showed English technical text. The sentence is now
// localised and the transport code is kept, because it names the cause exactly.
assert.equal(q.status.text, I18n.text("en", "status_error"));
assert.notEqual(q.status.text, "offline", "no raw transport string reaches the display");
assert.equal(q.status.color, "#ff6b6b");
Api.status(q.status, q, q.alarmState, q.activeSince);
pending.shift().error("API error: 503");
assert.equal(q.status.text, I18n.text("en", "status_error") + " (503)");
for (const lang of ["de", "fr", "it"]) {
    assert.notEqual(I18n.text(lang, "status_error"), "status_error", lang);
    assert.notEqual(I18n.text(lang, "status_error"), I18n.text("en", "status_error"), lang);
}
q.selectCommand("arm_home");
assert.equal(pending.length, 0);
assert.equal(Api.alarmPageItem(null), null, "no implicit stair light action");
q.executeAlarmPageItem();
assert.equal(pending.length, 0);

q.alarmOnline = true;
q.alarmRawState = "disarmed";
q.alarmCommandDetails = p.alarmCommandDetails;
q.selectCommand("arm_away");
q.appendDigit("3");
q.alarmCommandDetails = [{command: "disarm", code_required: true}];
state(q);
assert.equal(q.pinCode, "", "changing available commands clears a partly entered PIN");
q.alarmPageItem = {domain: "c300x", entity_id: "switch.porch", kind: "switch"};
q.executeAlarmPageItem();
q.executeAlarmPageItem();
assert.equal(pending.length, 1, "quick action is also single-flight");
pending.shift().error("offline");
assert.equal(q.quickActionPending, false);

const events = library("c300x_ha.js");
let aborted = 0;
events.connections = [1, 2, 3].map(() => ({readyState: 1,
    onreadystatechange() { throw Error("cancelled callback ran"); },
    abort() { aborted++; this.onreadystatechange(); },
}));
events.stopDashboardRuntime();
assert.equal(aborted, 3);
assert.equal(events.connections.length, 0);

// The agent forwards each of these requests to Home Assistant and keeps one in
// flight, answering a second one with 503 display_command_pending. This
// library is the only producer, so the collision is removed by serialising
// here instead of reporting or retrying it.
function forwardLibrary() {
    const context = library("c300x_ha.js");
    const sent = [];
    context.XMLHttpRequest = function () {
        const xhr = this;
        sent.push(xhr);
        xhr.readyState = 1;
        xhr.status = 0;
        xhr.responseText = "";
        xhr.open = (method, url) => { xhr.url = url; };
        xhr.send = () => {};
        xhr.abort = () => { xhr.readyState = 4; xhr.onreadystatechange(); };
        xhr.finish = (status, body) => {
            xhr.readyState = 4;
            xhr.status = status;
            xhr.responseText = body;
            xhr.onreadystatechange();
        };
    };
    return [context, sent];
}

const [forward, sent] = forwardLibrary();
const seen = [];
forward.getJson("/ui/state", () => seen.push("state"), () => seen.push("state-error"));
forward.getJson("/homeassistant", () => seen.push("dashboard"), () => seen.push("dashboard-error"));
forward.getJson("/ui/alarm/command?command=disarm", () => seen.push("command"), null);
assert.equal(sent.length, 1, "only one request may hold the agent's display slot");
assert.match(sent[0].url, /\/ui\/state$/);
sent[0].finish(200, '{"ok":true}');
assert.equal(sent.length, 2, "the queued request starts once the slot is free");
assert.match(sent[1].url, /\/homeassistant$/);
sent[1].finish(200, '{"ok":true}');
assert.match(sent[2].url, /\/ui\/alarm\/command/);
sent[2].finish(200, '{"ok":true}');
assert.deepEqual(seen, ["state", "dashboard", "command"], "order is preserved");
assert.equal(forward.forwardActive, null);
assert.equal(forward.forwardQueue.length, 0);
assert.equal(forward.connections.length, 0, "no request is left registered");

// A failing request must hand the slot on, or the display would stop talking
// to the agent after the first error.
const [failing, failingSent] = forwardLibrary();
const errors = [];
failing.getJson("/ui/state", () => {}, error => errors.push(error));
failing.getJson("/homeassistant", () => errors.push("dashboard"), null);
failingSent[0].finish(503, "");
assert.deepEqual(errors, ["API error: 503"]);
assert.equal(failingSent.length, 2, "a refused request still releases the slot");
failingSent[1].finish(200, "{}");
assert.deepEqual(errors, ["API error: 503", "dashboard"]);

// Not even a throwing page callback may keep the slot.
const [throwing, throwingSent] = forwardLibrary();
let ran = false;
throwing.getJson("/ui/state", () => { throw Error("page bug"); }, () => { throw Error("handler bug"); });
throwing.getJson("/homeassistant", () => { ran = true; }, null);
assert.throws(() => throwingSent[0].finish(200, "{}"), /handler bug/);
assert.equal(throwingSent.length, 2, "the slot is released through finally");
throwingSent[1].finish(200, "{}");
assert.equal(ran, true);

// The queue is bounded, and an overflow is reported rather than dropped so a
// pressed button never goes silent.
const [bounded, boundedSent] = forwardLibrary();
const refused = [];
for (let i = 0; i < 1 + bounded.FORWARD_QUEUE_LIMIT; i++) {
    bounded.getJson("/ui/state?i=" + i, () => {}, error => refused.push(error));
}
assert.equal(bounded.forwardQueue.length, bounded.FORWARD_QUEUE_LIMIT);
assert.deepEqual(refused, []);
bounded.getJson("/ui/state?over", () => {}, error => refused.push(error));
assert.deepEqual(refused, ["queue full"]);
assert.equal(boundedSent.length, 1);

// Tearing the runtime down must not start what it is tearing down.
const [stopped, stoppedSent] = forwardLibrary();
stopped.getJson("/ui/state", () => {}, null);
stopped.getJson("/homeassistant", () => { throw Error("torn down request ran"); }, null);
stopped.stopDashboardRuntime();
assert.equal(stopped.forwardQueue.length, 0);
assert.equal(stopped.forwardActive, null);
assert.equal(stoppedSent.length, 1, "no queued request is started by the teardown");
assert.equal(stopped.connections.length, 0);
console.log("Alarm QML production controls passed");
