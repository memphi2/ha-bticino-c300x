// ES5 fixture: actual production controller is prepended by the Python probe.
// Screen/audio/timing boundaries are explicit substitutes, not hardware proof.
var BASE = 1800000000000;
var sequence = 0;
function check(value, message) { if (!value) throw new Error(message); }
function command(duration) {
    var id = ("00000000000000000000000000000000" + (++sequence).toString(16)).slice(-32);
    return {id: id, notification_id: "probe", revision: id, severity: "warning",
        title: "Notice", message: "Message", wake_duration: duration, sound_duration: duration,
        expires_in: 3600, remaining_ms: 5000, expires: BASE + 5000,
        message_expires: BASE + 3600000};
}
function fixture(asyncWake) {
    var f = {now: BASE, state: 0, blocked: false, beeps: 0, wakes: 0, releases: 0, visible: null};
    f.controller = createController({
        now: function() { return f.now; }, blocked: function() { return f.blocked; },
        screen: function() { return f.state; }, off: 0, normal: 2,
        idleInterval: function() { return 20000; },
        simulateClick: function() {
            f.wakes++;
            if (!asyncWake && f.state === 0) { f.state = 2; f.controller.screenChanged(); }
        },
        releaseNormal: function() { f.releases++; f.state = 0; f.controller.screenChanged(); },
        soundReady: function() { return true; },
        beep: function(guard) {
            if (f.beforeBeep) f.beforeBeep();
            if (!guard()) return false;
            f.beeps++; return true;
        },
        show: function(c) { f.visible = c; }, hide: function() { f.visible = null; },
        ack: function() { f.controller.acknowledged(true); }
    });
    f.advance = function(milliseconds) {
        for (var t = 0; t < milliseconds; t += 250) { f.now += 250; f.controller.tick(); }
    };
    return f;
}
var durations = [0, 30, 300];
for (var i = 0; i < durations.length; i++) {
    var f = fixture(false), duration = durations[i];
    check(f.controller.receive(command(duration)), "accept duration " + duration);
    f.advance(Math.max(30, duration) * 1000);
    check(f.beeps === duration && f.releases === (duration ? 1 : 0), "effect budgets " + duration);
    check(f.visible === null, "visible expiry " + duration);
    f.advance(10000);
    check(f.beeps === duration, "no effects after expiry");
}
var preemptions = ["preempt", "userInteraction", "destroy"];
for (var p = 0; p < preemptions.length; p++) {
    var f = fixture(false);
    f.controller.receive(command(30));
    f.controller[preemptions[p]]();
    f.advance(31000);
    check(f.beeps === 1 && f.releases === 0, "no late effects: " + preemptions[p]);
}
var delayed = fixture(true);
delayed.controller.receive(command(30));
delayed.controller.preempt();
delayed.controller.receive(command(30));
delayed.state = 2;
delayed.controller.screenChanged();
delayed.advance(31000);
check(delayed.wakes === 1 && delayed.releases === 0, "old wake cannot own new alert");
var reentrant = fixture(false);
reentrant.beforeBeep = function() { reentrant.controller.preempt(); };
reentrant.controller.receive(command(30));
check(reentrant.beeps === 0, "synchronous preemption blocks beep");
var protectedPage = fixture(false);
protectedPage.blocked = true;
check(!protectedPage.controller.receive(command(30)), "protected page rejects alert");
check(protectedPage.beeps === 0 && protectedPage.wakes === 0, "protected page no effects");
var clock = fixture(false);
clock.controller.receive(command(30));
clock.now--;
clock.controller.tick();
clock.advance(31000);
check(clock.visible === null && clock.beeps === 1 && clock.releases === 0, "clock rollback cancels");
var owned = fixture(false);
owned.state = 2;
owned.controller.receive(command(30));
owned.advance(31000);
check(owned.releases === 0, "preexisting screen lease untouched");
"ALERT_LIFECYCLE_OK";
