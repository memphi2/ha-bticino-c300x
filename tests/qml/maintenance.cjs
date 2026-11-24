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
next("GET", "").reply(null, 403);
assert.equal(panel.busy, false);
assert.equal(panel.status, "display_settings_error");
api.request(panel, deadline, "", null);
next("GET", "").reply({ok:true, ssh:false, reboot:false, remove:false});
assert.equal(panel.canReboot, false);
assert.equal(queue.length, 0);

const qml = fs.readFileSync(path.join(dir, "C300XSettings.qml"), "utf8");
const ui = vm.createContext({panel, Maintenance: api, deadline, visible:true, busy:false,
    canReboot:true, canRemove:true, pending:"", expiresAt:0, expiry:{interval:10000, restart(){}, stop(){}},
    popups: [], dismissed: 0,
    installPopup(component) { ui.popups.push(component); ui.open = true },
    dismissPopup() { ui.dismissed++; ui.open = false }, confirmation: "confirmation"});
vm.runInContext(qml.slice(qml.indexOf("    function clearConfirmation"), qml.indexOf("    Timer {")), ui);
for (const action of ["reboot", "remove"]) {
    assert.ok(qml.includes('onMouseClicked: panel.ask("' + action + '")'));
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
assert.equal(qml.split("!panel.pending").length - 1, 3, "switches and both actions rest while the question is open");
assert.match(qml, /onTriggered: panel.clearConfirmation\(\)/);
assert.match(qml, /function hidden\(\) \{\s*clearConfirmation\(\)/);
assert.match(qml, /onVisibleChanged: if \(visible\) checkBridge\(\); else hidden\(\)/);
const translations = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(dir, "js/c300x_i18n.js"), "utf8")
    .replace(/^\.pragma library/, ""), translations);
for (const locale of ["de", "en", "it", "fr"]) {
    for (const key of ["reboot", "remove", "confirm_reboot", "confirm_remove", "accepted", "timeout"]) {
        assert.ok(translations.catalog(locale)["maintenance_" + key], locale + ": " + key);
    }
    for (const key of ["confirm_reboot", "confirm_remove"]) {
        assert.match(translations.catalog(locale)["maintenance_" + key], /^[^\n]+\?\n[^\n]+\.$/, locale + ": " + key);
    }
    assert.equal(translations.catalog(locale).maintenance_cancel, undefined);
}
