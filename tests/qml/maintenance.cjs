const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const dir = path.join(__dirname, "../../device_qml");
const queue = [];
class Request {
    open(method, url) { this.method = method; this.url = url; this.headers = {}; }
    setRequestHeader(k, v) { this.headers[k] = v; }
    send(body) { this.body = body; queue.push(this); }
    abort() { this.reply(null, 0); }
    reply(data, status = 200) {
        Object.assign(this, {readyState: 4, status, responseText: JSON.stringify(data)});
        this.onreadystatechange();
    }
}
const api = vm.createContext({XMLHttpRequest: Request});
vm.runInContext(fs.readFileSync(path.join(dir, "js/c300x_maintenance.js"), "utf8"), api);
const deadline = {stop() {}, restart() {}};
const panel = {uiBaseUrl:"http://127.0.0.1:18123"};
function next(method, suffix, payload) {
    const req = queue.shift();
    assert.equal(req.url, "http://127.0.0.1:18123/ui/maintenance" + suffix);
    assert.equal(req.method, method);
    assert.equal(req.headers["x-c300x-ui"], "settings-v1");
    assert.equal(req.body, payload ? JSON.stringify(payload) : "");
    return req;
}
api.request(panel, deadline, "", null);
next("GET", "").reply({ok:true, ssh:true, reboot:true, remove:false});
next("GET", "/ssh").reply({ok:true, running:false});
assert.equal(panel.sshKnown, true);
assert.equal(panel.canRemove, false);
api.request(panel, deadline, "/ssh", {enabled:true});
api.request(panel, deadline, "/ssh", {enabled:true});
next("POST", "/ssh", {enabled:true}).reply({ok:true, running:true});
assert.equal(panel.sshRunning, true);
assert.equal(queue.length, 0);
api.request(panel, deadline, "/ssh", null);
const stale = next("GET", "/ssh");
api.cancel(panel, deadline);
stale.reply({ok:true, running:false});
assert.equal(panel.sshRunning, true);
api.request(panel, deadline, "", null);
// A read the user did not ask for leaves no message: the rows show what is unknown.
for (const [path, answer] of [["", null], ["", {ok:false}], ["/ssh", null]]) {
    panel.sshKnown = true;
    api.request(panel, deadline, path, null);
    next("GET", path).reply(answer, answer ? 200 : 500);
    assert.deepEqual([panel.busy, panel.status, panel.sshKnown], [false, "", path !== "/ssh"], "failed read of " + (path || "the abilities"));
}
api.request(panel, deadline, "", null);
api.expire(panel, deadline);
assert.deepEqual([panel.busy, panel.status, queue.length], [false, "", 1], "a read that takes too long leaves no message");
queue.shift();
api.request(panel, deadline, "", null);
next("GET", "").reply({ok:true, ssh:false, reboot:true, remove:true});
api.request(panel, deadline, "/reboot", {confirm:"reboot"});
api.expire(panel, deadline);
assert.deepEqual([panel.busy, panel.status], [false, "maintenance_timeout"], "an action that takes too long says so");
next("POST", "/reboot", {confirm:"reboot"});
api.request(panel, deadline, "", null);
assert.equal(panel.status, "");
api.expire(panel, deadline);
assert.equal(panel.status, "", "the read after an action is a read");
queue.shift();
api.expire(panel, deadline);
assert.equal(panel.status, "", "nothing is under way");
for (const path of ["/ssh", "/reboot", "/remove"]) {
    api.request(panel, deadline, path, {enabled:true});
    next("POST", path, {enabled:true}).reply(null, 500);
    assert.deepEqual([panel.busy, panel.status], [false, "display_settings_error"], "failed action " + path);
}
assert.match(fs.readFileSync(path.join(dir, "C300XSettings.qml"), "utf8"),
    /id: deadline\n        interval: 125000\n        onTriggered: Maintenance\.expire\(panel, deadline\)\n/);
api.request(panel, deadline, "", null);
next("GET", "").reply({ok:true, ssh:false, reboot:false, remove:false});
assert.equal(panel.canReboot, false);
assert.equal(queue.length, 0);

const qml = fs.readFileSync(path.join(dir, "C300XSettings.qml"), "utf8");
// Ten seconds were too short to read the removal question and decide.
assert.ok(qml.includes("Timer { id: expiry; interval: 30000; onTriggered: panel.clearConfirmation() }"), "the question stays for 30 seconds");
const ui = vm.createContext({panel, Maintenance: api, deadline, visible:true, busy:false,
    canReboot:true, canRemove:true, pending:"", expiresAt:0, expiry:{interval:30000, restart(){}, stop(){}},
    popups: [], dismissed: 0,
    installPopup(component) { ui.popups.push(component); ui.open = true },
    dismissPopup() { ui.dismissed++; ui.open = false }, confirmation: "confirmation"});
vm.runInContext(qml.slice(qml.indexOf("    function clearConfirmation"), qml.indexOf("    Timer {")), ui);
for (const action of ["reboot", "remove"]) {
    assert.ok(qml.includes('model: ["reboot", "remove"]') && qml.includes("onMouseClicked: panel.ask(modelData)"));
    // The question is the vendor's own popup. Nothing is sent before "Yes".
    ui.popups.length = 0;
    ui.dismissed = 0;
    ui.clearConfirmation();
    assert.equal(ui.dismissed, 0, "a popup that is not ours stays");
    ui.ask(action);
    assert.deepEqual([ui.popups, ui.open, ui.pending, queue.length], [["confirmation"], true, action, 0]);
    ui.ask(action === "reboot" ? "remove" : "reboot");
    assert.deepEqual([ui.popups.length, ui.pending], [1, action], "one question at a time");
    ui.expiresAt = Date.now() - 1;
    ui.confirmAction();
    assert.deepEqual([queue.length, ui.open, ui.pending], [0, false, ""], "an expired question sends nothing");
    ui.ask(action);
    ui.clearConfirmation();
    ui.confirmAction();
    assert.deepEqual([queue.length, ui.open, ui.dismissed], [0, false, 2], "No sends nothing");
    ui.ask(action);
    ui.visible = false;
    ui.confirmAction();
    ui.visible = true;
    assert.deepEqual([queue.length, ui.open], [0, false], "a hidden tab sends nothing");
    ui.ask(action);
    ui.confirmAction();
    assert.equal(ui.open, false);
    next("POST", "/" + action, {confirm: action === "remove" ? "remove_agent" : "reboot"})
        .reply({ok:true}, 202);
    ui.confirmAction();
    assert.equal(queue.length, 0);
}
assert.match(qml, /import Components\.Settings 1\.0\n/);
assert.match(qml, /Component \{\n        id: confirmation\n        ConfirmPopup \{\n            sourceSizeWidth: 400\n            sourceSizeHeight: panel\.pending === "remove" \? 190 : 130\n            maxLine: 6\n            message: panel\.pending \? panel\.label\("maintenance_confirm_" \+ panel\.pending\) : ""\n            onDeleteClicked: panel\.confirmAction\(\)\n            onCancelClicked: panel\.clearConfirmation\(\)\n/);
assert.ok(!qml.includes('visible: panel.pending !== ""'), "no second confirmation inside the tab");
assert.equal(qml.split("!panel.pending").length - 1, 2, "switches and both actions rest while the question is open");
assert.match(qml, /onTriggered: panel.clearConfirmation\(\)/);
assert.match(qml, /function hidden\(\) \{\s*clearConfirmation\(\)/);
assert.match(qml, /onVisibleChanged: if \(visible\) readStatus\(\); else hidden\(\)/);
const translations = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(dir, "js/c300x_i18n.js"), "utf8")
    .replace(/^\.pragma library/, ""), translations);
for (const locale of ["de", "en", "it", "fr", "es"]) {
    for (const key of ["reboot", "remove", "confirm_reboot", "confirm_remove", "accepted", "timeout"]) {
        assert.ok(translations.catalog(locale)["maintenance_" + key], locale + ": " + key);
    }
    for (const key of ["confirm_reboot", "confirm_remove"]) {
        assert.match(translations.catalog(locale)["maintenance_" + key], /^[^\n]+\?\n[^\n]+\.$/, locale + ": " + key);
    }
    assert.equal(translations.catalog(locale).maintenance_cancel, undefined);
}
