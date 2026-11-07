const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = path.resolve(__dirname, "../..");
function library(name) {
    const ctx = vm.createContext({Date, JSON, Math, XMLHttpRequest() {}});
    vm.runInContext(fs.readFileSync(path.join(root, "device_qml/js", name), "utf8")
        .replace(/^\.pragma library\s*/, ""), ctx);
    return ctx;
}
const Api = library("c300x_ha.js");
const I18n = library("c300x_i18n.js");
const qml = fs.readFileSync(path.join(root, "device_qml/HomeAssistant.qml"), "utf8");
const methods = [...qml.matchAll(/^    function [\s\S]*?^    }/gm)].map(m => m[0]).join("\n");
const p = vm.createContext({Api, I18n, Math, uiLanguage: "en", runtimeGeneration: 0,
    dashboardLoading: false, dashboardOnline: false, dashboardRefreshAgain: false,
    interactionActive: false, controlInFlight: false, pendingEntity: "", pageActive: true,
    currentPageIndex: 0, dashboardPages: [], items: [], selectedItem: null, status: {}});
p.page = p;
vm.runInContext(methods, p);
const queue = [];
Api.getJson = (url, success, error) => queue.push({url, success, error});
const item = {domain: "c300x", entity_id: "climate.room", kind: "entity", available: true,
    controls: [{command: "temperature", kind: "number", value: 20, min: 5, max: 30, step: 0.5, unit: "C"}]};
function payload(revision) { return {revision, data: {pages: [{items: [item]}]}}; }
Api.dashboard(p.status, p);
Api.dashboard(p.status, p);
assert.equal(queue.length, 1, "coalesce concurrent refreshes");
queue.shift().success(payload("one"));
assert.equal(queue.length, 1, "one trailing refresh");
queue.shift().success({not_modified: true});
assert.equal(p.dashboardOnline, true);
p.selectedItem = p.items[0];
Api.dashboard(p.status, p);
const beforeCommand = queue.shift();
p.adjustControl(p.selectedItem, p.selectedItem.controls[0], 1);
assert.match(queue[0].url, /climate.room%3Atemperature&option=20.5$/);
p.adjustControl(p.selectedItem, p.selectedItem.controls[0], 1);
assert.equal(queue.length, 1, "reject duplicate commands");
queue.shift().success({ok: true});
beforeCommand.success(payload("one"));
assert.equal(p.pendingEntity, "climate.room", "old response cannot finish a new command");
assert.equal(queue.length, 1);
item.controls[0].value = 20.5;
queue.shift().success(payload("two"));
assert.equal(p.pendingEntity, "");
assert.equal(p.selectedItem.controls[0].value, 20.5, "detail follows confirmed HA state");

Api.dashboard(p.status, p);
p.interactionActive = true;
queue.shift().success(payload("old"));
assert.equal(p.dashboardRefreshAgain, true, "incoming payload cannot destroy dragged slider");
assert.equal(Api.dashboardRevision, "two");
Api.dashboard(p.status, p);
assert.equal(queue.length, 0, "no fetches while dragging");
p.interactionActive = false;
p.adjustControl(p.selectedItem, p.selectedItem.controls[0], -1);
queue.shift().success({ok: true});
queue.shift().success(payload("three"));
queue.shift().success({not_modified: true});
assert.equal(p.pendingEntity, "");

p.adjustControl(p.selectedItem, p.selectedItem.controls[0], 1);
const stale = queue.shift();
p.aboutToHide();
stale.success({ok: true});
assert.equal(queue.length, 0, "hidden page cannot restart requests");
assert.equal(p.dashboardOnline, false);
Api.dashboard(p.status, p);
queue.shift().error("offline");
assert.equal(p.watchFailed, true);
assert.equal(Api.dashboardRevision, "");
Api.dashboard(p.status, p);
assert.equal(queue[0].url, "/homeassistant", "offline recovery needs a full snapshot");
queue.shift().success(payload("four"));
assert.equal(p.dashboardOnline, true);

const sliderHandlers = qml.slice(qml.indexOf("id: sliderMouse"), qml.indexOf("id: optionGrid"));
assert.match(sliderHandlers, /onPositionChanged: if \(pressed\) updatePreview\(mouse.x\)/);
assert.match(sliderHandlers, /onReleased: \{[\s\S]*Api.dashboardControl/);
assert.equal(sliderHandlers.split("onReleased:")[0].includes("Api.dashboardControl"), false);
assert.match(qml, /contentWidth: width/);
assert.match(qml, /interactive: !interactionActive/);
console.log("Dashboard QML production controls passed");

Api.dashboard(p.status, p);
queue.shift().success({...payload("five"), notifications: [
    {id: "calendar", revision: 12, title: "Appointment", message: "At 10", actions: []},
]});
assert.equal(p.notifications.length, 1);
p.notificationsOpen = true;
p.notificationAction(p.notifications[0], null);
assert.match(queue[0].url, /entities=notification.calendar&option=/);
assert.equal(JSON.parse(decodeURIComponent(queue[0].url.split("&option=")[1])).revision, 12);
p.notificationAction(p.notifications[0], null);
assert.equal(queue.length, 1, "notification actions are single-flight too");
queue.shift().success({ok: true});
queue.shift().success(payload("six"));
assert.equal(p.notifications.length, 0);
assert.equal(p.notificationsOpen, false, "expiry/dismissal closes the empty details view");
