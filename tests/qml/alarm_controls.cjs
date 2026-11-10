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
console.log("Alarm QML production controls passed");
