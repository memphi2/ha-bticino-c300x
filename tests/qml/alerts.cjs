const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../device_qml/js/c300x_alerts.js"), "utf8");
const logic = vm.createContext({});
vm.runInContext(source.replace(/^\.pragma library\s*/, ""), logic);
const BASE = 1800000000000;
let sequence = 0;
function command(overrides = {}) {
    const hex = (++sequence).toString(16).padStart(32, "0");
    return {id: hex, notification_id: "test_notice", revision: hex, severity: "warning",
        title: "Notice", message: "Message", wake_duration: 30, sound_duration: 30,
        expires_in: 3600, remaining_ms: 5000, expires: BASE + 5000,
        message_expires: BASE + 3600000, ...overrides};
}
function fixture(options = {}) {
    const f = {now: BASE, state: 0, blocked: false, audioBusy: false, visible: null,
        beeps: [], wakes: [], releases: [], acks: [], order: [], ...options};
    const io = {
        now: () => f.now, blocked: () => f.blocked, screen: () => f.state,
        off: 0, normal: 2, idleInterval: () => 20000,
        simulateClick() {
            f.wakes.push(f.now);
            if (f.wakeCallback) f.wakeCallback();
            else if (!f.asyncWake && f.state === 0) { f.state = 2; f.c.screenChanged(); }
        },
        releaseNormal() { f.releases.push(f.now); f.state = 0; f.c.screenChanged(); },
        soundReady: () => !f.audioBusy,
        beep(guard) {
            if (f.beforeBeep) f.beforeBeep();
            if (!guard()) return false;
            f.beeps.push(f.now); return true;
        },
        show(c) { f.visible = c; }, hide() { f.visible = null; f.order.push("hide"); },
        ack(c) { f.acks.push(c); f.order.push("ack"); }
    };
    f.c = logic.createController(io);
    f.step = (ms = 250) => { f.now += ms; f.c.tick(); };
    f.advance = ms => { for (let t = 0; t < ms; t += 250) f.step(); };
    return f;
}

// Flat protocol validation is strict, including all duration/deadline boundaries.
assert.ok(logic.validate(command(), BASE));
assert.equal(logic.validate(command(), NaN), null);
for (const field of ["id", "notification_id", "revision", "severity", "title", "message", "wake_duration",
    "sound_duration", "expires_in", "remaining_ms", "expires", "message_expires"]) {
    const c = command(); delete c[field]; assert.equal(logic.validate(c, BASE), null, field);
}
for (const overrides of [
    {extra: true}, {id: "x"}, {revision: "A".repeat(32)}, {notification_id: "Upper"},
    {notification_id: "a".repeat(65)}, {severity: "urgent"}, {title: "t".repeat(81)},
    {message: "m".repeat(501)}, {title: 123}, {message: null}, {message: "\u0000"},
    {message: "\ud800"}, {message: "\udc00"}, {expires: BASE}, {message_expires: BASE},
    {remaining_ms: 0}, {remaining_ms: 5001}, {expires_in: 0}, {expires_in: 604801},
    {wake_duration: -1}, {sound_duration: 301}, {wake_duration: 0.5}, {sound_duration: "30"},
    {wake_duration: true}, {expires: Infinity}, {remaining_ms: NaN}
]) assert.equal(logic.validate(command(overrides), BASE), null, JSON.stringify(overrides));
assert.ok(logic.validate(command({title: "\ud83d\ude00".repeat(80), message: "\ud83d\ude00".repeat(500)}), BASE));
assert.ok(logic.validate(command({wake_duration: 0, sound_duration: 300, expires_in: 604800}), BASE));

{
    const f = fixture(); assert.equal(f.c.receive(command()), true);
    f.advance(30000);
    assert.equal(f.beeps.length, 30);
    assert.ok(f.beeps.every((time, i) => !i || time - f.beeps[i - 1] >= 1000));
    assert.equal(f.releases.length, 1); assert.equal(f.visible, null);
    const calls = f.beeps.length + f.wakes.length + f.releases.length;
    f.advance(30000); assert.equal(f.beeps.length + f.wakes.length + f.releases.length, calls);
}
{
    const f = fixture({state: 2}); f.c.receive(command({severity: "info", sound_duration: 0}));
    f.advance(30000); assert.equal(f.beeps.length, 0); assert.equal(f.releases.length, 0);
    assert.equal(f.state, 2, "pre-existing Normal never owned");
}
{
    const f = fixture(); f.c.receive(command({wake_duration: 0, sound_duration: 0}));
    f.advance(30000); assert.equal(f.wakes.length, 0); assert.equal(f.beeps.length, 0);
    assert.equal(f.releases.length, 0); assert.equal(f.visible, null);
}
{
    const f = fixture(); f.c.receive(command({wake_duration: 1, sound_duration: 3}));
    f.advance(4000); assert.equal(f.releases.length, 1); assert.equal(f.beeps.length, 3,
        "own screen release does not truncate independent sound budget");
}
{
    const f = fixture(); const c = command({wake_duration: 300, sound_duration: 300});
    f.c.receive(c); f.advance(300000);
    assert.equal(f.visible, null); assert.equal(f.beeps.length, 300); assert.equal(f.releases.length, 1);
}
{
    const f = fixture(); f.c.receive(command({message_expires: BASE + 1000})); f.advance(1000);
    assert.equal(f.visible, null); assert.equal(f.beeps.length, 1); assert.equal(f.releases.length, 1);
}
{
    const f = fixture(); f.c.receive(command()); f.advance(500);
    f.c.acknowledge(); const wakes = f.wakes.length; f.advance(40000);
    assert.equal(f.acks.length, 1); assert.deepEqual(f.order, ["hide", "ack"]);
    assert.equal(f.releases.length, 0); assert.equal(f.wakes.length, wakes);
    assert.equal(f.beeps.length, 1); f.c.acknowledge(); assert.equal(f.acks.length, 1);
}
for (const cancel of ["preempt", "destroy"]) {
    const f = fixture(); const c = command(); f.c.receive(c); f.c[cancel]();
    f.state = 4; f.c.screenChanged(); f.advance(40000);
    assert.equal(f.releases.length, 0, cancel); assert.equal(f.beeps.length, 1, cancel);
    assert.equal(f.visible, null); assert.equal(f.c.receive(c), false, "no replay after " + cancel);
}
{
    const f = fixture(); f.c.receive(command()); f.c.userInteraction(); f.advance(40000);
    assert.equal(f.releases.length, 0); assert.equal(f.wakes.length, 1); assert.equal(f.beeps.length, 1);
}
{
    const f = fixture({blocked: true}); const c = command(); assert.equal(f.c.receive(c), false);
    f.blocked = false; assert.equal(f.c.receive(c), false); assert.equal(f.wakes.length, 0);
}
{
    const f = fixture(); f.c.receive(command()); f.blocked = true; f.step(); f.blocked = false;
    f.advance(40000); assert.equal(f.releases.length, 0); assert.equal(f.visible, null);
}
{
    const f = fixture({asyncWake: true}); f.c.receive(command()); f.c.preempt();
    f.state = 2; f.c.screenChanged(); f.advance(40000);
    assert.equal(f.releases.length, 0, "late native wake never resurrects canceled generation");
}
for (const mode of ["replace", "preempt"]) {
    const f = fixture({asyncWake: true}); f.c.receive(command());
    if (mode === "preempt") f.c.preempt();
    f.c.receive(command({severity: "error"})); assert.equal(f.wakes.length, 1);
    f.state = 2; f.c.screenChanged(); f.advance(30000);
    assert.equal(f.releases.length, 0, "old wake response never assigned to newer generation: " + mode);
}
{
    const f = fixture({asyncWake: true}); f.c.receive(command({remaining_ms: 1000})); f.advance(1000);
    f.state = 2; f.c.screenChanged(); f.advance(30000); assert.equal(f.releases.length, 0);
}
{
    const f = fixture({asyncWake: true}); f.c.receive(command()); f.now += 100;
    f.state = 2; f.c.screenChanged(); f.advance(30000); assert.equal(f.releases.length, 1);
}
{
    const f = fixture(); f.wakeCallback = () => { f.c.preempt(); f.state = 4; };
    f.c.receive(command()); f.advance(30000); assert.equal(f.beeps.length, 0); assert.equal(f.releases.length, 0);
}
{
    const f = fixture(); f.beforeBeep = () => f.c.preempt(); f.c.receive(command());
    assert.equal(f.beeps.length, 0, "reentrant takeover before beep");
}
{
    const f = fixture(); let attempts = 0;
    f.beforeBeep = () => { attempts++; throw Error("firmware error"); };
    f.c.receive(command()); f.advance(30000); assert.equal(attempts, 1, "no repeated failed audio calls");
}
{
    const f = fixture(); f.wakeCallback = () => { throw Error("wake failed"); };
    assert.equal(f.c.receive(command()), false); f.advance(30000);
    assert.equal(f.visible, null); assert.equal(f.beeps.length, 0);
}
{
    const f = fixture({audioBusy: true}); f.c.receive(command()); f.advance(3000);
    assert.equal(f.beeps.length, 0); f.audioBusy = false; f.step(); assert.equal(f.beeps.length, 1);
    f.audioBusy = true; f.advance(30000); assert.equal(f.beeps.length, 1);
}
{
    const f = fixture({audioBusy: true}); f.c.receive(command()); f.advance(5000);
    f.audioBusy = false; f.advance(30000); assert.equal(f.beeps.length, 0, "no first beep after delivery deadline");
}
{
    const f = fixture(); f.beforeBeep = () => { f.now += 5001; };
    f.c.receive(command()); assert.equal(f.beeps.length, 0, "check delivery deadline after reentrant flag enable");
}
{
    const f = fixture(); const low = command({severity: "info", sound_duration: 0});
    const high = command({severity: "error"}); f.c.receive(low); f.advance(500);
    f.c.receive(high); assert.equal(f.visible.id, high.id); assert.equal(f.releases.length, 0);
    assert.equal(f.c.receive(command({severity: "warning"})), false);
    f.advance(30000); assert.equal(f.releases.length, 1, "replacement inherits only owned lease");
}
{
    const f = fixture(); f.c.receive(command()); const c = command(); f.c.receive(c);
    assert.equal(f.beeps.length, 1, "replacement cannot bypass beep spacing");
    assert.equal(f.c.receive({...c, id: "f".repeat(32)}), false, "same revision cannot replay");
}
{
    const f = fixture(); f.c.receive(command()); f.state = 4; f.c.screenChanged(); f.advance(30000);
    assert.equal(f.releases.length, 0, "unexpected screen owner retained"); assert.equal(f.beeps.length, 1);
}
{
    const f = fixture(); f.c.receive(command()); f.now -= 1; f.c.tick();
    assert.equal(f.visible, null); assert.equal(f.releases.length, 0, "clock rollback cancels, never extends");
}
{
    const f = fixture(); f.c.receive(command()); for (let i = 0; i < 120; i++) f.c.tick();
    assert.equal(f.visible, null, "stalled clock cannot extend lifetime indefinitely");
}
{
    const f = fixture(); f.c.receive(command()); f.now += 3600000; f.c.tick();
    assert.equal(f.visible, null); assert.equal(f.beeps.length, 1, "no catch-up beep bursts");
}
console.log("Alert state-machine checks passed (host simulation, not hardware proof).");
