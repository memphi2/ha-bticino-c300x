const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const qml = fs.readFileSync(path.join(__dirname, "../../device_qml/C300XAlerts.qml"), "utf8");
const js = fs.readFileSync(path.join(__dirname, "../../device_qml/js/c300x_alerts.js"), "utf8");
const apiSource = fs.readFileSync(path.join(__dirname, "../../device_qml/js/c300x_ha.js"), "utf8");
const i18n = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, "../../device_qml/js/c300x_i18n.js"), "utf8")
    .replace(/^\.pragma library\s*/, ""), i18n);
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
function fixture(sharedEngine) {
    const requests = [];
    const events = [];
    let now = BASE;
    class Clock extends Date { getTime() { return now; } static now() { return now; } }
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
            this.method = method; this.url = url; this.readyState = 1; assert.notEqual(async, false);
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
    const engine = sharedEngine || vm.createContext({});
    if (!sharedEngine) vm.runInContext(js.replace(/^\.pragma library\s*/, ""), engine);
    const api = vm.createContext({XMLHttpRequest: XHR, Date: Clock});
    vm.runInContext(apiSource.replace(/^\.pragma library\s*/, ""), api);
    const context = vm.createContext({
        blocked: false, stopped: false, visible: true, notice: null,
        pollGeneration: 0, resumeAttempts: 5, runtimeGeneration: 0, acknowledging: false, ackFailed: false,
        XMLHttpRequest: XHR, Alerts: engine, Api: api, I18n: i18n, uiLanguage: "en",
        Date: Clock,
        effects: timer(), reconnect: timer(), resume: timer(), ackTimeout: timer(), messageScroll: {contentY: 77},
        ScreenState: {ScreenOff: 0, Normal: 2}, AudioState: {Idle: 0, Beep: 1, RingtoneMute: 4},
        global: {audioState: audio, screenState: {state: 2, screensaverInterval: 20000,
            simulateClick() { events.push("wake"); }, disableState() { events.push("release"); }},
            beep() { events.push("beep"); if (context.beepThrows) throw Error("beep failed"); }}
    });
    context.root = context;
    // Node does not implement Qt 4 QVariant conversion. Fail closed if any
    // runtime handle is ever stored on the QML owner instead of the JS module.
    for (const name of ["controller", "pendingRequest", "ackRequest", "ackToken"]) {
        Object.defineProperty(context, name, {
            get() { throw Error("Qt 4 cannot retain " + name + " in a QML variant"); },
            set() { throw Error("Qt 4 cannot retain " + name + " in a QML variant"); }
        });
    }
    vm.runInContext(methods, context);
    return {c: context, requests, events, audio, engine, api,
        advance(ms) { now += ms; },
        get runtime() { return vm.runInContext("Alerts.runtimeFor(root)", context); },
        resume() { assert.equal(context.resume.running, true); context.resume.running = false; context.waitForCommand(); },
        failOpen(value) { failOpen = value; }, failSend(value) { failSend = value; }};
}

{
    const f = fixture();
    const translations = {
        de: ["Info", "Warnung", "Fehler", "Gelesen"],
        en: ["Info", "Warning", "Error", "Mark read"],
        it: ["Informazione", "Avviso", "Errore", "Letto"],
        fr: ["Information", "Avertissement", "Erreur", "Lu"]
    };
    for (const [language, labels] of Object.entries(translations)) {
        f.c.uiLanguage = language;
        for (const [index, severity] of ["info", "warning", "error"].entries()) {
            f.c.notice = {...payload, severity};
            assert.equal(f.c.severityText(), (index === 0 ? "i  " : "!  ") + labels[index]);
        }
        assert.equal(f.c.uiText("dismiss_notification"), labels[3]);
    }
    f.c.notice = null;
    assert.equal(f.c.severityText(), "");
    assert.match(qml, /property string uiLanguage: trsl.language/);
    assert.match(qml, /property string acknowledgeLabel: uiText\("dismiss_notification"\)/);
    assert.match(qml, /text: root.severityText\(\)/);
}

// Lifecycle hooks can fire before Component.onCompleted or after destruction.
// The .pragma library must retain identities but never retain a dead owner.
{
    const f = fixture();
    assert.equal(f.c.canListen(), false);
    assert.equal(f.c.canConnect(), false);
    f.c.updateGuard(); f.c.waitForCommand(); f.c.preempt();
    f.c.screenChanged(); f.c.tick(); f.c.acknowledge();
    f.c.sendAcknowledgement(payload);
    assert.equal(f.requests.length, 0);
    f.c.initialize();
    const runtime = f.runtime;
    f.c.initialize();
    assert.equal(f.runtime, runtime);
    assert.equal(f.requests.length, 1, "initialization must be idempotent");
    const other = fixture(f.engine); other.c.initialize();
    assert.notEqual(other.runtime, runtime);
    const otherRequest = other.runtime.pendingRequest;
    f.c.shutdown(); f.c.shutdown(); f.c.initialize();
    assert.equal(f.runtime, null);
    assert.equal(f.engine.runtimes.length, 1);
    assert.equal(other.runtime.pendingRequest, otherRequest);
    assert.equal(otherRequest.aborted, false);
    other.c.shutdown();
    assert.equal(f.engine.runtimes.length, 0, "destroy must release owner and closures");
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
    assert.equal(f.requests.length, 1); assert.equal(f.runtime.pendingRequest, null);
    assert.equal(f.c.reconnect.running, true); assert.equal(f.c.notice, null);
    f.c.waitForCommand(); assert.equal(f.requests.length, 2); f.c.shutdown();
    assert.equal(f.c.reconnect.running, false);
}
for (const blocked of [false, true]) {
    for (const fault of ["failOpen", "failSend"]) {
        const f = fixture(); f.c.blocked = blocked; f[fault](true); f.c.initialize();
        assert.equal(f.runtime.pendingRequest, null); assert.equal(f.c.reconnect.running, true);
        assert.equal(f.requests[0].aborted, true); f.c.shutdown();
    }
}
for (const guard of ["blocked", "visible"]) {
    const f = fixture(); f.c[guard] = guard === "blocked"; f.c.initialize();
    assert.equal(f.c.canListen(), false); assert.equal(f.c.canConnect(), true);
    assert.equal(f.requests.length, 1, "protected and hidden roots advertise presence");
    const initial = f.runtime.pendingRequest, initialCallback = initial.onreadystatechange;
    assert.equal(initial.url, "http://127.0.0.1:8090/ui/alerts/next?protected=1");
    assert.equal(initial.method, "GET"); assert.equal(initial.headers["X-C300X-GUI"], "alerts-v1");
    f.c.waitForCommand(); assert.equal(f.requests.length, 1, "one sleeping protected GET");
    for (const name of ["effects", "resume", "reconnect", "ackTimeout"]) assert.equal(f.c[name].running, false);
    f.c[guard] = guard !== "blocked"; f.c.updateGuard();
    assert.equal(initial.aborted, true);
    assert.equal(f.requests.length, 1, "guard clear yields for socket teardown");
    f.resume(); assert.equal(f.requests.length, 2);
    const old = f.runtime.pendingRequest, stale = old.onreadystatechange;
    assert.equal(old.url, "http://127.0.0.1:8090/ui/alerts/next");
    f.c[guard] = guard === "blocked"; f.c.updateGuard();
    assert.equal(old.aborted, true); assert.equal(f.runtime.pendingRequest, null);
    assert.equal(f.c.resume.running, true); assert.equal(f.c.reconnect.running, false);
    f.resume(); assert.equal(f.requests.length, 3);
    const protectedPoll = f.runtime.pendingRequest;
    assert.equal(protectedPoll.url, initial.url);
    old.status = 200; old.responseText = JSON.stringify(payload); old.readyState = 4;
    stale();
    assert.equal(f.runtime.pendingRequest, protectedPoll, "old safe callback cannot steal protected listener");
    assert.equal(f.c.notice, null);
    f.c[guard] = guard !== "blocked"; f.c.updateGuard(); f.resume();
    assert.equal(protectedPoll.aborted, true);
    const current = f.runtime.pendingRequest;
    assert.equal(current.url, old.url);
    initial.status = 200; initial.responseText = JSON.stringify(payload); initial.readyState = 4;
    initialCallback();
    assert.equal(f.runtime.pendingRequest, current, "old protected callback cannot steal safe listener");
    stale();
    assert.equal(f.runtime.pendingRequest, current, "old callback cannot steal resumed listener");
    assert.equal(f.c.notice, null); assert.equal(f.events.includes("wake"), false);
    assert.equal(f.events.includes("beep"), false);
    current.complete(200, payload); assert.equal(f.c.notice.title, payload.title);
    f.c.shutdown();
}

// Transport EOF/errors clear the protected slot and retry only after backoff.
for (const status of [0, 500, 503]) {
    const f = fixture(); f.c.blocked = true; f.c.initialize();
    f.runtime.pendingRequest.complete(status, {});
    assert.equal(f.runtime.pendingRequest, null); assert.equal(f.c.reconnect.running, true);
    assert.equal(f.c.resume.running, false); assert.deepEqual(f.events, ["send"]);
    f.c.waitForCommand();
    assert.equal(f.runtime.pendingRequest.url, "http://127.0.0.1:8090/ui/alerts/next?protected=1");
    assert.equal(f.c.reconnect.running, false); f.c.shutdown();
}

// Even a valid command returned illegally on a protected GET must be ignored,
// including when the guard has cleared before its change handler executes.
for (const guard of ["blocked", "visible"]) {
    for (const clearGuard of [false, true]) {
        for (const body of [payload, "invalid json", "x".repeat(16385)]) {
            const f = fixture(); f.c[guard] = guard === "blocked"; f.c.initialize();
            f.runtime.controller.receive = () => assert.fail("protected request dispatched a command");
            if (clearGuard) f.c[guard] = guard !== "blocked";
            f.runtime.pendingRequest.complete(200, body);
            assert.equal(f.runtime.pendingRequest, null);
            assert.equal(f.c.notice, null); assert.deepEqual(f.events, ["send"]);
            assert.equal(f.requests.length, 1, "unexpected protected response cannot spin");
            assert.equal(f.c.reconnect.running, true);
            assert.equal(f.c.resume.running, false); assert.equal(f.c.effects.running, false);
            f.c.shutdown();
        }
    }
}

for (const guard of ["blocked", "visible"]) {
    const f = fixture(); f.c[guard] = guard === "blocked"; f.c.initialize();
    const old = f.runtime.pendingRequest;
    f.c.preempt(); assert.equal(old.aborted, true);
    f.resume();
    for (let attempt = 0; attempt < 6; attempt++) {
        assert.equal(f.runtime.pendingRequest.url, "http://127.0.0.1:8090/ui/alerts/next?protected=1");
        f.runtime.pendingRequest.complete(409, {});
        if (attempt < 5) {
            assert.equal(f.c.reconnect.running, false);
            f.resume();
        }
    }
    assert.equal(f.c.resume.running, false, "protected busy retries are also bounded");
    assert.equal(f.c.reconnect.running, true);
    f.c.waitForCommand();
    const sleeping = f.runtime.pendingRequest, count = f.requests.length;
    f.advance(600000); f.c.waitForCommand();
    assert.equal(f.requests.length, count);
    for (const name of ["effects", "resume", "reconnect", "ackTimeout"]) assert.equal(f.c[name].running, false);
    f.c.shutdown();
    assert.equal(sleeping.aborted, true); assert.equal(f.c.canConnect(), false);
    f.c.preempt(); f.c.updateGuard(); f.c.waitForCommand();
    assert.equal(f.requests.length, count); assert.equal(f.c.resume.running, false);
}
{
    const f = fixture(); f.c.initialize(); const old = f.runtime.pendingRequest;
    const stale = old.onreadystatechange;
    f.c.preempt();
    assert.equal(old.aborted, true); assert.equal(f.requests.length, 1);
    f.resume(); assert.equal(f.requests.length, 2, "call hook without guard change resumes once");
    old.status = 200; old.responseText = JSON.stringify(payload); old.readyState = 4;
    stale(); assert.equal(f.c.notice, null);
    f.runtime.pendingRequest.complete(409, {});
    assert.equal(f.c.reconnect.running, false, "hangup/re-arm race must not deafen for 30 seconds");
    for (let attempt = 0; attempt < 5; attempt++) {
        f.resume(); f.runtime.pendingRequest.complete(409, {});
    }
    assert.equal(f.c.resume.running, false, "busy retries are bounded");
    assert.equal(f.c.reconnect.running, true);
    f.c.blocked = true; f.c.updateGuard();
    assert.equal(f.c.reconnect.running, false);
    f.c.blocked = false; f.c.updateGuard(); f.resume();
    assert.equal(f.c.resumeAttempts, 5);
    f.runtime.pendingRequest.complete(200, payload); assert.equal(f.c.notice.title, payload.title);
    f.c.shutdown(); assert.equal(f.c.resume.running, false);
}
{
    const f = fixture(); f.c.initialize();
    f.audio.onEnable = () => f.c.preempt();
    f.runtime.pendingRequest.complete(200, payload);
    assert.equal(f.c.notice, null); assert.equal(f.requests.length, 1,
        "preemption during receive must not immediately re-arm old generation");
    assert.equal(f.c.resume.running, true); f.c.shutdown();
}
{
    const f = fixture(); f.c.initialize(); f.requests[0].complete(200, payload);
    f.api.getJsonShared("/ui/state", () => {}, () => {});
    const read = f.requests.at(-1), count = f.requests.length;
    f.c.acknowledge(); f.c.acknowledge();
    assert.equal(f.requests.length, count, "ack waits for the occupied display slot");
    assert.equal(f.c.acknowledging, true); assert.ok(f.c.notice);
    read.complete(200, {});
    const ack = f.requests.at(-1); const url = new URL(ack.url);
    assert.equal(url.pathname, "/homeassistant");
    assert.equal(url.searchParams.get("domain"), "c300x");
    assert.equal(url.searchParams.get("service"), "toggle");
    assert.equal(url.searchParams.get("entities"), "notification.warning_notice");
    assert.deepEqual(JSON.parse(url.searchParams.get("option")), {revision: payload.revision, action_id: null});
    assert.equal(f.c.ackTimeout.running, true); assert.equal(f.runtime.pendingRequest, f.requests[1]);
    ack.complete(500, {}); assert.equal(f.c.ackTimeout.running, false);
    assert.ok(f.c.notice, "failed ack must not hide the notice");
    assert.equal(f.c.ackFailed, true); assert.equal(f.c.acknowledging, false);
    const n = f.requests.length, effects = f.events.length;
    f.advance(1000); f.c.tick();
    assert.equal(f.requests.length, n, "no automatic retry traffic");
    assert.equal(f.events.length, effects, "no resumed wake or sound");
    f.c.acknowledge(); assert.equal(f.requests.length, n + 1);
    f.requests.at(-1).complete(200, {ok: true});
    assert.equal(f.c.notice, null); assert.equal(f.c.ackFailed, false);
    assert.equal(f.c.effects.running, false);
    f.c.shutdown(); assert.equal(f.requests[1].aborted, true);
}
{
    const f = fixture(); f.c.initialize(); f.requests[0].complete(200, payload); f.c.acknowledge();
    const ack = f.requests.at(-1);
    f.c.finishAcknowledgement(false);
    assert.equal(ack.aborted, false, "retain the shared slot until the sent request finishes");
    f.c.acknowledge(); const pendingAck = f.runtime.ackToken;
    ack.complete(200, {ok: true});
    assert.equal(f.runtime.ackToken, pendingAck, "late success cannot confirm an explicit retry");
    assert.ok(f.c.notice);
    assert.equal(f.c.ackTimeout.running, true);
    const staleGet = f.runtime.pendingRequest.onreadystatechange;
    const sent = f.requests.at(-1);
    f.c.shutdown(); sent.complete(200, {ok: true});
    const n = f.requests.length; staleGet(); f.c.waitForCommand(); f.c.sendAcknowledgement(payload);
    f.c.preempt(); f.c.userInteraction(); f.c.acknowledge();
    assert.equal(f.requests.length, n); assert.equal(f.runtime, null);
    assert.equal(f.c.effects.running, false); assert.equal(f.c.reconnect.running, false);
}

for (const [status, body] of [[503, {ok: true}], [200, {}], [200, null], [200, {ok: false}], [200, "invalid"]]) {
    const f = fixture(); f.c.initialize(); f.requests[0].complete(200, payload);
    f.c.acknowledge(); const count = f.requests.length;
    f.requests.at(-1).complete(status, body);
    assert.equal(f.c.ackFailed, true); assert.ok(f.c.notice);
    assert.equal(f.requests.length, count); assert.equal(f.c.ackTimeout.running, false);
    f.c.shutdown();
}
for (const fault of ["failOpen", "failSend"]) {
    const f = fixture(); f.c.initialize(); f.requests[0].complete(200, payload);
    f[fault](true); f.c.acknowledge();
    assert.ok(f.c.notice); assert.equal(f.c.ackFailed, true);
    f[fault](false);
    const count = f.requests.length;
    f.c.acknowledge();
    assert.equal(f.requests.length, count + 1, "failed transport must release shared slot: " + fault);
    f.requests.at(-1).complete(200, {ok: true});
    assert.equal(f.c.notice, null); f.c.shutdown();
}
for (const cancel of ["preempt", "shutdown", "replace", "timeout", "queue-expiry"]) {
    const f = fixture(); f.c.initialize(); f.requests[0].complete(200, payload);
    f.api.getJsonShared("/ui/state", () => {}, () => {});
    const read = f.requests.at(-1), count = f.requests.length;
    f.c.acknowledge(); assert.equal(f.requests.length, count);
    if (cancel === "replace") {
        f.runtime.pendingRequest.complete(200, {...payload, id: "3".repeat(32), revision: "4".repeat(32)});
    } else if (cancel === "timeout") {
        f.c.finishAcknowledgement(false);
    } else if (cancel === "queue-expiry") {
        f.advance(10001);
    } else {
        f.c[cancel]();
    }
    read.complete(200, {});
    assert.equal(f.requests.filter(r => r.url?.includes("entities=")).length, 0,
        "cancelled or expired queued ack is never sent: " + cancel);
    if (cancel === "timeout" || cancel === "queue-expiry") {
        assert.ok(f.c.notice); assert.equal(f.c.ackFailed, true);
    }
    f.c.shutdown();
}
{
    const f = fixture(); f.c.initialize(); f.requests[0].complete(200, payload); f.c.acknowledge();
    const old = f.requests.at(-1), staleCallback = old.onreadystatechange;
    f.c.visible = false; f.c.updateGuard();
    assert.equal(f.c.notice, null); assert.equal(f.c.acknowledging, false);
    f.c.visible = true; f.c.updateGuard(); f.resume();
    f.runtime.pendingRequest.complete(200, {...payload, id: "3".repeat(32), revision: "4".repeat(32)});
    f.c.acknowledge(); const newToken = f.runtime.ackToken;
    old.complete(200, {ok: true}); staleCallback();
    assert.equal(f.runtime.ackToken, newToken);
    assert.equal(f.c.notice.revision, "4".repeat(32)); assert.equal(f.c.acknowledging, true);
    f.requests.at(-1).complete(200, {ok: true});
    assert.equal(f.c.notice, null); f.c.shutdown();
}
{
    const f = fixture(); f.c.initialize(); f.requests[0].complete(200, payload); f.c.acknowledge();
    // HomeAssistant's runtime stop may abort the shared request. It must not
    // confirm our notice, and the one-shot UI deadline exposes the cancellation.
    f.api.stopDashboardRuntime();
    assert.ok(f.c.notice); assert.equal(f.c.acknowledging, true);
    f.c.finishAcknowledgement(false);
    assert.equal(f.c.ackFailed, true); assert.equal(f.c.acknowledging, false);
    const count = f.requests.length; f.c.tick(); assert.equal(f.requests.length, count);
    f.c.acknowledge(); f.requests.at(-1).complete(200, {ok: true});
    assert.equal(f.c.notice, null); f.c.shutdown();
}
{
    const f = fixture(); f.c.initialize(); f.requests[0].complete(200, payload); f.c.acknowledge();
    const old = f.requests.at(-1);
    f.runtime.pendingRequest.complete(200, {...payload, id: "3".repeat(32), revision: "4".repeat(32)});
    old.complete(200, {ok: true});
    assert.equal(f.c.notice.revision, "4".repeat(32), "old success must not dismiss the replacement alert");
    assert.equal(f.c.acknowledging, false); assert.equal(f.c.ackFailed, false);
    f.c.shutdown();
}
{
    const f = fixture(); f.c.initialize(); f.requests[0].complete(200, payload);
    for (let i = 0; i <= f.api.FORWARD_QUEUE_LIMIT; i++) f.api.getJson("/ui/state", () => {}, () => {});
    const count = f.requests.length;
    f.c.acknowledge();
    assert.equal(f.c.acknowledging, false); assert.equal(f.c.ackFailed, true); assert.ok(f.c.notice);
    assert.equal(f.requests.length, count, "full queue does not start another transport");
    f.c.shutdown(); f.api.stopDashboardRuntime();
}

assert.match(qml, /property bool blocked: true/);
assert.match(qml, /onBlockedChanged: updateGuard\(\)/);
assert.match(qml, /onVisibleChanged: updateGuard\(\)/);
assert.match(qml, /onStateChangedInt: root.screenChanged\(\)/);
assert.doesNotMatch(qml, /property\s+(?:variant|var)\s+(?:controller|pendingRequest|ackRequest)\b/);
assert.match(qml, /id: reconnect; interval: 30000; repeat: false/);
assert.match(qml, /id: resume; interval: 100; repeat: false/);
assert.match(qml, /id: ackTimeout; interval: 10000; repeat: false/);
assert.match(qml, /onPressed: root.userInteraction\(\)/);
assert.match(qml, /onClicked: root.acknowledge\(\)/);
assert.match(qml, /Component.onDestruction: shutdown\(\)/);
assert.equal((qml.match(/textFormat: Text.PlainText/g) || []).length, 4);
assert.doesNotMatch(qml + js, /ringtoneManager|ForcedNormal|enableState\(ScreenState.ScreenOff\)|beepEnabled\s*=|setVolume|setInterval/);
assert.match(qml, /onTriggered: root.finishAcknowledgement\(false\)/);
assert.match(qml, /enabled: !root.acknowledging/);
assert.match(qml, /root.ackFailed \? root.uiText\("alert_ack_retry"\)/);
assert.equal((qml.match(/disableState\(ScreenState.Normal\)/g) || []).length, 1);

// Execute the actual outside-panel handler: it must release the lease without
// accepting the press or dismissing the message.
{
    const handler = qml.match(/    MouseArea \{\n        anchors.fill: parent\n        enabled: !!root.notice && !root.blocked\n        onPressed: \{([\s\S]*?)\n        }\n    }/);
    assert.ok(handler, "full-screen observer is a sibling behind the panel");
    assert.ok(handler.index < qml.indexOf("id: panel"));
    const f = fixture(); f.c.initialize(); f.requests[0].complete(200, payload);
    const mouse = {accepted: true}; f.c.mouse = mouse;
    vm.runInContext(handler[1], f.c);
    assert.equal(mouse.accepted, false, "underlying item must receive the same press");
    assert.equal(f.c.notice.title, payload.title);
    const calls = f.events.length;
    for (let i = 0; i < 120; i++) f.c.tick();
    assert.equal(f.events.slice(calls).some(e => ["wake", "beep", "release"].includes(e)), false);
    f.c.shutdown();
}
console.log("Alert QML adapter checks passed (XHR/firmware mocks, not physical confirmation).");
