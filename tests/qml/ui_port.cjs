const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../..");

const sent = [];
function Request() { this.readyState = 0; }
Request.prototype.open = function(method, url) { this.url = url; };
Request.prototype.setRequestHeader = function() {};
Request.prototype.send = function() { sent.push(this); };
Request.prototype.abort = function() {};
const source = fs.readFileSync(path.join(root, "device_qml/js/c300x_ha.js"), "utf8")
    .replace(/^\.pragma library\s*/, "");
function library() {
    const context = vm.createContext({XMLHttpRequest: Request, Date, Math});
    vm.runInContext(source, context);
    return context;
}
const Api = library();
const timer = () => ({restart() {}, stop() {}});
const owner = {uiBaseUrl: "http://127.0.0.1:18123", ready: false, busy: false, stopped: false,
    deadline: timer(), touchToneRetry: timer(), touchToneReportDeadline: timer(),
    touchToneEnabled: true, applyingTouchTone: false};
assert.equal(Api.baseUrl(), "http://127.0.0.1:8090", "8090 stays the default");
Api.loadDisplayPreferences(owner);
assert.equal(Api.baseUrl(), "http://127.0.0.1:18123", "MainApp's configured base URL is taken");
Api.watchTouchTone(owner);
Api.reportTouchTone(owner);
assert.deepEqual(sent.map(r => r.url.split("?")[0]), ["http://127.0.0.1:18123/ui/preferences",
    "http://127.0.0.1:18123/ui/touch-tone/next", "http://127.0.0.1:18123/ui/touch-tone/state"]);
Api.useBaseUrl("http://192.0.2.5:80");
assert.equal(Api.baseUrl(), "http://127.0.0.1:18123", "only a loopback base URL is taken");
// The home page can ask for its buttons before MainApp's preferences loaded.
const early = library();
early.homeButtons(() => {}, {uiBaseUrl: "http://127.0.0.1:18125", visible: true});
assert.equal(sent[sent.length - 1].url, "http://127.0.0.1:18125/ui/state", "the home page's base URL is taken");
const alerts = fs.readFileSync(path.join(root, "device_qml/C300XAlerts.qml"), "utf8");
assert.ok(alerts.includes('request.open("GET", Api.baseUrl() + "/ui/alerts/next"'));
for (const file of ["js/c300x_ha.js", "js/c300x_memos.js", "C300XAlerts.qml"]) {
    const text = fs.readFileSync(path.join(root, "device_qml", file), "utf8");
    assert.equal((text.match(/127\.0\.0\.1:8090/g) || []).length, file === "C300XAlerts.qml" ? 0 : 1,
        file + " keeps 8090 only as the default");
}
console.log("Display calls follow the configured UI port passed");
