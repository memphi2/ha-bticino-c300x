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
Api.startEventWatch = () => {};
const I18n = library("c300x_i18n.js");
const qml = fs.readFileSync(path.join(root, "device_qml/HomeAssistant.qml"), "utf8");
const methods = [...qml.matchAll(/^    function [\s\S]*?^    }/gm)].map(m => m[0]).join("\n");
const p = vm.createContext({Api, I18n, Math, uiLanguage: "en", runtimeGeneration: 0,
    dashboardLoading: false, dashboardOnline: false, dashboardRefreshAgain: false,
    interactionActive: false, listScrolling: false, controlInFlight: false, pendingEntity: "", pageActive: true,
    commandGeneration: 0, controlFeedback: [],
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
assert.match(p.itemDetail({kind: "switch", state: false, controls: [
    {command: "brightness", kind: "number", value: 50, unit: "%"},
]}), /^Off/);
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
assert.equal(p.feedbackKey(p.selectedItem), "state_confirmed");

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
const cachedItems = p.items;
const cachedSelection = p.selectedItem;
queue.shift().error("offline");
assert.equal(p.items, cachedItems, "offline keeps the last snapshot");
assert.equal(p.selectedItem, cachedSelection, "offline keeps navigation and detail state");
assert.equal(p.feedbackText(p.selectedItem), "Offline - last known state");
p.adjustControl(p.selectedItem, p.selectedItem.controls[0], 1);
assert.equal(queue.length, 0, "offline controls cannot send commands");
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

const light = {domain: "c300x", entity_id: "light.room", kind: "switch", state: true,
    available: true, details: {type: "light", value: "50", unit: "%", state_label: "On"},
    controls: [{command: "color", kind: "choice", value: "red", options: ["red", "green"]},
        {command: "hue", kind: "number"}, {command: "saturation", kind: "number"}]};
const normalized = Api.dashboardMixedItems([light])[0];
assert.equal(normalized.details.value, "50");
assert.deepEqual(Array.from(Api.dashboardDetailControls(normalized), c => c.command), ["color"]);
assert.equal(Api.dashboardDetailControls({controls: [{command: "hue"}]}).length, 1, "old snapshots retain legacy controls");
const cover = {details: {type: "cover", activity: "opening"}, controls: [
    {command: "close_cover", kind: "button"}, {command: "position", kind: "number"},
    {command: "stop_cover", kind: "button"}, {command: "open_cover", kind: "button"},
]};
assert.deepEqual(Array.from(Api.dashboardCoverControls(cover), c => c.command), ["open_cover", "stop_cover", "close_cover"]);
assert.deepEqual(Array.from(Api.dashboardDetailControls(cover), c => c.command), ["position"]);
assert.equal(Api.dashboardDetailControls(null).length, 0);
assert.equal(Api.dashboardCoverControls(null).length, 0);
assert.equal(Api.dashboardMixedItems([{...light, available: false}])[0].available, false);
const sensor = Api.dashboardMixedItems([{domain: "c300x", entity_id: "sensor.room", kind: "entity", available: false, details: {type: "sensor", value: "22"}}])[0];
assert.equal(sensor.available, false, "read-only availability is not conditional on controls");
assert.equal(sensor.details.value, "22");
p.dashboardOnline = true;
assert.equal(p.detailValue(normalized), "50 %");
assert.equal(p.detailState(cover), "Opening");
assert.equal(p.detailState({details: {type: "climate", activity: "idle"}}), "Idle");
assert.equal(p.detailValue(sensor), "?");
p.dashboardOnline = false;
assert.equal(p.detailValue(normalized), "50 %", "last value remains readable, marked stale separately");
assert.equal(p.detailState(normalized), "Offline - last known state");
p.dashboardOnline = true;
assert.equal(p.optionLabel({command: "color"}, "red"), "Red");
assert.equal(p.optionLabel({command: "fan_mode"}, "custom mode"), "custom mode");
assert.equal(p.optionLabel({command: "preset_mode"}, "auto"), "auto", "custom preset names remain unchanged");
for (const lang of ["de", "fr", "it"]) {
    assert.deepEqual(Object.keys(I18n.DETAIL_LABELS[lang]).sort(), Object.keys(I18n.DETAIL_LABELS.en).sort());
    for (const key of Object.keys(I18n.DETAIL_LABELS.en)) assert.notEqual(I18n.text(lang, key), key);
}
Api.dashboardControl(normalized, normalized.controls[0], "green", p.status, p);
assert.equal(queue.length, 1, "a swatch sends one atomic color command");
assert.match(queue.shift().url, /light.room%3Acolor&option=green$/);
p.aboutToHide();
assert.equal((qml.match(/\bTimer\s*\{/g) || []).length, 2, "entity details introduce no periodic timers");
assert.match(qml, /anchors.top: entitySummary.bottom/);
console.log("Entity detail controls and translations passed");

p.dashboardOnline = true;
p.pageActive = true;
Api.dashboard(p.status, p);
queue.shift().success(payload("feedback-1"));
const unchangedItems = p.items;
const unchangedItem = p.items[0];
const unchangedSelection = p.selectedItem;
Api.dashboard(p.status, p);
queue.shift().success({...payload("feedback-2"), notifications: [{id: "notice", title: "Notice"}]});
assert.equal(p.items, unchangedItems, "notification updates preserve the entity model");
assert.equal(p.items[0], unchangedItem);
assert.equal(p.selectedItem, unchangedSelection);

p.adjustControl(p.selectedItem, p.selectedItem.controls[0], 1);
assert.equal(p.feedbackKey(p.selectedItem), "sending");
queue.shift().success({ok: true});
queue.shift().success({not_modified: true});
assert.equal(p.feedbackKey(p.selectedItem), "action_sent", "ACK is not a state confirmation");
assert.equal(p.pendingEntity, "", "accepted commands cannot block a later cover stop");
item.controls[0].value += 0.5;
Api.dashboard(p.status, p);
queue.shift().success(payload("feedback-3"));
assert.equal(p.feedbackKey(p.selectedItem), "state_confirmed");

p.adjustControl(p.selectedItem, p.selectedItem.controls[0], 1);
queue.shift().success({ok: false});
assert.equal(p.feedbackKey(p.selectedItem), "action_error");
Api.dashboard(p.status, p);
queue.shift().success({not_modified: true});
assert.equal(p.feedbackKey(p.selectedItem), "action_error", "refresh cannot hide a failed command");

p.adjustControl(p.selectedItem, p.selectedItem.controls[0], 1);
const timedOut = queue.shift();
p.expirePendingControl();
assert.equal(p.feedbackKey(p.selectedItem), "state_unconfirmed");
assert.equal(p.controlInFlight, false);
assert.equal(queue.length, 1, "timeout only reads state; it never resends a command");
timedOut.success({ok: true});
assert.equal(p.feedbackKey(p.selectedItem), "state_unconfirmed", "late ACK cannot mask a timeout");
queue.shift().success({not_modified: true});
p.adjustControl(p.selectedItem, p.selectedItem.controls[0], -1);
queue.shift().error("disconnected");
assert.equal(p.feedbackKey(p.selectedItem), "state_unconfirmed");
assert.equal(queue.length, 0, "ambiguous transport failure is not retried");
Api.dashboardChoiceAction({entity_id: "select.room", domain: "c300x", kind: "choice"}, "a & b", p.status, p);
assert.match(queue[0].url, /entities=select.room&option=a%20%26%20b$/);
queue.shift().success({ok: true});
queue.shift().success({not_modified: true});

// Delegates keep their data objects because an unchanged snapshot is skipped
// entirely. Reusing unchanged elements of a *changed* list cannot add to that:
// items is a QML variant property, and assigning to one converts the whole
// structure into a QVariant, so element identity is lost on the next read -
// the same conversion that cannot store a JavaScript null.
const model = {items: [{entity_id: "one", state: 1}, {entity_id: "two", state: 2}]};
const unchanged = model.items;
Api.assignDashboardValue(model, "items", [{entity_id: "one", state: 1}, {entity_id: "two", state: 2}]);
assert.equal(model.items, unchanged, "an unchanged list keeps its data objects");
Api.assignDashboardValue(model, "items", [{entity_id: "one", state: 3}, {entity_id: "two", state: 2}]);
assert.notEqual(model.items, unchanged, "a changed list is taken as a whole");
assert.equal(model.items[0].state, 3);
for (let i = 0; i < 100; i++) Api.setDashboardFeedback(p, "button." + i, "action_sent");
assert.equal(p.controlFeedback.length, 32, "feedback storage is bounded");

const allLight = {...light, controls: [{command: "toggle", kind: "button"},
    {command: "brightness", kind: "number"}, {command: "color_temp_kelvin", kind: "number"},
    ...light.controls]};
assert.deepEqual(Array.from(Api.dashboardDetailSections(allLight)), ["white_mode", "color_mode"]);
assert.deepEqual(Array.from(Api.dashboardVisibleControls(allLight, "white_mode"), c => c.command), ["brightness", "color_temp_kelvin"]);
assert.deepEqual(Array.from(Api.dashboardVisibleControls(allLight, "color_mode"), c => c.command), ["brightness", "color"]);
const climate = {details: {type: "climate"}, controls: [
    {command: "temperature"}, {command: "hvac_mode"}, {command: "fan_mode"}, {command: "preset_mode"},
]};
assert.deepEqual(Array.from(Api.dashboardVisibleControls(climate, ""), c => c.command), ["temperature", "hvac_mode"]);
assert.deepEqual(Array.from(Api.dashboardVisibleControls(climate, "more_controls"), c => c.command), ["fan_mode", "preset_mode"]);
assert.deepEqual(Array.from(Api.dashboardVisibleControls(null, "")), []);
const brightnessExpected = Api.dashboardExpectation(light, {command: "brightness", kind: "number"}, "50");
const retainedBrightness = {...light, controls: [{command: "brightness", value: 50}]};
assert.equal(Api.dashboardExpectationMatches({...retainedBrightness, state: false}, brightnessExpected), false, "retained attributes on an off light do not confirm turn-on");
assert.equal(Api.dashboardExpectationMatches(retainedBrightness, brightnessExpected), true);
assert.equal(Api.dashboardExpectationMatches({details: {activity: "open", position: 30}}, {command: "open_cover"}), false, "partly open is not fully open");
assert.equal(Api.dashboardExpectationMatches({details: {activity: "opening", position: 30}}, {command: "open_cover"}), true);
assert.match(qml, /model: items.length/);
assert.match(qml, /model: detailControls.length/);
assert.match(qml, /checkable: false\s+checked: tileItem.state/, "legacy switch must not overwrite its HA-state binding on press");
console.log("Feedback, bounded state and incremental display updates passed");

// A refresh reassigns the whole item list, so it must not land inside a flick.
// The item object is shared with the payload, so the revision is the only
// observable that tells an applied snapshot from a deferred one.
p.dashboardOnline = true;
p.pageActive = true;
p.pendingEntity = "";
p.controlInFlight = false;
p.dashboardRefreshAgain = false;
p.listScrolling = false;
Api.dashboard(p.status, p);
queue.shift().success(payload("scroll-1"));
while (queue.length > 0) queue.shift().success({not_modified: true});
assert.equal(Api.dashboardRevision, "scroll-1");

p.listScrolling = true;
Api.dashboard(p.status, p);
assert.equal(queue.length, 0, "no fetches while the list scrolls");
assert.equal(p.dashboardRefreshAgain, true, "a scrolled-over refresh is remembered");
p.replayDeferredRefresh();
assert.equal(queue.length, 0, "scrolling still blocks the replay");
p.listScrolling = false;
p.replayDeferredRefresh();
assert.equal(queue.length, 1, "the deferred refresh runs once the flick settles");
queue.shift().success(payload("scroll-2"));
assert.equal(Api.dashboardRevision, "scroll-2", "the replayed refresh still applies state");

// A response that arrives mid-flick waits instead of re-laying out the tiles.
Api.dashboard(p.status, p);
const inFlight = queue.shift();
p.listScrolling = true;
inFlight.success(payload("scroll-3"));
assert.equal(Api.dashboardRevision, "scroll-2", "an in-flight payload cannot re-layout a moving list");
assert.equal(p.dashboardRefreshAgain, true);
assert.equal(p.dashboardLoading, false, "a deferred payload releases the single-flight lock");
p.listScrolling = false;
p.replayDeferredRefresh();
assert.equal(queue.length, 1);
queue.shift().success(payload("scroll-4"));
assert.equal(Api.dashboardRevision, "scroll-4", "the settled list catches up to HA");

p.replayDeferredRefresh();
assert.equal(queue.length, 0, "a settled list without a pending refresh stays quiet");
assert.match(qml, /property bool listScrolling: scroll.moving \|\| details.moving/);
assert.match(qml, /onListScrollingChanged: replayDeferredRefresh\(\)/);
console.log("Scroll-aware dashboard refresh passed");

// Snapshots are compared structurally: an equal payload must not be reassigned
// (that is what keeps tile identity), and a difference at any depth must be seen.
assert.equal(Api.sameDashboardValue(1, 1), true);
assert.equal(Api.sameDashboardValue(1, "1"), false, "no type coercion");
assert.equal(Api.sameDashboardValue("ab", "ab"), true, "strings are values, not lists");
assert.equal(Api.sameDashboardValue("ab", ["a", "b"]), false);
assert.equal(Api.sameDashboardValue(null, null), true);
assert.equal(Api.sameDashboardValue(null, {}), false);
assert.equal(Api.sameDashboardValue({}, null), false);
assert.equal(Api.sameDashboardValue([], {}), false, "a list never equals an object");
assert.equal(Api.sameDashboardValue([1, 2], [1, 2]), true);
assert.equal(Api.sameDashboardValue([1, 2], [1, 2, 3]), false);
assert.equal(Api.sameDashboardValue({a: 1}, {a: 1, b: 2}), false, "an added key is a change");
assert.equal(Api.sameDashboardValue({a: 1, b: 2}, {a: 1}), false, "a removed key is a change");
assert.equal(
    Api.sameDashboardValue(
        {items: [{controls: [{command: "brightness", value: 50}]}]},
        {items: [{controls: [{command: "brightness", value: 50}]}]},
    ),
    true,
);
assert.equal(
    Api.sameDashboardValue(
        {items: [{controls: [{command: "brightness", value: 50}]}]},
        {items: [{controls: [{command: "brightness", value: 51}]}]},
    ),
    false,
    "a difference deep inside a control is detected",
);

const dashboardSource = fs.readFileSync(path.join(root, "device_qml/js/c300x_ha.js"), "utf8");
const assignBody = dashboardSource.slice(
    dashboardSource.indexOf("function sameDashboardValue"),
    dashboardSource.indexOf("function loadDashboardPage"),
);
assert.equal(assignBody.includes("JSON.stringify("), false, "no snapshot is serialised to compare it");
console.log("Structural snapshot comparison passed");
