const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = path.resolve(__dirname, "../..");
const jsRoot = process.env.C300X_DEVICE_JS_ROOT || path.join(root, "device_qml/js");
function library(name) {
    const ctx = vm.createContext({Date, JSON, Math, XMLHttpRequest() {}});
    vm.runInContext(fs.readFileSync(path.join(jsRoot, name), "utf8")
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
Api.getJsonShared = Api.getJson;
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
const offExpected = Api.dashboardExpectation(light, {command: "brightness", kind: "number"}, "0");
assert.equal(offExpected.power, false);
assert.equal(Api.dashboardExpectationMatches({...light, state: false, controls: [{command: "brightness", value: null}]}, offExpected), true,
    "brightness 0 turns the light off, and an off light has no brightness to compare");
assert.equal(Api.dashboardExpectationMatches({...light, controls: [{command: "brightness", value: 10}]}, offExpected), false,
    "a light that is still on does not confirm 0");
const fanOffExpected = Api.dashboardExpectation({entity_id: "fan.room", state: true}, {command: "percentage", kind: "number"}, "0");
assert.equal(Api.dashboardExpectationMatches({entity_id: "fan.room", available: true, state: false,
    controls: [{command: "percentage", value: null}]}, fanOffExpected), true, "speed 0 is confirmed by the fan being off");
assert.equal(Api.dashboardExpectationMatches({details: {activity: "open", position: 30}}, {command: "open_cover"}), false, "partly open is not fully open");
assert.equal(Api.dashboardExpectationMatches({details: {activity: "opening", position: 30}}, {command: "open_cover"}), true);
assert.match(qml, /model: items.length/);
assert.match(qml, /model: detailControls.length/);
assert.match(qml, /checkable: false\s+checked: tileItem.state/, "legacy switch must not overwrite its HA-state binding on press");
console.log("Feedback, bounded state and incremental display updates passed");

const dashboardSource = fs.readFileSync(path.join(root, "device_qml/js/c300x_ha.js"), "utf8");
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

// Only the request waits. A response already in flight is applied even while the
// list moves, so command bookkeeping is never stranded behind a long gesture: a
// deferred payload would leave pendingEntity set, keep every switch dimmed and
// let the expiry timer report a command that actually succeeded as unconfirmed.
Api.dashboard(p.status, p);
const inFlight = queue.shift();
p.listScrolling = true;
inFlight.success(payload("scroll-3"));
assert.equal(Api.dashboardRevision, "scroll-3", "an in-flight payload still lands");
assert.equal(p.dashboardOnline, true, "a mid-flick response still clears the offline state");
assert.equal(p.pendingEntity, "", "a mid-flick response still finishes the refresh");
while (queue.length > 0) queue.shift().success({not_modified: true});
p.listScrolling = false;

p.replayDeferredRefresh();
assert.equal(queue.length, 0, "a settled list without a pending refresh stays quiet");
assert.match(
    qml,
    /property bool listScrolling: scroll.moving \|\| details.moving \|\| notificationDetails.moving/,
    "every scrollable surface that a refresh re-lays out is covered",
);
assert.match(qml, /onListScrollingChanged: replayDeferredRefresh\(\)/);
const dashboardFetch = dashboardSource.slice(
    dashboardSource.indexOf("function dashboard("),
    dashboardSource.indexOf("function finishDashboardRefresh"),
);
assert.equal(
    dashboardFetch.split("listScrolling").length - 1,
    1,
    "listScrolling gates the request only, never the response",
);
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

const assignBody = dashboardSource.slice(
    dashboardSource.indexOf("function sameDashboardValue"),
    dashboardSource.indexOf("function loadDashboardPage"),
);
assert.equal(assignBody.includes("JSON.stringify("), false, "no snapshot is serialised to compare it");
console.log("Structural snapshot comparison passed");

// Nothing else ever removes a controlFeedback entry, so an entry is aged where
// it is read: first into the warning the user can act on, then away, so the
// tile shows its plain reading again.
let clock = 1700000000000;
const realDate = Api.Date;
Api.Date = {now: () => clock};
p.controlFeedback = [];
p.pendingEntity = "";
p.controlInFlight = false;
p.dashboardOnline = true;
const stuck = {entity_id: "light.hall", available: true};
Api.setDashboardFeedback(p, stuck.entity_id, "action_sent", {command: "toggle", value: true});
const stored = p.controlFeedback;
clock += 14999;
assert.equal(p.feedbackKey(stuck), "action_sent", "a command HA may still reflect is left alone");
clock += 1;
assert.equal(p.feedbackKey(stuck), "state_unconfirmed", "an unreflected command reads as a warning");
assert.equal(p.readingColor(stuck), "#f1c40f", "and the tile reading says so");
assert.equal(p.controlFeedback, stored, "ageing an entry costs no list reassignment");
clock += 59999 - 15000;
assert.equal(p.feedbackKey(stuck), "state_unconfirmed", "the warning stays long enough to read");
clock += 1;
assert.equal(p.feedbackKey(stuck), "", "a settled entry stops being reported");
assert.equal(p.readingColor(stuck), "#c7d0d9");

// A late confirmation still lands, and is stamped again so it reads as fresh.
p.controlFeedback = [];
Api.setDashboardFeedback(p, stuck.entity_id, "action_sent", {command: "toggle", value: true});
p.dashboardPages = [{items: [{entity_id: stuck.entity_id, state: true, available: true}]}];
clock += 20000;
Api.confirmDashboardFeedback(p);
assert.equal(p.feedbackKey(stuck), "state_confirmed", "HA reflecting it late still confirms the command");
clock += 59999;
assert.equal(p.feedbackKey(stuck), "state_confirmed");
clock += 1;
assert.equal(p.feedbackKey(stuck), "", "a confirmation is aged from its own stamp, not the command's");

// An entry that has aged out must not come back as a confirmation.
p.controlFeedback = [];
Api.setDashboardFeedback(p, stuck.entity_id, "action_sent", {command: "toggle", value: true});
clock += 60000;
Api.confirmDashboardFeedback(p);
assert.equal(p.feedbackKey(stuck), "", "a discarded command cannot be revived");

// An entry without an expectation is terminal and is never reconsidered.
p.controlFeedback = [];
Api.setDashboardFeedback(p, stuck.entity_id, "action_error");
assert.equal(p.feedbackKey(stuck), "action_error");
clock += 59999;
Api.confirmDashboardFeedback(p);
assert.equal(p.feedbackKey(stuck), "action_error", "a failed action is not confirmed by matching state");
clock += 1;
assert.equal(p.feedbackKey(stuck), "");

// A track skip has no state to confirm, so it stays sent instead of turning into a warning.
p.controlFeedback = [];
Api.setDashboardFeedback(p, stuck.entity_id, "action_sent", {command: "media_next_track", stateless: true});
p.dashboardPages = [{items: [{entity_id: stuck.entity_id, state: true, available: true}]}];
clock += 15000;
Api.confirmDashboardFeedback(p);
assert.equal(p.feedbackKey(stuck), "action_sent", "a command without a state is never reported as unconfirmed");
clock += 45000;
assert.equal(p.feedbackKey(stuck), "", "and settles like any other entry");
Api.Date = realDate;
p.controlFeedback = [];
p.dashboardPages = [];
console.log("Feedback ageing passed");
// Full-height tiles carry their own buttons.
const commands = list => Array.from(list, q => q.command + ":" + q.steps);
const coverItem = {entity_id: "cover.shade", controls: [
    {command: "close_cover", kind: "button"}, {command: "open_cover", kind: "button"},
    {command: "stop_cover", kind: "button"},
    {command: "position", kind: "number", value: 40, min: 0, max: 100, step: 1}]};
assert.deepEqual(commands(Api.dashboardQuickControls(coverItem)),
    ["open_cover:0", "stop_cover:0", "close_cover:0"], "a cover shows up/stop/down, not its position pair");
const lightItem = {entity_id: "light.desk", domain: "c300x", available: true, state: true, controls: [
    {command: "toggle", kind: "button"},
    {command: "brightness", kind: "number", value: 95, min: 0, max: 100, step: 1, unit: "%"}]};
assert.deepEqual(commands(Api.dashboardQuickControls(lightItem)), ["brightness:-10", "brightness:10"],
    "one-percent controls step by ten on the tile");
assert.deepEqual(commands(Api.dashboardQuickControls({controls: [
    {command: "temperature", kind: "number", value: 20, min: 5, max: 30, step: 0.5},
    {command: "hvac_mode", kind: "choice", value: "heat", options: ["off", "heat"]}]})),
    ["temperature:-1", "temperature:1"], "a thermostat steps by its own step");
assert.deepEqual(commands(Api.dashboardQuickControls({controls: [{command: "toggle", kind: "button"}]})), [],
    "a plain on/off entity has only its switch");
assert.deepEqual(commands(Api.dashboardQuickControls(null)), []);
const selectControl = {command: "option", kind: "choice", value: "b", options: ["a", "b", "c"]};
assert.equal(Api.dashboardCycleOption(selectControl, 1), "c");
assert.equal(Api.dashboardCycleOption(selectControl, -1), "a");
assert.equal(Api.dashboardCycleOption({options: ["a", "b"], value: "b"}, 1), "a", "wraps forwards");
assert.equal(Api.dashboardCycleOption({options: ["a", "b"], value: "a"}, -1), "b", "wraps backwards");
assert.equal(Api.dashboardCycleOption({options: ["a", "b"], value: null}, 1), "a", "unknown starts at the first");
assert.equal(Api.dashboardCycleOption({options: ["a", "b"]}, -1), "b", "unknown starts at the last");
assert.equal(Api.dashboardCycleOption({options: []}, 1), null);
assert.equal(p.quickLabel({steps: -10, kind: "number"}, null), "-");
assert.equal(p.quickLabel({steps: 1, kind: "choice"}, null), "›");
assert.equal(p.quickLabel({steps: 0, kind: "button"}, {command: "stop_cover"}), "■");
assert.equal(p.quickLabel({}, undefined), "", "a delegate outliving its entry renders nothing");
const brightnessStep = {command: "brightness", kind: "number", steps: 10};
assert.equal(p.quickUsable(brightnessStep, lightItem.controls[1]), true);
assert.equal(p.quickUsable(brightnessStep, {command: "brightness", kind: "number", value: null, min: 0, max: 100, step: 1}), false,
    "minus/plus without a value would send nothing, so the tile dims them");
assert.equal(p.quickUsable({command: "temperature", kind: "number", steps: 1}, {command: "temperature", kind: "number", min: 5, max: 30, step: 0.5}), false,
    "a thermostat without a target has nothing to step from");
assert.equal(p.quickUsable({command: "option", kind: "choice", steps: 1}, {command: "option", kind: "choice", value: null, options: ["a"]}), true,
    "a select without a current option still steps to the first");
assert.equal(p.quickUsable({command: "stop_cover", kind: "button", steps: 0}, {command: "stop_cover", kind: "button"}), true);
assert.equal(p.quickUsable({command: "missing", kind: "number", steps: 1}, undefined), false);
p.dashboardOnline = true; p.pendingEntity = ""; queue.length = 0;
p.quickAction(lightItem, {command: "brightness", kind: "number", steps: 10});
assert.match(queue[0].url, /light.desk%3Abrightness&option=100$/, "the tile step is clamped to the control range");
p.pendingEntity = ""; p.controlInFlight = false; queue.length = 0;
p.quickAction({entity_id: "select.mode", domain: "c300x", available: true, controls: [selectControl]},
    {command: "option", kind: "choice", steps: 1});
assert.match(queue[0].url, /select.mode%3Aoption&option=c$/);
p.pendingEntity = ""; p.controlInFlight = false; queue.length = 0;
p.quickAction(Object.assign({domain: "c300x", available: true}, coverItem), {command: "stop_cover", kind: "button", steps: 0});
assert.match(queue[0].url, /cover.shade%3Astop_cover$/, "a plain button sends no option");
p.pendingEntity = ""; p.controlInFlight = false; queue.length = 0;
p.quickAction(lightItem, {command: "missing", kind: "number", steps: 1});
assert.equal(queue.length, 0, "a control the entity no longer offers sends nothing");
const sized = Api.dashboardMixedItems([
    {kind: "switch", domain: "c300x", entity_id: "switch.a", tile_width: "full", tile_height: "full"},
    {kind: "switch", domain: "c300x", entity_id: "switch.b"}]);
assert.equal(sized[0].tile_width, "full"); assert.equal(sized[0].tile_height, "full");
assert.equal(sized[1].tile_width, undefined, "automatic adds no key");
p.controlFeedback = [];
console.log("Tile controls passed");
// The weather card is one ordered item of its page.
const kinds = list => Array.from(list, i => i.kind + (i.entity_id ? ":" + i.entity_id : ""));
const sw = id => ({kind: "switch", domain: "c300x", entity_id: id});
const weatherData = {available: true, temperature: "12 C"};
assert.deepEqual(kinds(Api.dashboardMixedItems([sw("switch.a"), {kind: "weather"}, sw("switch.b")])),
    ["switch:switch.a", "weather", "switch:switch.b"], "a weather item keeps its configured place");
assert.deepEqual(kinds(Api.dashboardWeatherPlaced(Api.dashboardMixedItems([sw("switch.a"), {kind: "weather"}]), weatherData)),
    ["switch:switch.a", "weather"]);
assert.deepEqual(kinds(Api.dashboardWeatherPlaced(Api.dashboardMixedItems([sw("switch.a")]), weatherData)),
    ["weather", "switch:switch.a"], "an older Home Assistant without the item still shows the card on top");
assert.deepEqual(kinds(Api.dashboardWeatherPlaced(Api.dashboardMixedItems([{kind: "weather"}, sw("switch.a")]), null)),
    ["switch:switch.a"], "no weather data leaves no empty card");
assert.deepEqual(kinds(Api.dashboardWeatherPlaced(Api.dashboardMixedItems([{kind: "weather"}, {kind: "weather"}]), weatherData)),
    ["weather"], "the card is never shown twice");
assert.deepEqual(kinds(Api.dashboardWeatherPlaced([], undefined)), []);
p.dashboardPages = [{items: [sw("switch.a"), {kind: "weather"}], weather: weatherData}];
p.currentPageIndex = 0; p.pageCount = 1;
Api.loadDashboardPage(p.status, p);
assert.deepEqual(kinds(p.items), ["switch:switch.a", "weather"]);
assert.equal(p.weatherVisible, true);
p.refreshSelectedItem();
p.dashboardPages = []; p.items = [];
console.log("Weather placement passed");
// A media player tile carries transport buttons and confirms play/pause.
const playerItem = {entity_id: "media_player.kitchen", domain: "c300x", available: true, state: true,
    details: {type: "media_player", playing: true}, controls: [
    {command: "toggle", kind: "button"},
    {command: "media_previous_track", kind: "button"},
    {command: "media_play_pause", kind: "button", playing: true},
    {command: "media_next_track", kind: "button"},
    {command: "volume_level", kind: "number", value: 40, min: 0, max: 100, step: 1, unit: "%"},
    {command: "volume_mute", kind: "boolean", value: false},
    {command: "source", kind: "choice", value: "Radio", options: ["Radio", "TV"]}]};
assert.deepEqual(commands(Api.dashboardQuickControls(playerItem)),
    ["media_previous_track:0", "media_play_pause:0", "media_next_track:0"]);
assert.deepEqual(commands(Api.dashboardQuickControls({controls: [
    {command: "media_play_pause", kind: "button", playing: false},
    {command: "volume_level", kind: "number", value: 40, min: 0, max: 100, step: 1}]})),
    ["media_play_pause:0"], "a player without track buttons shows what it has, not a volume pair");
assert.equal(p.controlLabel({command: "media_play_pause", playing: true}), "||");
assert.equal(p.controlLabel({command: "media_play_pause", playing: false}), ">");
assert.equal(p.controlLabel({command: "media_play_pause"}), ">", "an unknown state offers play");
assert.equal(p.controlLabel({command: "media_previous_track"}), "«");
assert.equal(p.controlLabel({command: "media_next_track"}), "»");
assert.equal(p.optionLabel({command: "source"}, "off"), "off", "a source name is never translated as a mode");
assert.deepEqual(Array.from(Api.dashboardVisibleControls(playerItem, ""), c => c.command),
    ["media_previous_track", "media_play_pause", "media_next_track", "volume_level", "volume_mute", "source"],
    "the power switch lives in the summary, not in the control list");
const pauseExpected = Api.dashboardExpectation(playerItem, playerItem.controls[2], null);
assert.equal(pauseExpected.playing, false);
assert.equal(Api.dashboardExpectationMatches(playerItem, pauseExpected), false, "still playing is not a confirmation");
const pausedItem = JSON.parse(JSON.stringify(playerItem));
pausedItem.controls[2].playing = false; pausedItem.details.playing = false;
assert.equal(Api.dashboardExpectationMatches(pausedItem, pauseExpected), true);
const withoutPlayButton = JSON.parse(JSON.stringify(pausedItem)); withoutPlayButton.controls.splice(2, 1);
assert.equal(Api.dashboardExpectationMatches(withoutPlayButton, pauseExpected), true,
    "a player that cannot play loses the button once paused, and HA reports it paused");
const playExpected = Api.dashboardExpectation(pausedItem, pausedItem.controls[2], null);
assert.equal(playExpected.playing, true);
assert.equal(Api.dashboardExpectationMatches(pausedItem, playExpected), false, "still paused is not a confirmation");
const withoutPauseButton = JSON.parse(JSON.stringify(playerItem)); withoutPauseButton.controls.splice(2, 1);
assert.equal(Api.dashboardExpectationMatches(withoutPauseButton, playExpected), true,
    "a player that cannot pause loses the button once playing, and HA reports it playing");
assert.equal(Api.dashboardExpectationMatches(withoutPlayButton, playExpected), false,
    "a lost button is no confirmation: a cast player whose session ended is not playing");
const switchedOff = JSON.parse(JSON.stringify(withoutPlayButton)); switchedOff.state = false;
assert.equal(Api.dashboardExpectationMatches(switchedOff, playExpected), false, "a player switched off is not playing");
assert.equal(Api.dashboardExpectationMatches(Object.assign({}, withoutPauseButton, {details: {type: "media_player"}}), playExpected), false,
    "without the reported playback state nothing is confirmed");
assert.equal(Api.dashboardExpectationMatches(Object.assign({}, withoutPlayButton, {available: false}), pauseExpected), false,
    "an unavailable player confirms nothing");
for (const skip of [playerItem.controls[1], playerItem.controls[3]]) {
    const skipExpected = Api.dashboardExpectation(playerItem, skip, null);
    assert.deepEqual(JSON.parse(JSON.stringify(skipExpected)), {command: skip.command, stateless: true},
        "a track skip has no state to confirm");
    assert.equal(Api.dashboardExpectationMatches(playerItem, skipExpected), false, "so no state confirms it");
}
p.pendingEntity = ""; p.controlInFlight = false; p.dashboardOnline = true; queue.length = 0;
p.quickAction(playerItem, {command: "media_next_track", kind: "button", steps: 0});
assert.match(queue[0].url, /media_player.kitchen%3Amedia_next_track$/);
p.pendingEntity = ""; p.controlInFlight = false; queue.length = 0; p.controlFeedback = [];
const everyPlayerControl = playerItem.controls.concat([{command: "sound_mode", kind: "choice", value: "Movie", options: ["Movie"]}]);
for (const language of ["en", "de", "fr", "it"]) {
    p.uiLanguage = language;
    for (const control of everyPlayerControl) {
        assert.notEqual(p.controlLabel(control), control.command, language + " label for " + control.command);
    }
    for (const key of ["media_previous_track", "media_play_pause", "media_next_track"]) {
        assert.equal(I18n.text(language, key), key, "the " + key + " button draws a symbol, so no text ships for it");
    }
}
p.uiLanguage = "en";
console.log("Media player controls passed");



// A fan steps by one of its speeds: HA sends the speed grid, rounded down.
const fanItem = {entity_id: "fan.three", domain: "c300x", available: true, state: true, details: {type: "fan"},
    controls: [{command: "percentage", kind: "number", value: 66.666666, min: 0, max: 100, step: 33.333333, unit: "%"}]};
assert.deepEqual(commands(Api.dashboardQuickControls(fanItem)), ["percentage:-1", "percentage:1"],
    "a three-speed fan moves one speed per tile press");
assert.equal(p.controlValue(fanItem.controls[0]), "66 %", "the speed reads like HA's own percentage");
// A fan is a switch-kind item; its tile shows the speed its minus and plus step.
const fanTile = Object.assign(JSON.parse(JSON.stringify(fanItem)), {kind: "switch"});
assert.equal(p.itemDetail(fanTile), "On   Speed: 66 %", "a fan tile reads the speed it steps");
const offFanTile = JSON.parse(JSON.stringify(fanTile)); offFanTile.state = false; offFanTile.controls[0].value = 0;
assert.equal(p.itemDetail(offFanTile), "Off   Speed: 0 %", "an off fan reads speed 0");
for (const language of ["en", "de", "fr", "it"]) {
    p.uiLanguage = language;
    assert.equal(p.itemDetail(fanTile), p.uiText("on") + "   " + p.uiText("percentage") + ": 66 %", language + " fan tile reading");
    assert.notEqual(p.uiText("percentage"), "percentage", language + " names the fan speed");
}
p.uiLanguage = "en";
assert.equal(p.controlValue({command: "percentage", value: 99.999999, unit: "%"}), "100 %");
assert.equal(p.controlValue({command: "temperature", value: 20.5, unit: "C"}), "20.5 C", "other numbers are shown as sent");
p.pendingEntity = ""; p.controlInFlight = false; p.dashboardOnline = true; queue.length = 0;
p.adjustControl(fanItem, fanItem.controls[0], 1);
assert.match(queue[0].url, /fan.three%3Apercentage&option=99.999999$/, "plus reaches the top speed");
const topExpected = Api.dashboardExpectation(fanItem, fanItem.controls[0], "99.999999");
const topItem = JSON.parse(JSON.stringify(fanItem)); topItem.controls[0].value = 99.999999;
assert.equal(Api.dashboardExpectationMatches(topItem, topExpected), true, "HA's next state confirms the press");
p.pendingEntity = ""; p.controlInFlight = false; queue.length = 0;
p.adjustControl(fanItem, fanItem.controls[0], -1);
assert.match(queue[0].url, /fan.three%3Apercentage&option=33.333333$/, "minus leaves the current speed");
p.pendingEntity = ""; p.controlInFlight = false; queue.length = 0; p.controlFeedback = [];
console.log("Fan speed steps passed");
// A fractional step can leave the range's quotient just under a whole number.
for (const [min, max, step, top] of [[0.05, 1, 0.05, "1"], [-0.7, 0.7, 0.1, "0.7"], [0.1, 0.7, 0.1, "0.7"]]) {
    const ranged = {entity_id: "number.mix", domain: "c300x", available: true,
        controls: [{command: "value", kind: "number", value: Number(top), min, max, step}]};
    p.pendingEntity = ""; p.controlInFlight = false; queue.length = 0;
    p.adjustControl(ranged, ranged.controls[0], 1);
    assert.match(queue[0].url, new RegExp("number.mix%3Avalue&option=" + top.replace(".", "\\.") + "$"),
        "plus at the top of " + min + ".." + max + " stays at the top");
}
assert.equal(p.controlLastStep({min: -0.7, max: 0.7, step: 0.1}), 14);
assert.equal(p.controlLastStep({min: 7, max: 35, step: 0.5}), 56);
assert.equal(p.controlLastStep({min: 0, max: 100, step: 33.333333}), 3, "a fan keeps its own speeds");
assert.equal(p.controlLastStep({min: 0, max: 1, step: 0.3}), 3, "a range off the grid ends at its last whole step");
p.pendingEntity = ""; p.controlInFlight = false; queue.length = 0; p.controlFeedback = [];
console.log("Fractional ranges passed");
