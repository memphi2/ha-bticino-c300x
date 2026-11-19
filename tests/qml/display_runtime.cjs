const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../..");
const jsRoot = process.env.C300X_DEVICE_JS_ROOT || path.join(root, "device_qml/js");
const alarmQml = fs.readFileSync(path.join(root, "device_qml/Alarm.qml"), "utf8");
const dashboardQml = fs.readFileSync(path.join(root, "device_qml/HomeAssistant.qml"), "utf8");

function runtime(name = "c300x_ha.js") {
    let now = 100000;
    const sent = [], timers = [];
    function timer(handler = () => {}) {
        const t = {interval: 0, running: false, deadline: 0,
            restart() { this.running = true; this.deadline = now + this.interval; },
            stop() { this.running = false; },
            destroy() { this.stop(); },
            triggered: {connect(fn) { handler = fn; }},
            // Qt 4.8 order: the handler runs first, then the one-shot timer is marked stopped.
            fire() { handler(); this.running = false; if (this.stopped) this.stopped(); },
        };
        timers.push(t);
        return t;
    }
    function advance(ms) {
        const end = now + ms;
        let firings = 0;
        while (true) {
            const next = timers.filter(t => t.running && t.deadline <= end)
                .sort((a, b) => a.deadline - b.deadline)[0];
            if (!next) break;
            assert.ok(++firings < 100, "no zero-delay timer loop");
            now = next.deadline;
            next.fire();
        }
        now = end;
    }
    function Request() { this.readyState = 0; this.status = 0; }
    Request.prototype.open = function(method, url) { this.url = url; this.readyState = 1; };
    Request.prototype.send = function() { sent.push(this); };
    Request.prototype.abort = function() {
        this.aborted = true;
        this.finish(0, "");
    };
    Request.prototype.finish = function(status, data) {
        this.status = status;
        this.responseText = typeof data === "string" ? data : JSON.stringify(data);
        this.readyState = 4;
        this.onreadystatechange();
    };
    const clock = {now: () => now};
    const Api = vm.createContext({Date: clock, XMLHttpRequest: Request, Qt: {
        createQmlObject() {
            assert.fail("Qt 4 cannot create QML objects from a shared script library");
        },
    }});
    vm.runInContext(fs.readFileSync(path.join(jsRoot, name), "utf8")
        .replace(/^\.pragma library\s*/, ""), Api);
    function request(suffix) {
        const req = sent.find(r => r.readyState !== 4 && r.url.includes(suffix));
        assert.ok(req, "pending request for " + suffix);
        return req;
    }
    return {Api, sent, timers, timer, advance, request, clock};
}

function methods(qml, values) {
    values.feedbackColorsEnabled = true;
    values.c300xDisplayPreferences = {load() {}};
    const p = vm.createContext(values);
    p.page = p;
    vm.runInContext([...qml.matchAll(/^    function [\s\S]*?^    }/gm)]
        .map(m => m[0]).join("\n"), p);
    return p;
}

function alarm(r) {
    const noop = () => {};
    return methods(alarmQml, {Api: r.Api, Date: r.clock, I18n: {text: (_, key) => key},
        uiLanguage: "en", pinCode: "", pinRequested: false, alarmOnline: true,
        alarmConfigured: true, alarmRawState: "disarmed", alarmCommands: ["arm_home", "disarm"],
        alarmCommandDetails: [{command: "arm_home"}, {command: "disarm", code_required: true}],
        alarmOpenSensors: [], alarmOpenSensorCount: 0, alarmDelayRemaining: 0,
        selectedCommand: "disarm", selectedCommandReady: true, selectedCommandBlockedBySensors: false,
        selectedCommandStatus: "", bypassOffered: false, activeFeedbackCommand: "", commandFeedback: "",
        commandFeedbackColor: "", commandPending: false, commandInFlight: false, quickActionPending: false,
        quickActionGeneration: 0, runtimeGeneration: 0, statusGeneration: 0, lastStatusRefreshMs: 0,
        alarmPageItem: {domain: "c300x", entity_id: "switch.porch", kind: "switch"},
        pageActive: true, watchFailed: false, preventReturnToHomepage: false,
        status: {}, alarmState: {}, activeSince: {},
        modeFeedbackTimer: {restart: noop}, delayedStatusRefresh: {restart: noop, stop: noop},
    });
}

function payload(p, state = "armed_home") {
    return {alarm: {state, commands: p.alarmCommandDetails}};
}

function watchdog(r, p, pending) {
    const body = alarmQml.match(new RegExp("running: pageActive && " + pending
        + "\\s+onTriggered: \\{([\\s\\S]*?)^        \\}", "m"))[1];
    const t = r.timer(() => vm.runInContext(body, p));
    t.interval = 10000;
    t.restart();
}

// Original failing scenario: a disarm was still sent after the error timeout.
{
    const r = runtime(), p = alarm(r);
    p.refreshAlarmStatus(true);
    p.pinCode = "1234";
    p.executeCommand("disarm", false);
    assert.equal(r.Api.forwardQueue.length, 1);
    watchdog(r, p, "commandPending");
    r.advance(10000);
    assert.equal(p.commandPending, false);
    assert.match(p.status.text, /alarm_command_error/);
    assert.ok(r.Api.forwardQueue.every(e => !e.path.includes("code=")), "PIN-bearing command removed");
    r.request("/ui/state").finish(200, payload(p));
    assert.equal(r.sent.length, 2, "only a fresh status read follows the timeout");
    assert.ok(r.sent.every(req => !req.url.includes("command=")));
    r.request("/ui/state").finish(200, payload(p));
}

// Deadlines are enforced before dispatch even if the QML watchdog runs late.
{
    const r = runtime(), p = alarm(r);
    r.Api.getJson("/ui/state", () => {}, null);
    p.pinCode = "1234";
    p.executeCommand("disarm", false);
    r.Api.getJson("/homeassistant", () => {}, null);
    r.advance(10000);
    r.request("/ui/state").finish(200, {});
    assert.equal(p.commandPending, false);
    assert.match(p.status.text, /alarm_command_error/);
    assert.equal(r.sent.length, 2, "expired command skipped without blocking subsequent work");
    assert.ok(r.sent[1].url.endsWith("/homeassistant"));
    r.sent[1].finish(200, {});
    assert.equal(r.Api.forwardActive, null);
}

for (const cancellation of ["pause", "generation", "quick-timeout"]) {
    const r = runtime(), p = alarm(r);
    r.Api.getJson("/ui/state", () => {}, null);
    if (cancellation === "quick-timeout") {
        p.executeAlarmPageItem();
        watchdog(r, p, "quickActionPending");
        r.advance(10000);
        assert.equal(p.quickActionPending, false);
    } else {
        p.executeCommand("arm_home", false);
        if (cancellation === "pause") p.pausePage();
        else p.runtimeGeneration++;
    }
    r.request("/ui/state").finish(200, payload(p));
    assert.ok(r.sent.every(req => !req.url.includes("command=") && !req.url.includes("entities=")), cancellation);
}

// Cancellation affects only its owner; a sent action retains the native slot.
{
    const r = runtime(), p = alarm(r), other = alarm(r);
    p.executeCommand("arm_home", false);
    const active = r.sent[0];
    other.executeCommand("arm_home", false);
    p.pausePage();
    assert.equal(active.aborted, undefined, "cannot recall a physical action by aborting its socket");
    assert.equal(r.sent.length, 1, "do not start another action before the native slot is free");
    active.finish(200, {ok: true});
    assert.equal(p.commandPending, false, "no late callback after cancellation");
    assert.equal(r.sent.length, 2, "other page's command survives");
    r.sent[1].finish(200, {ok: true});
}

// An ACK received after the deadline is ambiguous, never a reported success.
{
    const r = runtime(), p = alarm(r);
    p.executeCommand("arm_home", false);
    r.advance(10000);
    r.sent[0].finish(200, {ok: true});
    assert.equal(p.commandPending, false);
    assert.match(p.status.text, /alarm_command_error/);
}

// The same deadline applies to readiness checks and dashboard controls.
{
    const r = runtime(), p = alarm(r);
    r.Api.getJson("/ui/state", () => {}, null);
    r.Api.alarmCheck("arm_home", p.status, p);
    r.advance(10000);
    r.sent[0].finish(200, {});
    assert.equal(r.sent.length, 1);
    assert.equal(p.commandPending, false);
}
{
    const r = runtime();
    const p = {runtimeGeneration: 0, commandGeneration: 0, dashboardOnline: true,
        pendingEntity: "", controlFeedback: []};
    r.Api.getJson("/ui/state", () => {}, null);
    r.Api.dashboardControl({entity_id: "cover.shade", domain: "c300x"},
        {command: "close_cover"}, null, {}, p);
    r.advance(10000);
    r.sent[0].finish(200, {});
    assert.equal(r.sent.length, 1, "expired cover action is not dispatched");
    assert.equal(p.pendingEntity, "");
    assert.equal(p.controlInFlight, false);
    assert.equal(p.controlFeedback[0].state, "state_unconfirmed");
}

// A burst of invalidations needs one trailing read, not a stale shared reply.
{
    const r = runtime(), p = alarm(r);
    p.refreshAlarmStatus(true);
    for (let i = 0; i < 5; i++) p.handleStatusEvent({topic: "alarm"});
    assert.equal(r.sent.length, 1);
    assert.equal(r.Api.forwardQueue.length, 1);
    r.sent[0].finish(200, payload(p, "armed_home"));
    assert.equal(p.alarmRawState, "disarmed", "invalidated snapshot ignored");
    assert.equal(r.sent.length, 2);
    p.handleStatusEvent({topic: "alarm"});
    r.sent[1].finish(200, payload(p, "pending"));
    assert.equal(p.alarmRawState, "disarmed", "an event during the trailing read invalidates it too");
    r.sent[2].finish(200, payload(p, "triggered"));
    assert.equal(p.alarmRawState, "triggered");
    assert.equal(p.selectedCommand, "disarm");
    r.advance(60000);
    assert.equal(r.sent.length, 3, "no idle status polling");
}
console.log("Queue deadlines, cancellation and fresh alarm reads passed");

// Exercise the vendor lifecycle, not a direct call to our cleanup helper.
for (const destination of ["homePage", "videocallPage"]) {
    const r = runtime();
    const p = methods(dashboardQml, {Api: r.Api, Date: r.clock, I18n: {text: (_, key) => key},
        uiLanguage: "en", status: {}, runtimeGeneration: 0, commandGeneration: 0,
        pendingEntity: "", controlFeedback: [], dashboardOnline: true,
        dashboardLoading: false, dashboardRefreshAgain: false, listScrolling: false,
        pageActive: false, armedCommand: "", interactionActive: false});
    p.aboutToShow();
    r.Api.dashboardControl({entity_id: "cover.shade", domain: "c300x"},
        {command: "close_cover"}, null, p.status, p);
    assert.equal(r.Api.forwardQueue.length, 1);
    p.armedCommand = "unlock";
    p.interactionActive = true;
    p.dashboardRefreshAgain = true;
    const requests = r.sent.slice();
    const lateCallbacks = requests.map(request => request.onreadystatechange);
    const oldPage = {item: p, source: "HomeAssistant.qml", visible: true};
    const nextPage = {visible: false, _pageName: destination};
    const tabs = {tabs: [oldPage, nextPage], current: nextPage,
        global: {screenshotActive: false}, console: {log() {}}};
    const sysroot = process.env.C300X_DEVICE_SYSROOT;
    if (sysroot) {
        const skin = path.join(sysroot, "home/bticino/bin/gui/skins/default");
        for (const [file, name, target] of [["PageLoader.qml", "hidden", oldPage],
            ["TabView.qml", "_realActivateTab", tabs]]) {
            const source = fs.readFileSync(path.join(skin, file), "utf8");
            const method = source.match(new RegExp("^    function " + name + "\\([^]*?^    }", "m"));
            assert.ok(method, file + " exposes " + name);
            vm.runInContext(method[0], vm.createContext(target));
        }
    } else {
        oldPage.hidden = () => { if (p.hidden) p.hidden(); };
        tabs._realActivateTab = () => {
            oldPage.visible = false;
            oldPage.hidden();
            nextPage.visible = true;
        };
    }
    tabs._realActivateTab(nextPage);
    assert.equal(p.pageActive, false, destination + " invokes dashboard cleanup via hidden()");
    assert.equal(p.runtimeGeneration, 1);
    assert.equal(p.armedCommand, "");
    assert.equal(p.interactionActive, false);
    assert.equal(p.pendingEntity, "");
    assert.equal(p.controlInFlight, false);
    assert.equal(p.dashboardOnline, false);
    assert.equal(p.dashboardLoading, false);
    assert.equal(p.dashboardRefreshAgain, false);
    assert.equal(p.controlFeedback[0].state, "state_unconfirmed");
    assert.equal(r.Api.eventWatching, false);
    assert.equal(r.Api.eventRequest, null);
    assert.equal(r.Api.forwardQueue.length, 0);
    assert.equal(r.Api.forwardActive, null);
    assert.ok(requests.every(request => request.aborted));
    for (const callback of lateCallbacks) callback();
    r.advance(60000);
    assert.equal(r.sent.length, requests.length, "hidden dashboard sends no further requests");
    assert.equal(p.pageActive, false);
    p.aboutToShow();
    assert.equal(p.pageActive, true);
    assert.equal(r.sent.length, requests.length + 2, "reopening starts one read and one event watch");
    assert.equal(r.Api.eventWatching, true);
}
console.log("Dashboard stock hidden lifecycle passed");

// Emulate QML property notifications: rendered feedback is cached until a
// property changes. Merely advancing Date.now() cannot refresh that binding.
{
    const r = runtime();
    const item = {entity_id: "light.hall"};
    let feedback = [], active = false, rendered = "";
    const p = methods(dashboardQml, {Api: r.Api, Date: r.clock, I18n: {text: (_, key) => key},
        uiLanguage: "en", pendingEntity: "", controlInFlight: false, dashboardOnline: true});
    const trigger = dashboardQml.match(/id: feedbackExpiry\s+repeat: false\s+onTriggered: ([^\n]+)/)[1];
    const stopped = dashboardQml.match(/id: feedbackExpiry[^}]*onRunningChanged: ([^\n]+)/)[1];
    p.feedbackDue = false;
    p.feedbackExpiry = r.timer(() => vm.runInContext(trigger, p));
    p.feedbackExpiry.stopped = () => { p.running = p.feedbackExpiry.running; vm.runInContext(stopped, p); };
    assert.match(dashboardQml, /onControlFeedbackChanged: scheduleFeedbackExpiry\(\)/);
    assert.match(dashboardQml, /onPageActiveChanged: refreshFeedbackExpiry\(\)/);
    Object.defineProperty(p, "controlFeedback", {get: () => feedback, set(value) {
        feedback = value;
        p.scheduleFeedbackExpiry();
        rendered = p.feedbackText(item);
    }});
    Object.defineProperty(p, "pageActive", {get: () => active, set(value) {
        active = value;
        p.refreshFeedbackExpiry();
    }});
    p.pageActive = true;
    assert.equal(p.feedbackExpiry.running, false);
    r.Api.setDashboardFeedback(p, item.entity_id, "action_sent", {command: "toggle", value: true});
    const stamp = feedback[0].at;
    assert.equal(rendered, "action_sent");
    r.advance(14999);
    assert.equal(rendered, "action_sent");
    r.advance(1);
    assert.equal(rendered, "state_unconfirmed", "timer invalidates the cached binding without another event");
    assert.equal(feedback[0].at, stamp, "warning does not extend the discard deadline");
    assert.equal(feedback[0].expected.value, true, "late confirmation remains possible");
    assert.equal(p.feedbackExpiry.interval, 45000);
    r.advance(45000);
    assert.equal(rendered, "");
    assert.equal(feedback.length, 0);
    assert.equal(p.feedbackExpiry.running, false);

    r.Api.setDashboardFeedback(p, item.entity_id, "action_sent", {command: "toggle", value: true});
    r.advance(20000);
    p.dashboardPages = [{items: [{...item, state: true}]}];
    r.Api.confirmDashboardFeedback(p);
    assert.equal(rendered, "state_confirmed");
    assert.equal(p.feedbackExpiry.interval, 60000, "confirmation gets its own lifetime");
    p.pageActive = false;
    assert.equal(p.feedbackExpiry.running, false, "hidden page has no expiry wakeups");
    r.advance(70000);
    p.pageActive = true;
    assert.equal(rendered, "", "resume expires old feedback immediately");
    assert.equal(p.feedbackExpiry.running, false);
    assert.equal(r.sent.length, 0, "feedback expiry never polls the network");
}
console.log("Demand-driven feedback binding expiry passed");

function memoPage(r) {
    const p = {externalUnreadMessages: -1, externalUnreadMemos: -1};
    p.memoEventRetryTimer = r.timer(() => r.Api.retryEventWatch());
    r.Api.syncHomeNotifications(p);
    r.request("/ui/answering-machine/messages").finish(200, {unread: 1});
    r.request("/ui/memos").finish(200, {unread: 2});
    return p;
}

{
    const r = runtime("c300x_memos.js"), p = memoPage(r), events = [];
    r.Api.startEventWatch(event => events.push(event.topic));
    assert.equal(r.timers.length, 1, "one lifetime-owned retry timer");
    const retry = r.timers[0];
    for (const delay of [1000, 2000, 4000, 8000, 16000, 30000, 30000]) {
        r.request("/ui/events/next").finish(503, "");
        assert.equal(retry.interval, delay, "bounded backoff");
        const before = r.sent.length;
        r.advance(delay - 1);
        assert.equal(r.sent.length, before, "no immediate retry loop");
        r.advance(1);
        assert.equal(r.sent.length, before + 1);
    }
    r.request("/ui/events/next").finish(200, {revision: 0, changed: false});
    r.request("/ui/answering-machine/messages").finish(200, {unread: 5});
    r.request("/ui/memos").finish(200, {unread: 7});
    assert.equal(p.externalUnreadMessages, 5);
    assert.equal(p.externalUnreadMemos, 7, "outage recovery resyncs even with no changed event");
    assert.deepEqual(events, ["notifications"], "home button availability is refreshed too");
    assert.equal(retry.running, false);
    assert.equal(r.Api.eventRetryDelay, 1000);
    const healthyCount = r.sent.length;
    r.advance(60000);
    assert.equal(r.sent.length, healthyCount, "no timer-driven idle polling");
    r.request("/ui/events/next").finish(200, {revision: 0, changed: false});
    assert.equal(r.sent.length, healthyCount + 1, "healthy watch only renews its long poll");
    r.request("/ui/events/next").finish(200, "invalid JSON");
    assert.equal(retry.interval, 1000);
    r.Api.stopEventWatch();
    const stoppedCount = r.sent.length;
    r.advance(60000);
    assert.equal(r.sent.length, stoppedCount, "stop cancels scheduled retry");
}

// Retry a failed recovery snapshot without opening a second event long poll.
{
    const r = runtime("c300x_memos.js"), p = memoPage(r);
    r.Api.startEventWatch(() => {});
    r.request("/ui/events/next").finish(0, "");
    r.advance(1000);
    r.request("/ui/events/next").finish(200, {revision: 3, changed: false});
    r.request("/ui/answering-machine/messages").finish(503, "");
    r.request("/ui/memos").finish(200, {unread: 4});
    let poll = r.request("/ui/events/next");
    assert.equal(r.timers[0].running, true);
    const before = r.sent.length;
    poll.finish(200, {revision: 3, changed: false});
    assert.equal(r.sent.length, before + 1, "event traffic cannot bypass snapshot backoff");
    poll = r.request("/ui/events/next");
    r.advance(r.timers[0].interval);
    assert.equal(r.request("/ui/events/next"), poll);
    r.request("/ui/answering-machine/messages").finish(200, {unread: 8});
    r.request("/ui/memos").finish(200, {unread: 9});
    assert.equal(p.externalUnreadMessages, 8);
    assert.equal(p.externalUnreadMemos, 9);
    assert.equal(r.timers[0].running, false);
    assert.equal(r.Api.eventRecovering, false);
}

// A newer snapshot supersedes an in-flight recovery read, not vice versa.
{
    const r = runtime("c300x_memos.js"), p = memoPage(r);
    r.Api.startEventWatch(() => {});
    r.request("/ui/events/next").finish(0, "");
    r.advance(1000);
    r.request("/ui/events/next").finish(200, {revision: 1, changed: false});
    const oldMessages = r.request("/ui/answering-machine/messages");
    const oldMemos = r.request("/ui/memos");
    r.Api.syncHomeNotifications(p);
    oldMessages.finish(200, {unread: 99});
    oldMemos.finish(200, {unread: 99});
    assert.equal(p.externalUnreadMessages, 1);
    assert.equal(p.externalUnreadMemos, 2);
    assert.equal(r.Api.eventRecovering, true, "superseded results cannot finish recovery");
    r.request("/ui/answering-machine/messages").finish(200, {unread: 8});
    r.request("/ui/memos").finish(200, {unread: 9});
    assert.equal(p.externalUnreadMessages, 8);
    assert.equal(p.externalUnreadMemos, 9);
    r.Api.stopEventWatch();
    assert.equal(r.timers[0].running, false);
}

// Stopped or superseded responses cannot clear a new watch or update its page.
{
    const r = runtime("c300x_memos.js"), p = memoPage(r);
    r.Api.startEventWatch(() => {});
    const old = r.request("/ui/events/next"), lateHandler = old.onreadystatechange;
    r.Api.stopEventWatch();
    assert.equal(old.aborted, true);
    r.Api.startEventWatch(() => {});
    const current = r.request("/ui/events/next");
    old.status = 200;
    old.responseText = JSON.stringify({revision: 999, changed: true});
    lateHandler();
    assert.equal(r.Api.eventRequest, current);
    assert.equal(r.Api.eventRevision, 0);
    current.finish(0, "");
    r.advance(1000);
    r.request("/ui/events/next").finish(200, {revision: 1, changed: false});
    r.Api.stopEventWatch();
    r.request("/ui/answering-machine/messages").finish(200, {unread: 99});
    r.request("/ui/memos").finish(200, {unread: 99});
    assert.equal(p.externalUnreadMessages, 1);
    assert.equal(p.externalUnreadMemos, 2);
    assert.equal(r.timers[0].running, false);
    assert.equal(r.Api.connections.length, 0);
}
console.log("Memo watch backoff, resync and cancellation passed");

// Switching owners stops the old QML-owned timer; JS must never destroy it.
{
    const r = runtime("c300x_memos.js"), oldPage = memoPage(r);
    oldPage.memoEventRetryTimer.destroy = () => assert.fail("QML owns the timer");
    r.Api.startEventWatch(() => {});
    r.request("/ui/events/next").finish(0, "");
    const newPage = memoPage(r);
    assert.equal(oldPage.memoEventRetryTimer.running, false);
    assert.equal(r.Api.eventRetryTimer, newPage.memoEventRetryTimer);
    assert.equal(r.Api.eventWatching, false);
    r.Api.startEventWatch(() => {});
    r.request("/ui/events/next").finish(0, "");
    assert.equal(newPage.memoEventRetryTimer.running, true);
}

// An older HomePage without the alias must not crash during an update.
{
    const r = runtime("c300x_memos.js");
    r.Api.syncHomeNotifications({externalUnreadMessages: -1, externalUnreadMemos: -1});
    assert.equal(r.Api.eventRetryTimer, null);
    assert.equal(r.timers.length, 0);
    assert.equal(r.sent.length, 2);
}
