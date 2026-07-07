import assert from "node:assert/strict";
import test from "node:test";

import { C300XCardActions } from "../../custom_components/bticino_c300x/frontend/c300x-card-actions.js";

function fakeCard(overrides = {}) {
  const calls = [];
  const card = {
    _error: "",
    _hass: {
      async callService(domain, service, data) {
        calls.push(["service", domain, service, data]);
      },
    },
    _lifecycle: {
      activeHomeCallSession: false,
      answeringDoorbell: false,
      doorbellAnswered: false,
      hangupInProgress: false,
      ringPreviewActive: false,
      startingCall: false,
    },
    _webrtc: {
      pc: null,
      running: false,
    },
    _clearNotice() {
      calls.push(["clear_notice"]);
    },
    _closePeer(clearStatus) {
      calls.push(["close_peer", clearStatus]);
    },
    _doorstationView() {
      return { action: "stream" };
    },
    _isAutoMode() {
      return false;
    },
    _isConfiguredCallActive() {
      return false;
    },
    _isHomeCallMode() {
      return false;
    },
    _serviceData() {
      return { entry_id: "entry-1" };
    },
    async _startAnsweredDoorbellStream() {
      calls.push(["answered_stream"]);
    },
    async _startTalkback(options) {
      calls.push(["talkback", options || {}]);
    },
    _updateState() {
      calls.push(["update_state"]);
    },
    ...overrides,
  };
  return { calls, card };
}

test("action controller answers a ring call before promoting the answered stream", async () => {
  const { calls, card } = fakeCard({
    _doorstationView() {
      return { action: "answer" };
    },
    _lifecycle: {
      activeHomeCallSession: false,
      answeringDoorbell: false,
      doorbellAnswered: false,
      hangupInProgress: false,
      ringPreviewActive: true,
      startingCall: false,
    },
    _webrtc: {
      pc: {},
      running: true,
    },
  });
  const actions = new C300XCardActions(card);

  await actions.handlePrimaryAction();

  assert.deepEqual(calls, [
    ["service", "bticino_c300x", "answer_doorbell_call", { entry_id: "entry-1" }],
    ["answered_stream"],
  ]);
  assert.equal(card._lifecycle.answeringDoorbell, false);
  assert.equal(card._lifecycle.doorbellAnswered, true);
});

test("action controller stops doorstation media before closing the local peer", async () => {
  const { calls, card } = fakeCard({
    _doorstationView() {
      return { action: "hang_up" };
    },
    _lifecycle: {
      activeHomeCallSession: false,
      answeringDoorbell: false,
      doorbellAnswered: true,
      hangupInProgress: false,
      ringPreviewActive: false,
      startingCall: false,
    },
  });
  const actions = new C300XCardActions(card);

  await actions.handlePrimaryAction();

  assert.deepEqual(calls, [
    ["service", "bticino_c300x", "hangup_doorbell_call", { entry_id: "entry-1" }],
    ["service", "bticino_c300x", "stop_doorbell_video", { entry_id: "entry-1" }],
    ["close_peer", true],
  ]);
});

test("action controller starts a home-call audio session through the shared talkback path", async () => {
  const { calls, card } = fakeCard({
    _isAutoMode() {
      return true;
    },
  });
  const actions = new C300XCardActions(card);

  await actions.handleHomeCallAction();

  assert.deepEqual(calls, [
    ["clear_notice"],
    ["talkback", { homeCall: true }],
    ["update_state"],
  ]);
  assert.equal(card._lifecycle.activeHomeCallSession, true);
  assert.equal(card._lifecycle.startingCall, false);
});
