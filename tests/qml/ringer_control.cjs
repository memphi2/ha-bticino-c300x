const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../..");
const source = fs.readFileSync(path.join(root, "device_qml/C300XRingerControl.qml"), "utf8");

assert.doesNotMatch(source, /property\s+(?:variant|var)\s+pendingRequest\b/,
    "Qt4 must not round-trip the XHR through a QML variant");
assert.match(source, /^import "js\/c300x_ringer.js" as Ringer$/m);
const library = fs.readFileSync(path.join(root, "device_qml/js/c300x_ringer.js"), "utf8");
assert.doesNotMatch(library, /^\s*\.pragma\s+library\b/m,
    "each Ringer control needs its own request state");
const handlers = [...source.matchAll(/^    function [\s\S]*?^    }/gm)].map(m => m[0]).join("\n");
const destruction = source.match(/Component\.onDestruction: \{([\s\S]*?)^    }/m)[1];
assert.match(source, /interval: 30000\s+repeat: false\s+onTriggered: control.waitForCommand\(\)/);
assert.match(source, /Component\.onCompleted: waitForCommand\(\)/);

function runtime() {
    const requests = [], operations = [];
    let reconnects = 0, stops = 0, mute = true;
    class Request {
        static DONE = 4;
        constructor() { this.aborts = 0; }
        open(method, url, async) {
            this.url = url;
            assert.equal(method, "GET");
            assert.equal(async, true);
        }
        setRequestHeader(name, value) {
            assert.equal(name, "X-C300X-GUI");
            assert.equal(value, "ringer-v1");
        }
        send() { requests.push(this); }
        reply(data, status = 200) {
            this.status = status;
            this.responseText = JSON.stringify(data);
            this.readyState = Request.DONE;
            this.onreadystatechange();
        }
        abort() {
            this.aborts++;
            this.reply(null, 0);
        }
    }
    const Ringer = vm.createContext({});
    vm.runInContext(library, Ringer);
    const audioState = {
        enableState(state) { assert.equal(state, 4); mute = true; operations.push("enable"); },
        disableState(state) { assert.equal(state, 4); mute = false; operations.push("disable"); },
        isStateEnabled(state) { assert.equal(state, 4); return mute; },
    };
    const context = vm.createContext({Ringer, stopped: false, uiBaseUrl: "http://127.0.0.1:18090", XMLHttpRequest: Request,
        global: {audioState}, AudioState: {RingtoneMute: 4},
        reconnect: {start() { reconnects++; }, stop() { stops++; }}});
    Object.defineProperty(context, "pendingRequest", {
        get() { assert.fail("request handle must remain in JS state"); },
        set() { assert.fail("request handle must remain in JS state"); },
    });
    vm.runInContext(handlers, context);
    return {context, requests, operations, get mute() { return mute; },
        get reconnects() { return reconnects; }, get stops() { return stops; },
        shutdown() { vm.runInContext(destruction, context); }};
}

function command(muted, overrides = {}) {
    return Object.assign({ok: true, id: "a".repeat(32), muted, expires: Date.now() + 5000}, overrides);
}

const r = runtime();
r.context.waitForCommand();
r.context.waitForCommand();
assert.equal(r.requests.length, 1, "only one sleeping request");
assert.equal(r.requests[0].url, "http://127.0.0.1:18090/ui/ringer/next?picture=1");
r.requests[0].reply(command(false));
assert.equal(r.mute, false);
assert.deepEqual(r.operations, ["disable"]);
assert(r.requests[1].url.endsWith("completed=" + "a".repeat(32) + "&muted=0"));
r.requests[1].reply(command(true));
assert.equal(r.mute, true);
assert.deepEqual(r.operations, ["disable", "enable"]);
assert(r.requests[2].url.endsWith("&muted=1"));

const liveCount = r.requests.length;
r.requests[0].reply(command(false));
assert.equal(r.requests.length, liveCount, "duplicate old completion cannot create another poll");
assert.equal(r.mute, true);
r.requests[2].reply(command(false, {expires: Date.now() - 1}));
assert.equal(r.reconnects, 1);
for (const bad of [{id: "../arbitrary"}, {muted: "false"}, {ok: false}, {expires: "tomorrow"}]) {
    r.context.waitForCommand();
    r.requests.at(-1).reply(command(false, bad));
    assert.equal(r.mute, true);
}
assert.equal(r.reconnects, 5);
r.context.waitForCommand();
r.requests.at(-1).reply(null, 503);
assert.equal(r.reconnects, 6, "HTTP failure schedules the existing reconnect timer");
r.context.waitForCommand();
const pending = r.requests.at(-1);
const late = pending.onreadystatechange;
const count = r.requests.length;
r.shutdown();
assert.equal(pending.aborts, 1, "destruction aborts the original XHR instance");
assert.equal(r.stops, 1);
assert.equal(r.reconnects, 6, "synchronous abort callback cannot schedule reconnect");
pending.reply(command(false));
late();
r.context.waitForCommand();
r.shutdown();
assert.equal(pending.aborts, 1, "cleanup clears the handle before aborting");
assert.equal(r.requests.length, count);
assert.deepEqual(r.operations, ["disable", "enable"]);
assert.ok(r.requests.slice(0, -1).every(request => request.aborts === 0));

const first = runtime(), second = runtime();
first.context.waitForCommand();
second.context.waitForCommand();
first.shutdown();
assert.equal(first.requests[0].aborts, 1);
assert.equal(second.requests[0].aborts, 0, "another control owns a separate request");
second.requests[0].reply(command(false));
assert.equal(second.mute, false);
assert.equal(second.requests.length, 2);
second.shutdown();
const idle = runtime();
const picture = runtime();
const callObj = {callInProgress: true, brightness: 10, contrast: 20, color: 30};
picture.context.videocallPage = {item: {callObj}};
picture.context.waitForCommand();
for (const [key, property] of [["brightness", "brightness"], ["contrast", "contrast"], ["saturation", "color"]]) {
    picture.requests.at(-1).reply(command(undefined, {picture: key, value: 90}));
    assert.equal(callObj[property], 90);
    assert.ok(picture.requests.at(-1).url.includes(key+"=90"));
}
callObj.callInProgress = false;
picture.requests.at(-1).reply(command(undefined, {picture: "brightness", value: 0}));
assert.equal(callObj.brightness, 90);
assert.ok(!picture.requests.at(-1).url.includes("brightness="));
assert.deepEqual(picture.operations, []);
picture.shutdown();
idle.shutdown();
assert.equal(idle.requests.length, 0);
console.log("Ringer command semantics, Qt4 JS ownership and teardown passed");
