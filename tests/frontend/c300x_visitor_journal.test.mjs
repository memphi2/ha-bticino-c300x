import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

globalThis.HTMLElement = class {};
globalThis.customElements = { get() {}, define() {} };
const { journalBlob, journalMediaKey, C300XVisitorJournal } = await import("../../custom_components/bticino_c300x/frontend/c300x-visitor-journal.js");

test("journal has no device commands, live media acquisition or polling", () => {
  const source = readFileSync(new URL("../../custom_components/bticino_c300x/frontend/c300x-visitor-journal.js", import.meta.url), "utf8");
  for (const forbidden of ["callService", "callWS", "getUserMedia", "RTCPeerConnection", "setInterval", "autoplay", "srcObject"])
    assert.equal(source.includes(forbidden), false, forbidden);
});

test("media bodies are bounded even without Content-Length", async () => {
  const signal = new AbortController().signal;
  assert.equal((await journalBlob(new Response("1234"), 4, signal)).size, 4);
  await assert.rejects(journalBlob(new Response("12345"), 4, signal));
  await assert.rejects(journalBlob(new Response(""), 4, signal));
  await assert.rejects(journalBlob(new Response("x", { status: 404 }), 4, signal));
  await assert.rejects(journalBlob(new Response("x", { headers: { "Content-Length": "5" } }), 4, signal));
});

test("aborted requests cannot publish stale media", async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(journalBlob(new Response("image"), 100, controller.signal));
});

function subscriptionJournal(subscribeMessage) {
  const journal = new C300XVisitorJournal();
  Object.assign(journal, { isConnected: true, hidden: false, entryId: "one", generation: 0,
    hass: { connection: { subscribeMessage } }, loads: 0 });
  journal.load = () => { journal.loads++; };
  journal.clearMedia = () => {};
  return journal;
}

test("journal uses authorized scoped subscription and ignores other entry signals", async () => {
  let callback, message, receiver, removed = 0;
  const journal = subscriptionJournal(function (fn, msg) {
    callback = fn; message = msg; receiver = this;
    return Promise.resolve(() => removed++);
  });
  journal.activate();
  await new Promise(setImmediate);
  assert.deepEqual(message, { type: "bticino_c300x/visitor_journal/subscribe", entry_id: "one" });
  assert.equal(receiver, journal.hass.connection);
  assert.equal(journal.loads, 1);
  callback({ entry_id: "other" });
  assert.equal(journal.loads, 1);
  callback({ entry_id: "one" });
  assert.equal(journal.loads, 2);
  callback({ entry_id: "one", closed: true });
  assert.equal(journal.active, false);
  assert.equal(removed, 1);
  callback({ entry_id: "one" });
  assert.equal(journal.loads, 2);
});

test("late subscription acknowledgement releases its listener after detach", async () => {
  let finish, removed = 0;
  const journal = subscriptionJournal(() => new Promise(resolve => { finish = resolve; }));
  journal.activate();
  await Promise.resolve();
  journal.disconnectedCallback();
  finish(() => removed++);
  await new Promise(setImmediate);
  assert.equal(removed, 1);
  assert.equal(journal.unsubscribe, null);
});

test("connection replacement disposes old and late listeners even when hass is mutated in place", async () => {
  let oldCallback, finishOld, oldRemoved = 0, newRemoved = 0;
  const journal = subscriptionJournal(callback => {
    oldCallback = callback;
    return new Promise(resolve => { finishOld = resolve; });
  });
  Object.assign(journal, { shadowRoot: {}, details: { open: true }, dialog: { open: false, close() {} } });
  journal.labels = journal.renderList = () => {};
  const hass = journal.hass;
  journal.configure({ hass, entryId: "one", enabled: true });
  await Promise.resolve();
  hass.connection = { subscribeMessage: () => Promise.resolve(() => newRemoved++) };
  journal.configure({ hass, entryId: "one", enabled: true });
  await new Promise(setImmediate);
  const loads = journal.loads;
  oldCallback({ entry_id: "one" });
  assert.equal(journal.loads, loads);
  finishOld(() => oldRemoved++);
  await new Promise(setImmediate);
  assert.equal(oldRemoved, 1);
  assert.equal(newRemoved, 0);
  journal.deactivate();
  assert.equal(newRemoved, 1);
});

test("rejected subscription clears stale data and allows a later activation", async () => {
  const journal = subscriptionJournal(() => Promise.reject(new Error("unauthorized")));
  journal.items = [{ id: "private" }];
  journal.activate();
  await new Promise(setImmediate);
  assert.equal(journal.active, false);
  assert.deepEqual(journal.items, []);
});

test("selected media identity ignores unrelated metadata but tracks availability and revision", () => {
  const item = { id: "one", video: true, video_revision: "original", video_at: 10 };
  const key = journalMediaKey(item, "video");
  assert.equal(journalMediaKey({ ...item, outcome: "answered", image_revision: "other", video_at: 20 }, "video"), key);
  assert.notEqual(journalMediaKey({ ...item, video_revision: "replacement" }, "video"), key);
  assert.notEqual(journalMediaKey({ ...item, video: false }, "video"), key);
  assert.notEqual(journalMediaKey({ ...item, id: "two" }, "video"), key);
});

test("list updates preserve playing media across reordering and reload only selected identity changes", () => {
  const journal = new C300XVisitorJournal();
  const item = { id: "one", video: true, video_revision: "original" };
  Object.assign(journal, { dialog: { open: true }, index: 0, kind: "video", mediaKey: journalMediaKey(item, "video") });
  const shows = [];
  journal.show = (...args) => shows.push(args);
  let labels = 0;
  journal.viewerLabels = () => labels++;
  journal.items = [{ id: "two" }, { ...item, outcome: "answered", image: true, image_revision: "new-image" }];
  journal.syncViewer("one");
  assert.equal(journal.index, 1);
  assert.equal(labels, 1);
  assert.deepEqual(shows, []);
  journal.items[1].video_revision = "replacement";
  journal.syncViewer("one");
  assert.deepEqual(shows, [[1, "video"]]);
});

for (const kind of ["image", "video"]) test(`newly available ${kind} loads in an already open empty visit`, () => {
  const journal = new C300XVisitorJournal();
  const item = { id: "one", image: false, video: false };
  Object.assign(journal, { dialog: { open: true }, index: 0, kind: "video", mediaKey: journalMediaKey(item, "video") });
  journal.items = [{ ...item, [kind]: true, [`${kind}_revision`]: "new" }];
  let shown;
  journal.show = (...args) => { shown = args; };
  journal.syncViewer("one");
  assert.deepEqual(shown, [0, kind]);
});
