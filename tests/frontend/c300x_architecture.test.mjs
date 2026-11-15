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

test("the card footer is one row at every width, with the readiness beside the status", () => {
  const template = source("c300x-card-template.js");

  // Buttons left, text, buttons right: no width may move the text below them.
  assert.match(template, /grid-template-areas: "controls text devices";/);
  assert.equal(template.match(/grid-template-areas:/g).length, 1);
  assert.equal(template.includes('"text text"'), false);
  // The readiness sits on the status line, not on a line of its own.
  const statusLine = template.slice(template.indexOf('<div class="status-line">'));
  assert.ok(statusLine.indexOf('<div class="secondary">') < statusLine.indexOf('<div class="readiness hidden">'));
  assert.ok(statusLine.indexOf('<div class="readiness hidden">') < statusLine.indexOf("</div>\n          </div>"));
  // Text that does not fit is cut instead of wrapping the row.
  for (const rule of [".title", ".secondary", ".readiness-text"]) {
    const body = template.slice(template.indexOf(`        ${rule} {`));
    assert.match(body.slice(0, body.indexOf("}")), /text-overflow: ellipsis;/, rule);
  }
});
