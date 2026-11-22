const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const requests = [];
class Request {
    constructor() { requests.push(this); this.headers = {}; this.aborted = false; }
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader(key, value) { this.headers[key] = value; }
    send() {}
    abort() { this.aborted = true; }
    reply(data, status = 200) {
        this.status = status;
        this.responseText = typeof data === "string" ? data : JSON.stringify(data);
        this.readyState = 4;
        this.onreadystatechange();
    }
}
const sandbox = {XMLHttpRequest: Request, Date, isFinite};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8").replace(/^\.pragma library\s*/, ""), sandbox);
const owner = {
    stopped: false, running: true, blocked: false, muted: false, applied: 0, retries: 0,
    setMuted(value) { this.applied++; this.muted = value; },
    reconnectRinger() { this.retries++; }
};
const runtime = sandbox.create(owner);
function command(id, muted = true) { return {ok: true, id: id.repeat(32), muted, expires: Date.now() + 5000}; }
runtime.start();
runtime.start();
assert.equal(requests.length, 1, "duplicate sleeping request");
assert.equal(requests[0].headers["X-C300X-GUI"], "ringer-v1");
requests[0].reply(command("a"));
assert.equal(owner.applied, 1);
assert.equal(requests.length, 2);
assert.match(requests[1].url, /completed=a{32}&muted=1$/);
requests[1].reply(command("a"));
assert.equal(owner.applied, 1, "replayed command applied twice");
assert.equal(owner.retries, 1);
runtime.start();
owner.setMuted = function() { this.applied++; }; // Vendor ignores the requested state.
requests.at(-1).reply(command("b", false));
assert.match(requests.at(-1).url, /completed=b{32}&muted=1$/, "ack invented a successful change");
const pending = requests.at(-1);
const late = pending.onreadystatechange;
owner.blocked = true;
runtime.stop();
assert.equal(pending.aborted, true);
pending.readyState = 4;
pending.status = 200;
pending.responseText = JSON.stringify(command("c"));
late();
assert.equal(owner.applied, 2, "late reply applied during call");
const count = requests.length;
runtime.start();
assert.equal(requests.length, count, "request started while blocked");
owner.blocked = false;
for (const data of [
    {...command("d"), expires: 1}, {...command("d"), muted: 1},
    {...command("d"), id: "../foreign"}, {...command("d"), ok: false},
    "{broken", " ".repeat(1025)
]) {
    runtime.start();
    requests.at(-1).reply(data);
}
assert.equal(owner.applied, 2, "invalid command applied");
runtime.start();
owner.blocked = true; // Guard transition before the QML cancellation callback.
requests.at(-1).reply(command("e"));
assert.equal(owner.applied, 2);
owner.blocked = false;
runtime.start();
owner.stopped = true;
runtime.stop();
assert.equal(requests.at(-1).aborted, true);
const stoppedCount = requests.length;
runtime.start();
assert.equal(requests.length, stoppedCount);
