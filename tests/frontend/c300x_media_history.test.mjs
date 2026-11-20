import assert from "node:assert/strict";
import test from "node:test";
import { C300XMediaHistory, historyItems, mediaBlob, mediaKey } from "../../custom_components/bticino_c300x/frontend/c300x-media-history.js";

const tick = () => new Promise(setImmediate);
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const item = (id = "a", kind = "image", at = 10) => ({ id: id.repeat(64), kind, at,
  expires_at: Date.now() / 1000 + 3600, revision: "first" });
const metadata = (items) => new Response(JSON.stringify({ items }), { headers: { "Content-Type": "application/json" } });
const bytes = (kind = "image") => new Response("saved media", { headers: { "Content-Type": kind === "image" ? "image/jpeg" : "video/mp4" } });

function harness(t, initial = [item()], customFetch) {
  const state = { items: initial, requests: [], subscriptions: [], released: 0, changes: 0 };
  state.hass = { user: { id: "alice", is_admin: true }, auth: {}, connection: {
    subscribeMessage(callback, message) { state.subscriptions.push({ callback, message }); return Promise.resolve(() => state.released++); },
  }, fetchWithAuth(path, options) {
    state.requests.push({ path, options });
    return customFetch ? customFetch(path, options) : Promise.resolve(path.endsWith("/entry") ? metadata(state.items)
      : bytes(state.items.find((entry) => path.endsWith(entry.id))?.kind));
  } };
  state.history = new C300XMediaHistory(() => state.changes++);
  state.configure = (overrides = {}) => state.history.configure({ hass: state.hass, entryId: "entry", connected: true, ...overrides });
  state.configure();
  t.after(() => state.history.deactivate());
  return state;
}

test("history validates IDs, kinds, dates, expiry, revisions, duplicates, bounds and chronological ordering", () => {
  const a = item("a", "video", 40), b = item("b", "image", 20), c = item("c", "image", 40);
  const invalid = [null, { ...a, id: "https://other/image" }, { ...a, kind: "html" }, { ...a, at: Infinity },
    { ...a, at: 9e99 }, { ...a, at: "40" }, { ...a, expires_at: 0 }, { ...a, expires_at: 9e99 },
    { ...a, revision: {} }, { ...a, revision: "" }];
  const items = historyItems({ items: [b, ...invalid, c, { ...a, url: "https://other" }] });
  assert.deepEqual(items, [a, c, b]);
  assert.throws(() => historyItems({ items: [a, a] }));
  assert.throws(() => historyItems({ items: Array(1001).fill(a) }));
  assert.throws(() => historyItems({ visits: [] }));
  assert.equal(mediaKey(a), mediaKey({ ...a, at: 80, expires_at: a.expires_at + 100 }));
  assert.notEqual(mediaKey(a), mediaKey({ ...a, revision: "changed" }));
});

test("bounded streamed bodies enforce exact MIME, size, status and nonempty content", async () => {
  const signal = new AbortController().signal;
  assert.equal((await mediaBlob(bytes(), "image", signal)).type, "image/jpeg");
  for (const response of [new Response("x"), new Response("x", { headers: { "Content-Type": "text/html" } }),
    new Response("", { headers: { "Content-Type": "image/jpeg" } }),
    new Response("x", { status: 403, headers: { "Content-Type": "image/jpeg" } }),
    new Response("x", { headers: { "Content-Type": "image/jpeg", "Content-Length": 524289 } }),
    new Response(new Uint8Array(524289), { headers: { "Content-Type": "image/jpeg" } })]) {
    await assert.rejects(mediaBlob(response, "image", signal));
  }
  await assert.rejects(mediaBlob(new Response(new Uint8Array(1048577),
    { headers: { "Content-Type": "application/json" } }), "list", signal));
  await assert.rejects(mediaBlob(new Response("x", { headers: { "Content-Type": "video/mp4", "Content-Length": 67108865 } }), "video", signal));
});

test("abort cancels a stalled reader without waiting for another byte", async () => {
  const controller = new AbortController();
  let canceled = 0;
  const response = new Response(new ReadableStream({ cancel() { canceled++; } }), { headers: { "Content-Type": "image/jpeg" } });
  const pending = mediaBlob(response, "image", controller.signal);
  controller.abort();
  await assert.rejects(pending);
  assert.equal(canceled, 1);
});

test("subscription is scoped and lazy; all images and videos navigate older/newer back to current", async (t) => {
  const a = item("a", "image", 40), b = item("b", "video", 30), c = item("c", "image", 20);
  const s = harness(t, [c, a, b]);
  await tick();
  assert.deepEqual(s.subscriptions[0].message, { type: "bticino_c300x/visitor_journal/subscribe", entry_id: "entry" });
  assert.equal(s.requests.length, 0);
  s.subscriptions[0].callback({ entry_id: "entry" });
  assert.equal(s.requests.length, 0);
  await s.history.step(1);
  assert.equal(s.history.selected.id, a.id);
  assert.ok(s.history.url.startsWith("blob:"));
  await s.history.step(1);
  assert.equal(s.history.selected.id, b.id);
  await s.history.step(1);
  assert.equal(s.history.selected.id, c.id);
  await s.history.step(-1);
  await s.history.step(-1);
  const count = s.requests.length;
  await s.history.step(-1);
  assert.equal(s.history.selected, null);
  assert.equal(s.history.url, "");
  assert.equal(s.requests.length, count);
  assert.ok(s.requests.every(({ path }) => /^\/api\/bticino_c300x\/media-history\/entry(?:\/[a-f0-9]{64})?$/.test(path)));
});

test("the image the card shows as its still is not shown again as the first saved file", async (t) => {
  const still = item("a", "image", 40), video = item("b", "video", 30), older = item("c", "image", 20);
  const s = harness(t, [still, video, older]);
  s.configure({ stillAt: 40 });
  await s.history.step(1);
  assert.equal(s.history.selected.id, video.id);
  // Browsing hides the still; the way back still ends at it, not at its saved copy.
  s.configure({ stillAt: null });
  await s.history.step(1);
  assert.equal(s.history.selected.id, older.id);
  await s.history.step(-1);
  assert.equal(s.history.selected.id, video.id);
  await s.history.step(-1);
  assert.equal(s.history.selected, null);

  const only = harness(t, [still]);
  only.configure({ stillAt: 40 });
  await only.history.step(1);
  assert.equal(only.history.selected, null);

  const other = harness(t, [still, video]);
  other.configure({ stillAt: 12 });
  await other.history.step(1);
  assert.equal(other.history.selected.id, still.id);
});

test("metadata insertion preserves playing file identity and removal/revision change closes it", async (t) => {
  const s = harness(t, [item("a", "video")]);
  await s.history.step(1);
  const url = s.history.url;
  s.items.unshift(item("b", "image", 20));
  s.subscriptions[0].callback({ entry_id: "other" });
  assert.equal(s.requests.length, 2);
  s.subscriptions[0].callback({ entry_id: "entry" });
  await s.history.listPromise;
  assert.equal(s.history.url, url);
  assert.equal(s.history.selected.id, item().id);
  assert.equal(s.requests.length, 3);
  s.items[1] = { ...s.items[1], revision: "replacement" };
  s.history.markDirty();
  await s.history.listPromise;
  assert.equal(s.history.selected, null);
  assert.equal(s.history.url, "");
  await s.history.step(1);
  s.items = [];
  s.history.markDirty();
  await s.history.listPromise;
  assert.equal(s.history.selected, null);
});

test("failed files keep their cursor so older media remains reachable", async (t) => {
  const newest = item("a", "video", 40), older = item("b", "image", 30);
  const s = harness(t, [newest, older], async (path) => path.endsWith("/entry")
    ? metadata([newest, older]) : path.endsWith(newest.id) ? new Response("missing", { status: 404 }) : bytes());
  await s.history.step(1);
  assert.equal(s.history.selected.id, newest.id);
  assert.equal(s.history.url, "");
  assert.equal(s.history.error, "unavailable");
  await s.history.step(1);
  assert.equal(s.history.selected.id, older.id);
  assert.ok(s.history.url);
  s.history.mediaUnavailable();
  assert.equal(s.history.selected.id, older.id, "A decoding error also retains the cursor");
  assert.equal(s.history.url, "");
  await s.history.step(-1);
  assert.equal(s.history.selected.id, newest.id);
  await s.history.step(-1);
  assert.equal(s.history.selected, null);
});

for (const status of [401, 403]) test(`${status} playback clears cached metadata instead of keeping a failed cursor`, async (t) => {
  const s = harness(t, [item()], async (path) => path.endsWith("/entry")
    ? metadata([item()]) : new Response("denied", { status }));
  await s.history.step(1);
  assert.equal(s.history.active, false);
  assert.equal(s.history.selected, null);
  assert.deepEqual(s.history.items, []);
  assert.equal(s.history.error, "unavailable");
});

test("invalidations during list loading coalesce and never publish superseded metadata", async (t) => {
  const first = deferred();
  let lists = 0;
  const s = harness(t, [], (path) => path.endsWith("/entry")
    ? ++lists === 1 ? first.promise : metadata([item("b")]) : bytes());
  const pending = s.history.step(1);
  await tick();
  s.history.markDirty();
  first.resolve(metadata([item("a")]));
  await pending;
  assert.equal(lists, 2);
  assert.equal(s.history.selected.id, item("b").id);
  assert.equal(s.requests.some(({ path }) => path.endsWith(item("a").id)), false);
});

test("clear while list is pending aborts and cannot reopen archive on late response", async (t) => {
  const deferredList = deferred();
  const s = harness(t, [], () => deferredList.promise);
  const pending = s.history.step(1);
  s.history.clearMedia();
  assert.equal(s.requests[0].options.signal.aborted, true);
  deferredList.resolve(metadata([item()]));
  await pending;
  assert.equal(s.history.selected, null);
  assert.deepEqual(s.history.items, []);
});

test("empty cleanup suppresses notifications but still cancels cached navigation", async (t) => {
  const s = harness(t);
  await s.history.load();
  const pending = s.history.step(1);
  const before = s.changes;
  s.history.clearMedia();
  assert.equal(s.changes, before);
  await pending;
  assert.equal(s.history.selected, null);
  assert.equal(s.requests.length, 1);
  for (let index = 0; index < 100; index++) s.configure({ busy: true });
  assert.equal(s.changes, before);
  s.configure({ enabled: false });
  assert.equal(s.changes, before + 1, "Active membership and cached items must invalidate once");
  for (let index = 0; index < 100; index++) s.configure({ enabled: false });
  assert.equal(s.changes, before + 1);
  assert.deepEqual(s.history.items, []);
});

test("busy/ring synchronously closes archive, aborts pending file and blocks navigation", async (t) => {
  const file = deferred();
  const s = harness(t, [], (path) => path.endsWith("/entry") ? metadata([item()]) : file.promise);
  const pending = s.history.step(1);
  await tick();
  assert.ok(s.history.selected);
  s.configure({ busy: true });
  assert.equal(s.history.selected, null);
  assert.equal(s.requests[1].options.signal.aborted, true);
  await s.history.step(1);
  assert.equal(s.requests.length, 2);
  file.resolve(bytes());
  await pending;
  assert.equal(s.history.url, "");
});

for (const identity of ["entry", "connection", "user", "auth", "admin"]) test(`${identity} change clears identity-scoped state and ignores late data`, async (t) => {
  const file = deferred();
  const s = harness(t, [], (path) => path.endsWith("/entry") ? metadata([item()]) : file.promise);
  const pending = s.history.step(1);
  await tick();
  const oldCallback = s.subscriptions[0].callback;
  const config = {};
  if (identity === "entry") config.entryId = "another";
  if (identity === "connection") s.hass.connection = { ...s.hass.connection };
  if (identity === "user") s.hass.user.id = "bob";
  if (identity === "auth") s.hass.auth = {};
  if (identity === "admin") s.hass.user.is_admin = false;
  s.configure(config);
  assert.equal(s.history.selected, null);
  assert.deepEqual(s.history.items, []);
  oldCallback({ entry_id: "entry", closed: true });
  assert.equal(s.history.active, true);
  file.resolve(bytes());
  await pending;
  assert.equal(s.history.url, "");
});

test("late subscription acknowledgements and closed membership release subscriptions", async (t) => {
  const subscription = deferred();
  const s = harness(t);
  s.history.deactivate();
  s.hass.connection = { subscribeMessage: () => subscription.promise };
  s.configure();
  await tick();
  s.history.deactivate();
  subscription.resolve(() => s.released++);
  await tick();
  assert.equal(s.released, 1);
  s.hass.connection = { subscribeMessage: async (callback) => { s.callback = callback; return () => s.released++; } };
  s.configure();
  await s.history.step(1);
  s.callback({ entry_id: "entry", closed: true });
  assert.equal(s.history.active, false);
  assert.equal(s.history.url, "");
  assert.equal(s.history.selected, null);
  assert.equal(s.released, 2);
});

test("subscription rejection, disable and detach fail closed; reconnect remains lazy", async (t) => {
  const s = harness(t);
  await s.history.step(1);
  s.configure({ enabled: false });
  assert.equal(s.history.active, false);
  assert.equal(s.history.url, "");
  s.configure();
  const count = s.requests.length;
  await tick();
  assert.equal(s.requests.length, count);
  s.configure({ connected: false });
  assert.equal(s.history.active, false);
  s.hass.connection = { subscribeMessage: () => Promise.reject(new Error("denied")) };
  s.configure();
  await tick();
  assert.equal(s.history.active, false);
  assert.deepEqual(s.history.items, []);
});

test("expiry removes selected file without polling", async (t) => {
  const s = harness(t, [item("a", "video")]);
  await s.history.step(1);
  s.history.items[0].expires_at = Date.now() / 1000 - 1;
  s.history.expire();
  assert.equal(s.history.selected, null);
  assert.equal(s.history.url, "");
  assert.equal(s.requests.length, 2);
});

test("metadata authorization failure clears existing file instead of retaining stale media", async (t) => {
  const s = harness(t);
  await s.history.step(1);
  s.hass.fetchWithAuth = async () => new Response("denied", { status: 403 });
  s.history.markDirty();
  await s.history.listPromise;
  assert.equal(s.history.selected, null);
  assert.equal(s.history.url, "");
  assert.deepEqual(s.history.items, []);
  assert.equal(s.history.error, "unavailable");
});
