const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../..");
const jsRoot = process.env.C300X_DEVICE_JS_ROOT || path.join(root, "device_qml/js");
const TEXT = 2;

function runtime() {
    const sent = [];
    function Request() { this.readyState = 0; this.status = 0; }
    Request.prototype.open = function(method, url) { this.method = method; this.url = url; this.readyState = 1; };
    Request.prototype.send = function() { sent.push(this); };
    Request.prototype.abort = function() { this.aborted = true; };
    Request.prototype.finish = function(status, data) {
        this.status = status;
        this.responseText = typeof data === "string" ? data : JSON.stringify(data);
        this.readyState = 4;
        this.onreadystatechange();
    };
    const Api = vm.createContext({Date, XMLHttpRequest: Request});
    vm.runInContext(fs.readFileSync(path.join(jsRoot, "c300x_memos.js"), "utf8")
        .replace(/^\.pragma library\s*/, ""), Api);
    function request(suffix) {
        const req = sent.find(r => r.readyState !== 4 && r.url.includes(suffix));
        assert.ok(req, "pending request for " + suffix);
        return req;
    }
    return {Api, sent, request};
}

// The stock memo model: remove() is the stock delete path, it deletes the memo.
function stockModel() {
    const objects = [
        {messageId: 1, type: TEXT}, {messageId: 2, type: TEXT},
        {messageId: 3, type: 1}, {messageId: 4, type: 1},
    ];
    const removed = [];
    return {
        removed,
        get count() { return objects.length; },
        binder: {getObject: index => objects[index]},
        remove(object) {
            removed.push((object.type === TEXT ? "text" : "voice") + "/memo_" + object.messageId);
            objects.splice(objects.indexOf(object), 1);
        },
    };
}

function sync(status, body) {
    const r = runtime(), model = stockModel(), results = [];
    r.Api.syncMemoModel({model}, TEXT, (ok, data) => results.push(ok));
    r.request("/ui/memos").finish(status, body);
    assert.equal(results.length, 1, "the page callback still runs");
    return model.removed;
}

const memo = id => ({id});
const all = [memo("text/memo_1"), memo("text/memo_2"), memo("voice/memo_3"), memo("voice/memo_4")];

// Memos switched off in the agent: an empty list says nothing about the station.
assert.deepEqual(sync(200, {ok: true, available: false, total: 0, memos: []}), []);
// More memos than the agent lists (max_memos), or a memo it could not read.
assert.deepEqual(sync(200, {ok: true, available: true, total: 1, memos: [memo("text/memo_1")]}), []);
// An agent without a deletion list never removes anything.
assert.deepEqual(sync(200, {ok: true, available: true, total: 0, memos: []}), []);
// Failed, refused or unparsable reads.
assert.deepEqual(sync(200, {ok: false, available: true, memos: [], deleted: ["text/memo_1"]}), []);
assert.deepEqual(sync(503, ""), []);
assert.deepEqual(sync(200, "not json"), []);
assert.deepEqual(sync(200, {ok: true, available: false, memos: [], deleted: ["text/memo_1"]}), []);
console.log("Memo sync never removes on an incomplete or unavailable list passed");

// Only memos the agent reports as deleted leave the model.
assert.deepEqual(sync(200, {ok: true, available: true, memos: all.filter(m => m.id !== "voice/memo_3"),
    deleted: ["voice/memo_3"]}), ["voice/memo_3"]);
// A memo listed again on the station is kept even if its ID was deleted before.
assert.deepEqual(sync(200, {ok: true, available: true, memos: all, deleted: ["text/memo_2"]}), []);
// Unknown or malformed deletion entries are ignored.
assert.deepEqual(sync(200, {ok: true, available: true, memos: [],
    deleted: [{id: "text/memo_1"}, 2, null, "text/memo_9"]}), []);
assert.deepEqual(sync(200, {ok: true, available: true, memos: [], deleted: "text/memo_1"}), []);
console.log("Memo sync removes only agent-deleted memos passed");

// Home badges: -1 hands the badge back to the stock count. A count the agent
// cannot vouch for must never show as a false 0 or stay frozen.
{
    const r = runtime(), home = {externalUnreadMessages: -1, externalUnreadMemos: -1};
    r.Api.syncHomeNotifications(home);
    r.request("/ui/answering-machine/messages").finish(200, {ok: true, available: true, unread: 3});
    r.request("/ui/memos").finish(200, {ok: true, available: false, unread: 0, memos: []});
    assert.equal(home.externalUnreadMessages, 3);
    assert.equal(home.externalUnreadMemos, -1, "memos switched off: stock count, not 0");
    r.Api.syncHomeNotifications(home);
    r.request("/ui/answering-machine/messages").finish(200, {ok: true, available: true, unread: 4});
    r.request("/ui/memos").finish(200, {ok: true, available: true, unread: 2});
    assert.deepEqual([home.externalUnreadMessages, home.externalUnreadMemos], [4, 2]);
    r.Api.syncHomeNotifications(home);
    r.request("/ui/answering-machine/messages").finish(503, "");
    r.request("/ui/memos").finish(200, "not json");
    assert.deepEqual([home.externalUnreadMessages, home.externalUnreadMemos], [-1, -1],
        "a failed read does not keep the last agent count");
    r.Api.syncHomeNotifications(home);
    r.request("/ui/answering-machine/messages").finish(200, {ok: true, available: true, unread: 4});
    r.request("/ui/memos").finish(200, {ok: true, available: true, unread: 2});
    r.Api.startEventWatch(() => {});
    r.request("/ui/events/next").finish(0, "");
    assert.deepEqual([home.externalUnreadMessages, home.externalUnreadMemos], [-1, -1],
        "agent down: the badge does not freeze on the last agent count");
    r.Api.stopEventWatch();
}
console.log("Home badges fall back to the stock count passed");

// The memo library follows the station UI port the patched pages expose.
{
    const r = runtime(), home = {externalUnreadMessages: -1, externalUnreadMemos: -1,
        uiBaseUrl: "http://127.0.0.1:18123"};
    r.Api.syncHomeNotifications(home);
    r.Api.startEventWatch(() => {});
    assert.ok(r.sent.length === 3 && r.sent.every(x => x.url.startsWith("http://127.0.0.1:18123/ui/")));
    r.Api.stopEventWatch();
    const memoPage = {model: stockModel(), uiBaseUrl: "http://evil.example:80"};
    r.Api.syncMemoModel(memoPage, TEXT);
    assert.ok(r.sent[r.sent.length - 1].url.startsWith("http://127.0.0.1:18123/ui/memos"),
        "only a loopback base URL is taken");
    const plain = runtime();
    plain.Api.syncMemoModel({model: stockModel()}, TEXT);
    assert.ok(plain.sent[0].url.startsWith("http://127.0.0.1:8090/ui/memos"), "8090 stays the default");
}
console.log("Memo library follows the UI port passed");
