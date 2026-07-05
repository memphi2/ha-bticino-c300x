import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const frontendRoot = new URL("../../custom_components/bticino_c300x/frontend/", import.meta.url);

function source(filename) {
  return readFileSync(new URL(filename, frontendRoot), "utf8");
}

test("pure state modules stay free of DOM, service, and WebRTC dependencies", () => {
  for (const filename of [
    "c300x-state-model.js",
    "c300x-card-lifecycle.js",
    "c300x-ring-preview-state.js",
  ]) {
    const text = source(filename);

    assert.equal(text.includes("callService"), false, filename);
    assert.equal(text.includes("document."), false, filename);
    assert.equal(text.includes("querySelector"), false, filename);
    assert.equal(text.includes("RTCPeerConnection"), false, filename);
    assert.equal(text.includes("MediaStream"), false, filename);
  }
});

test("frontend module ownership keeps orchestration out of the card renderer", () => {
  const card = source("c300x-doorbell-call-card.js");
  const actions = source("c300x-card-actions.js");
  const editor = source("c300x-card-editor.js");
  const template = source("c300x-card-template.js");
  const webrtc = source("c300x-webrtc-client.js");

  assert.equal(card.includes("callService("), false);
  assert.equal(card.includes("C300XCardActions"), true);
  assert.equal(actions.includes("callService("), true);
  assert.equal(editor.includes("c300x-doorbell-call-card.js"), false);
  assert.equal(template.includes("callService"), false);
  assert.equal(template.includes("RTCPeerConnection"), false);
  assert.equal(webrtc.includes("C300XMediaAttachment"), true);
});
