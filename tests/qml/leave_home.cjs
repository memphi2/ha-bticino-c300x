const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const qml = fs.readFileSync(path.join(__dirname, "../../device_qml/C300XLeaveHome.qml"), "utf8");
const methods = [...qml.matchAll(/^    function [\s\S]*?^    }/gm)].map(m => m[0]).join("\n");
let running = false;
const actions = [];
const ctx = vm.createContext({busy: false, online: true, visible: true, pendingActionId: "",
    confirmationTimer: {stop() { running = false; }, restart() { running = true; }},
    actionRequested(item) { actions.push(item); }});
vm.runInContext(methods, ctx);
const item = {entity_id: "leave", domain: "c300x"};
ctx.requestAction(item);
assert.equal(actions.length, 0, "first tap must not execute");
assert.equal(ctx.pendingActionId, "leave");
assert.equal(running, true);
ctx.requestAction(item);
assert.deepEqual(actions, [item]);
assert.equal(ctx.pendingActionId, "");
assert.equal(running, false);
for (const property of ["busy", "online", "visible"]) {
    ctx[property] = property === "busy";
    ctx.requestAction(item);
    ctx.requestAction(item);
    assert.equal(actions.length, 1, property + " gates execution");
    assert.equal(ctx.pendingActionId, "");
    ctx[property] = property !== "busy";
}
ctx.requestAction(item);
ctx.requestAction({entity_id: "other"});
assert.equal(actions.length, 1, "changing selection starts new confirmation");
assert.equal(ctx.pendingActionId, "other");
ctx.clearConfirmation();
ctx.requestAction(item);
assert.equal(actions.length, 1, "expiry requires a new first tap");
for (const signal of ["LeaveHome", "Busy", "Online"]) {
    assert.match(qml, new RegExp("on" + signal + "Changed: clearConfirmation\\(\\)"));
}
assert.match(qml, /onVisibleChanged: if \(!visible\) clearConfirmation\(\)/);
assert.match(qml, /interval: 8000/);
assert.match(qml, /onTriggered: root.clearConfirmation\(\)/);
assert.match(qml, /onClicked: root.requestAction\(modelData\)/);
assert.doesNotMatch(qml, /Component.onCompleted|XMLHttpRequest|Api\./);
assert.doesNotMatch(qml, /images\/settings\/list_btn/);
assert.match(qml, /root.alarm.available/);
assert.match(qml, /leaveHome.confirm_label/);
assert.match(qml, /leaveHome.cancel_label/);
