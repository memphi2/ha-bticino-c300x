import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

globalThis.HTMLElement = class {};
globalThis.customElements = { get() {}, define() {} };
const { journalBlob } = await import("../../custom_components/bticino_c300x/frontend/c300x-visitor-journal.js");

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
