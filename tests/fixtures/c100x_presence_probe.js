const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const requests = [];
class Request {
    constructor() { requests.push(this); this.headers = {}; }
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader(key, value) { this.headers[key] = value; }
    send() {}
    abort() { this.aborted = true; }
}
const context = {XMLHttpRequest: Request};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8").replace(/^\.pragma library\s*/, ""), context);
const owner = {running: true, stopped: false, blocked: false, vendorReady: false, displayReady: false, generation: "a".repeat(64),
    presenceRetry: {interval: 1000, count: 0, stop() {}, restart() { this.count++; }}};
const presence = context.create(owner);
presence.start();
assert.equal(requests.length, 0);
owner.vendorReady = true;
presence.start();
assert.equal(requests.length, 0, "vendor objects alone do not prove loaders");
owner.displayReady = true;
presence.start(); presence.start();
assert.equal(requests.length, 1);
assert.match(requests[0].url, /generation=a{64}&blocked=0$/);
assert.equal(requests[0].headers["X-C100X-GUI"], "presence-v1");
const late = requests[0].onreadystatechange;
owner.blocked = true;
presence.sync();
assert.equal(requests[0].aborted, true);
assert.match(requests[1].url, /blocked=1$/);
requests[0].readyState = 4; requests[0].status = 200;
late();
assert.equal(owner.presenceRetry.count, 0, "late callback revived prior lease");
requests[1].readyState = 4; requests[1].status = 200;
requests[1].responseText = JSON.stringify({ok: true, probe: "c".repeat(32)});
requests[1].onreadystatechange();
assert.equal(owner.presenceRetry.interval, 100);
presence.start();
assert.match(requests[2].url, /&probe=c{32}$/);
requests[2].readyState = 4; requests[2].status = 503;
requests[2].onreadystatechange();
assert.equal(owner.presenceRetry.interval, 30000);
owner.generation = "../unknown";
presence.sync();
assert.equal(requests.length, 3);
owner.generation = "b".repeat(64);
presence.sync();
assert.match(requests[3].url, /generation=b{64}/);
assert.doesNotMatch(requests[3].url, /probe=/, "challenge cannot cross generation/guard changes");
owner.stopped = true;
presence.stop(); presence.start();
assert.equal(requests[3].aborted, true);
assert.equal(requests.length, 4);
