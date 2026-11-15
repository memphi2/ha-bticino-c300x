const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const qml = fs.readFileSync(path.join(__dirname, "../../device_qml/C300XAlerts.qml"), "utf8");
const js = fs.readFileSync(path.join(__dirname, "../../device_qml/js/c300x_alerts.js"), "utf8");
const methods = [...qml.matchAll(/^    function [\s\S]*?^    }/gm)].map(m => m[0]).join("\n");
const BASE = 1800000000000;
const payload = {id: "1".repeat(32), notification_id: "warning_notice", revision: "2".repeat(32),
    severity: "warning", title: "<b>literal title</b>", message: "literal message", wake_duration: 30,
    sound_duration: 30, expires_in: 3600, remaining_ms: 5000,
    expires: BASE + 5000, message_expires: BASE + 3600000};

function timer() {
    return {running: false, starts: 0, restart() { this.running = true; this.starts++; },
        stop() { this.running = false; }};
}
function fixture() {
    const requests = [];
    const events = [];
    const audio = {state: 0, audioAccess: false, flag: false,
        isStateEnabled(state) { assert.equal(state, 1); return this.flag; },
        enableState(state) {
            assert.equal(state, 1); this.flag = true; this.state = 1; events.push("enable");
            if (audio.onEnable) audio.onEnable();
        },
        disableState(state) { assert.equal(state, 1); this.flag = false; this.state = 0; events.push("disable"); }};
    let failOpen = false, failSend = false;
    function XHR() {
        this.readyState = 0; this.status = 0; this.headers = {}; this.aborted = false;
        requests.push(this);
        this.open = (method, url, async) => {
            this.method = method; this.url = url; assert.equal(async, true);
            if (failOpen) throw Error("open failed");
        };
        this.setRequestHeader = (name, value) => { this.headers[name] = value; };
        this.send = () => { this.sent = true; events.push("send"); if (failSend) throw Error("send failed"); };
        this.abort = () => { this.aborted = true; this.readyState = 4; if (this.onreadystatechange) this.onreadystatechange(); };
        this.complete = (status, data) => {
            this.status = status; this.responseText = typeof data === "string" ? data : JSON.stringify(data);
            this.readyState = 4; this.onreadystatechange();
        };
    }
    XHR.DONE = 4;
    const engine = vm.createContext({});
    vm.runInContext(js.replace(/^\.pragma library\s*/, ""), engine);
    const context = vm.createContext({
        blocked: false, stopped: false, visible: true, controller: null, notice: null,
        pendingRequest: null, pollGeneration: 0, resumeAttempts: 5,
        ackRequest: null, XMLHttpRequest: XHR, Alerts: engine,
        Date: class extends Date { getTime() { return BASE; } },
        effects: timer(), reconnect: timer(), resume: timer(), ackTimeout: timer(), messageScroll: {contentY: 77},
        ScreenState: {ScreenOff: 0, Normal: 2}, AudioState: {Idle: 0, Beep: 1, RingtoneMute: 4},
        global: {audioState: audio, screenState: {state: 2, screensaverInterval: 20000,
            simulateClick() { events.push("wake"); }, disableState() { events.push("release"); }},
            beep() { events.push("beep"); if (context.beepThrows) throw Error("beep failed"); }}
    });
    context.root = context;
    vm.runInContext(methods, context);
    return {c: context, requests, events, audio,
        resume() { assert.equal(context.resume.running, true); context.resume.running = false; context.waitForCommand(); },
        failOpen(value) { failOpen = value; }, failSend(value) { failSend = value; }};
}

// Temporary RAM state is restored even on an exception or synchronous call takeover.
for (const prior of [false, true]) {
    const f = fixture(); f.audio.flag = prior; f.audio.state = prior ? 1 : 0;
    assert.equal(f.c.shortBeep(() => true), true);
    assert.equal(f.audio.flag, prior);
    assert.deepEqual(f.events, prior ? ["beep"] : ["enable", "beep", "disable"]);
}
{
    const f = fixture(); f.c.beepThrows = true;
    assert.throws(() => f.c.shortBeep(() => true), /beep failed/);
    assert.equal(f.audio.flag, false); assert.equal(f.events.at(-1), "disable");
}
{
    const f = fixture(); f.audio.onEnable = () => { f.c.blocked = true; };
    assert.equal(f.c.shortBeep(() => !f.c.blocked), false);
    assert.deepEqual(f.events, ["enable", "disable"]); assert.equal(f.audio.flag, false);
}
{
    const f = fixture(); f.audio.onEnable = () => { f.audio.audioAccess = true; };
    assert.equal(f.c.shortBeep(() => true), false); assert.equal(f.audio.flag, false);
    assert.deepEqual(f.events, ["enable", "disable"], "recheck audioAccess after enable signal");
}
for (const state of [2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]) {
    const f = fixture(); f.audio.state = state;
    assert.equal(f.c.shortBeep(() => true), false); assert.deepEqual(f.events, []);
}
for (const blocked of ["blocked", "stopped"]) {
    const f = fixture(); f.c[blocked] = true;
    assert.equal(f.c.shortBeep(() => true), false); assert.deepEqual(f.events, []);
}
{
    const f = fixture(); f.audio.audioAccess = true;
    assert.equal(f.c.shortBeep(() => true), false); assert.deepEqual(f.events, []);
}

// One sleeping GET only. Re-arm on valid delivery, retry errors after 30s; no idle timer polling.
{
    const f = fixture(); f.c.initialize(); assert.equal(f.requests.length, 1);
    const first = f.requests[0]; assert.equal(first.url, "http://127.0.0.1:8090/ui/alerts/next");
    assert.equal(first.method, "GET"); assert.equal(first.headers["X-C300X-GUI"], "alerts-v1");
    f.c.waitForCommand(); assert.equal(f.requests.length, 1);
    assert.equal(f.c.reconnect.running, false); assert.equal(f.c.effects.running, false);
    first.complete(200, payload);
    assert.equal(f.requests.length, 2); assert.equal(f.c.effects.running, true);
    assert.equal(f.c.notice.title, payload.title); assert.equal(f.c.messageScroll.contentY, 0);
    first.complete(200, payload); assert.equal(f.requests.length, 2, "stale callback cannot steal current request");
    const calls = f.events.length; f.c.preempt(); assert.equal(f.c.effects.running, false);
    f.requests[1].complete(200, payload); assert.equal(f.c.notice, null);
    assert.equal(f.events.slice(calls).filter(e => e === "beep").length, 0, "no replay after preempt");
    f.c.shutdown(); assert.ok(f.requests.at(-1).aborted);
}
for (const response of [[500, {}], [200, "invalid json"], [200, {...payload, unknown: 1}],
    [200, {...payload, expires: BASE}], [200, "x".repeat(16385)]]) {
    const f = fixture(); f.c.initialize(); f.requests[0].complete(...response);
    assert.equal(f.requests.length, 1); assert.equal(f.c.pendingRequest, null);
    assert.equal(f.c.reconnect.running, true); assert.equal(f.c.notice, null);
    f.c.waitForCommand(); assert.equal(f.requests.length, 2); f.c.shutdown();
    assert.equal(f.c.reconnect.running, false);
}
for (const fault of ["failOpen", "failSend"]) {
    const f = fixture(); f[fault](true); f.c.initialize();
    assert.equal(f.c.pendingRequest, null); assert.equal(f.c.reconnect.running, true);
    assert.equal(f.requests[0].aborted, true); f.c.shutdown();
}
for (const guard of ["blocked", "visible"]) {
    const f = fixture(); f.c[guard] = guard === "blocked"; f.c.initialize();
    assert.equal(f.requests.length, 0, "no initial listener on protected or hidden page");
    f.c[guard] = guard !== "blocked"; f.c.updateGuard();
    assert.equal(f.requests.length, 0, "guard clear yields for socket teardown");
    f.resume(); assert.equal(f.requests.length, 1);
    const old = f.c.pendingRequest, stale = old.onreadystatechange;
    f.c[guard] = guard === "blocked"; f.c.updateGuard();
    assert.equal(old.aborted, true); assert.equal(f.c.pendingRequest, null);
    assert.equal(f.c.resume.running, false); assert.equal(f.c.reconnect.running, false);
    f.c.waitForCommand(); assert.equal(f.requests.length, 1);
    f.c[guard] = guard !== "blocked"; f.c.updateGuard(); f.resume();
    const current = f.c.pendingRequest;
    old.status = 200; old.responseText = JSON.stringify(payload); old.readyState = 4;
    stale();
    assert.equal(f.c.pendingRequest, current, "old callback cannot steal resumed listener");
    assert.equal(f.c.notice, null); assert.equal(f.events.includes("wake"), false);
    assert.equal(f.events.includes("beep"), false);
    current.complete(200, payload); assert.equal(f.c.notice.title, payload.title);
    f.c.shutdown();
}
{
    const f = fixture(); f.c.initialize(); const old = f.c.pendingRequest;
    const stale = old.onreadystatechange;
    f.c.preempt();
    assert.equal(old.aborted, true); assert.equal(f.requests.length, 1);
    f.resume(); assert.equal(f.requests.length, 2, "call hook without guard change resumes once");
    old.status = 200; old.responseText = JSON.stringify(payload); old.readyState = 4;
    stale(); assert.equal(f.c.notice, null);
    f.c.pendingRequest.complete(409, {});
    assert.equal(f.c.reconnect.running, false, "hangup/re-arm race must not deafen for 30 seconds");
    for (let attempt = 0; attempt < 5; attempt++) {
        f.resume(); f.c.pendingRequest.complete(409, {});
    }
    assert.equal(f.c.resume.running, false, "busy retries are bounded");
    assert.equal(f.c.reconnect.running, true);
    f.c.blocked = true; f.c.updateGuard();
    assert.equal(f.c.reconnect.running, false);
    f.c.blocked = false; f.c.updateGuard(); f.resume();
    assert.equal(f.c.resumeAttempts, 5);
    f.c.pendingRequest.complete(200, payload); assert.equal(f.c.notice.title, payload.title);
    f.c.shutdown(); assert.equal(f.c.resume.running, false);
}
{
    const f = fixture(); f.c.initialize();
    f.audio.onEnable = () => f.c.preempt();
    f.c.pendingRequest.complete(200, payload);
    assert.equal(f.c.notice, null); assert.equal(f.requests.length, 1,
        "preemption during receive must not immediately re-arm old generation");
    assert.equal(f.c.resume.running, true); f.c.shutdown();
}
{
    const f = fixture(); f.c.initialize(); f.requests[0].complete(200, payload);
    let noticeAtSend, runningAtSend;
    // Observe state at the acknowledgement API boundary, not just after the call.
    const original = f.c.sendAcknowledgement;
    f.c.sendAcknowledgement = c => {
        noticeAtSend = f.c.notice; runningAtSend = f.c.effects.running; original(c);
    };
    f.c.acknowledge(); assert.equal(noticeAtSend, null); assert.equal(runningAtSend, false);
    const ack = f.requests.at(-1); const url = new URL(ack.url);
    assert.equal(url.pathname, "/homeassistant");
    assert.equal(url.searchParams.get("domain"), "c300x");
    assert.equal(url.searchParams.get("service"), "toggle");
    assert.equal(url.searchParams.get("entities"), "notification.warning_notice");
    assert.deepEqual(JSON.parse(url.searchParams.get("option")), {revision: payload.revision, action_id: null});
    assert.equal(f.c.ackTimeout.running, true); assert.equal(f.c.pendingRequest, f.requests[1]);
    ack.complete(500, {}); assert.equal(f.c.ackTimeout.running, false);
    assert.equal(f.c.notice, null, "ack delivery failure must not resume effects");
    const n = f.requests.length; f.c.acknowledge(); assert.equal(f.requests.length, n);
    f.c.shutdown(); assert.equal(f.requests[1].aborted, true);
}
{
    const f = fixture(); f.c.initialize(); f.c.sendAcknowledgement(payload);
    const ack = f.c.ackRequest; f.c.abortAcknowledgement(); assert.equal(ack.aborted, true);
    f.c.sendAcknowledgement(payload); const pendingAck = f.c.ackRequest;
    const staleGet = f.c.pendingRequest.onreadystatechange;
    f.c.shutdown(); assert.equal(pendingAck.aborted, true);
    const n = f.requests.length; staleGet(); f.c.waitForCommand(); f.c.sendAcknowledgement(payload);
    f.c.preempt(); f.c.userInteraction(); f.c.acknowledge();
    assert.equal(f.requests.length, n); assert.equal(f.c.controller, null);
    assert.equal(f.c.effects.running, false); assert.equal(f.c.reconnect.running, false);
}

assert.match(qml, /property bool blocked: true/);
assert.match(qml, /onBlockedChanged: updateGuard\(\)/);
assert.match(qml, /onVisibleChanged: updateGuard\(\)/);
assert.match(qml, /onStateChangedInt: if \(root.controller\) root.controller.screenChanged\(\)/);
assert.match(qml, /id: reconnect; interval: 30000; repeat: false/);
assert.match(qml, /id: resume; interval: 100; repeat: false/);
assert.match(qml, /id: ackTimeout; interval: 10000; repeat: false/);
assert.match(qml, /onPressed: root.userInteraction\(\)/);
assert.match(qml, /onClicked: root.acknowledge\(\)/);
assert.match(qml, /Component.onDestruction: shutdown\(\)/);
assert.equal((qml.match(/textFormat: Text.PlainText/g) || []).length, 4);
assert.doesNotMatch(qml + js, /ringtoneManager|ForcedNormal|enableState\(ScreenState.ScreenOff\)|beepEnabled\s*=|setVolume|setInterval|Api\./);
assert.equal((qml.match(/disableState\(ScreenState.Normal\)/g) || []).length, 1);
console.log("Alert QML adapter checks passed (XHR/firmware mocks, not physical confirmation).");
