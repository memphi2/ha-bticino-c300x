const fs = require("fs");
const vm = require("vm");
const assert = require("assert");
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(process.argv[2], "utf8").replace(/^\.pragma library\s*/, ""), context);
const entry = {id: "text/memo_1", kind: "text", has_text: true, text: "<b>literal</b>",
    date: "22/11/2026 12:00", read: false, text_truncated: false};
const good = {ok: true, available: true, memos: [entry, {kind: "voice"}]};
function parse(data) { return vm.runInContext(`textEntries(JSON.parse(${JSON.stringify(JSON.stringify(data))}))`, context); }
assert.equal(parse(good).length, 1);
assert.equal(parse(good)[0].text, entry.text);
for (const bad of [null, {}, {...good, memos: Array(129).fill(entry)}, {...good, available: "yes"},
    {...good, memos: [entry, entry]}, ...[
        {id: "text/../../escape"}, {kind: "unknown"}, {text: "x".repeat(513)}, {text: null},
        {has_text: false}, {read: "false"}, {date: 1}, {text_truncated: undefined}
    ].map(change => ({...good, memos: [{...entry, ...change}]}))]) {
    assert.throws(() => parse(bad));
}
let requests = [];
const page = {visible: true, blocked: false, busy: false, failed: false, entries: [],
    resetInput() {}, deadline: {restart() {}, stop() {}}};
function factory() {
    const xhr = {readyState: 0, open(method, url) {
        assert.equal(method, "GET"); assert.equal(url, "http://127.0.0.1:8090/ui/memos");
    }, send() {}, abort() { this.aborted = true; }, reply(status, data) {
        this.readyState = 4; this.status = status; this.responseText = JSON.stringify(data); this.onreadystatechange();
    }};
    requests.push(xhr); return xhr;
}
const reader = context.create(page, factory);
reader.load(); requests[0].reply(200, good);
assert.equal(page.entries.length, 1); assert.equal(page.busy, false);
reader.load(); const late = requests[1].onreadystatechange;
page.blocked = true; reader.stop(); requests[1].readyState = 4; requests[1].status = 200;
requests[1].responseText = JSON.stringify(good); late();
assert.equal(page.entries.length, 0); assert(requests[1].aborted);
reader.load(); assert.equal(requests.length, 2);
page.blocked = false; reader.load(); reader.timeout();
assert(page.failed && !page.busy && requests[2].aborted);
reader.load(); requests[3].reply(200, {...good, available: false});
assert.equal(page.entries.length, 0); assert.equal(page.available, false);
reader.load(); requests[4].reply(500, good); assert(page.failed);
reader.load(); requests[5].reply(200, {ok: true}); assert(page.failed);
reader.load(); const request = requests[6]; reader.destroy();
request.reply(200, good); assert(request.aborted); reader.load(); assert.equal(requests.length, 7);
