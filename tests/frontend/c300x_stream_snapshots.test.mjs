import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { C300XStreamSnapshots } from "../../custom_components/bticino_c300x/frontend/c300x-stream-snapshots.js";

const flush = () => new Promise(setImmediate);
const jpeg = () => new Blob(["jpeg"], { type: "image/jpeg" });
const response = () => ({ ok: true, headers: new Headers({ "Content-Type": "image/jpeg" }), blob: async () => jpeg() });
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

function fixture(t) {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"], now: 1800000000000 });
  const requests = [], previews = [], revoked = [];
  let nextUrl = 0;
  t.mock.method(URL, "createObjectURL", () => `blob:${++nextUrl}`);
  t.mock.method(URL, "revokeObjectURL", (url) => revoked.push(url));
  const hass = { fetchWithAuth: async (...args) => { requests.push(args); return response(); } };
  const snapshots = new C300XStreamSnapshots({
    getHass: () => hass, showPreview: (...args) => previews.push(args),
  });
  t.after(() => snapshots.dispose());
  const update = (attrs = {}, _active = false, entryId = "entry-1") => snapshots.update({
    entryId, attributes: { stream_snapshots: true, ...attrs },
  });
  return { snapshots, requests, previews, revoked, hass, update };
}

test("preview module cannot capture, upload or initiate a camera stream", (t) => {
  const source = readFileSync(new URL("../../custom_components/bticino_c300x/frontend/c300x-stream-snapshots.js", import.meta.url), "utf8");
  for (const forbidden of ["POST", "getVideo", "srcObject", "canvas", "snapshot_session",
    "snapshot_delay_seconds", "RTCPeerConnection", "callService", "setInterval"]) {
    assert.equal(source.includes(forbidden), false, forbidden);
  }
  const f = fixture(t);
  f.update({ snapshot_session: "ring-1" });
  t.mock.timers.tick(60000);
  assert.deepEqual(f.requests, []);
  assert.deepEqual(f.previews, []);
});

test("archived preview is fetched once and expires locally at fourteen days", async (t) => {
  const f = fixture(t);
  const capturedAt = Date.now() / 1000;
  const attrs = { snapshot_latest: "image-1", snapshot_captured_at: capturedAt };
  f.update(attrs, false);
  await flush();
  assert.deepEqual(f.previews.at(-1), ["blob:1", capturedAt]);
  f.update(attrs, false);
  assert.equal(f.requests.length, 1);
  t.mock.timers.tick(14 * 86400000);
  assert.deepEqual(f.previews.at(-1), ["", 0]);
  assert.deepEqual(f.revoked, ["blob:1"]);
  f.update(attrs, false);
  assert.equal(f.requests.length, 1);
});

test("retention changes expire old previews and long retention respects timer limits", async (t) => {
  const f = fixture(t);
  const attrs = { snapshot_latest: "image-1", snapshot_captured_at: Date.now() / 1000 - 2 * 86400 };
  f.update(attrs, false);
  await flush();
  f.update({ ...attrs, snapshot_retention_days: 1 }, false);
  assert.deepEqual(f.previews.at(-1), ["", 0]);
  f.update({ ...attrs, snapshot_retention_days: 365 }, false);
  await flush();
  t.mock.timers.tick(2147483647);
  assert.equal(f.previews.at(-1)[0], "blob:2");
  assert.equal(f.requests.length, 2);
});

test("disabled or missing settings never load a preview; stale failures cannot clear a newer one", async (t) => {
  const f = fixture(t);
  const attrs = { snapshot_latest: "old", snapshot_captured_at: Date.now() / 1000 };
  f.update({ ...attrs, stream_snapshots: false }, false);
  f.update({ ...attrs, stream_snapshots: undefined }, false);
  assert.equal(f.requests.length, 0);
  const pending = deferred();
  const fetch = f.hass.fetchWithAuth;
  f.hass.fetchWithAuth = () => pending.promise;
  f.update(attrs, false);
  f.hass.fetchWithAuth = fetch;
  f.update({ ...attrs, snapshot_latest: "new" }, false);
  await flush();
  pending.reject(new Error("late failure"));
  await flush();
  assert.deepEqual(f.previews.at(-1), ["blob:1", attrs.snapshot_captured_at]);
  f.update({ stream_snapshots: false }, false);
  assert.deepEqual(f.previews.at(-1), ["", 0]);
});

test("disable while preview body is pending discards the response", async (t) => {
  const f = fixture(t);
  const pending = deferred();
  f.hass.fetchWithAuth = async () => ({ ...response(), blob: () => pending.promise });
  f.update({ snapshot_latest: "image", snapshot_captured_at: Date.now() / 1000 }, false);
  await flush();
  f.update({ stream_snapshots: false }, false);
  pending.resolve(jpeg());
  await flush();
  assert.equal(f.snapshots.url, "");
  assert.equal(f.previews.some(([url]) => !!url), false);
});

test("failed preview requests are not retried on unchanged state or timers", async (t) => {
  const f = fixture(t);
  const attrs = { snapshot_latest: "image", snapshot_captured_at: Date.now() / 1000 };
  f.hass.fetchWithAuth = async (...args) => { f.requests.push(args); throw new Error("offline"); };
  f.update(attrs);
  await flush();
  for (let i = 0; i < 10; i++) f.update(attrs);
  t.mock.timers.tick(60000);
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0][1].method, undefined);
  assert.equal(f.snapshots.url, "");
});

test("preview requests time out and disposal cancels pending work", async (t) => {
  const f = fixture(t);
  const pending = deferred();
  let signal;
  f.hass.fetchWithAuth = (_url, options) => { signal = options.signal; return pending.promise; };
  const attrs = { snapshot_latest: "image", snapshot_captured_at: Date.now() / 1000 };
  f.update(attrs);
  t.mock.timers.tick(10000);
  assert.equal(signal.aborted, true);
  pending.resolve(response());
  await flush();
  assert.equal(f.snapshots.url, "");
  const second = deferred();
  f.hass.fetchWithAuth = (_url, options) => { signal = options.signal; return second.promise; };
  f.update({ ...attrs, snapshot_latest: "next" });
  f.snapshots.dispose();
  assert.equal(signal.aborted, true);
  second.resolve(response());
  await flush();
  assert.equal(f.snapshots.url, "");
});

test("preview loads need a device entry and valid unexpired timestamp", (t) => {
  const f = fixture(t);
  const attrs = { snapshot_latest: "image", snapshot_captured_at: Date.now() / 1000 };
  f.update(attrs, false, "");
  for (const timestamp of [0, -1, "invalid", Infinity, Date.now() / 1000 - 14 * 86400]) {
    f.update({ ...attrs, snapshot_captured_at: timestamp });
  }
  assert.equal(f.requests.length, 0);
});

test("invalid content types, empty and oversized archives remain blank", async (t) => {
  const f = fixture(t);
  const invalid = [
    { ...response(), ok: false },
    { ...response(), headers: new Headers({ "Content-Type": "text/html" }) },
    { ...response(), blob: async () => new Blob([]) },
    { ...response(), blob: async () => new Blob([new Uint8Array(512 * 1024 + 1)]) },
  ];
  for (const [i, result] of invalid.entries()) {
    f.hass.fetchWithAuth = async () => result;
    f.update({ snapshot_latest: `image-${i}`, snapshot_captured_at: Date.now() / 1000 });
    await flush();
    assert.equal(f.snapshots.url, "");
  }
});

test("synchronous card rerender does not duplicate a preview request", async (t) => {
  const f = fixture(t);
  const attrs = { snapshot_latest: "image", snapshot_captured_at: Date.now() / 1000 };
  f.snapshots.showPreview = () => f.update(attrs);
  f.update(attrs);
  await flush();
  assert.equal(f.requests.length, 1);
  // Restore the callback before teardown, which intentionally clears metadata.
  f.snapshots.showPreview = () => {};
});
