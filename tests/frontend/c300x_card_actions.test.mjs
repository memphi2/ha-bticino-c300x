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
    ["update_state"],
  ]);
  assert.equal(card._lifecycle.answeringDoorbell, false);
  assert.equal(card._lifecycle.doorbellAnswered, true);
});

test("answering fails visibly without sending an unscoped service or starting media", async () => {
  const { calls, card } = fakeCard({
    _doorstationView: () => ({ action: "answer" }),
    _serviceData() { throw new Error("Camera device assignment unavailable"); },
  });
  await new C300XCardActions(card).handlePrimaryAction();
  assert.deepEqual(calls, [["update_state"]]);
  assert.equal(card._error, "Camera device assignment unavailable");
  assert.equal(card._lifecycle.answeringDoorbell, false);
  assert.equal(card._lifecycle.doorbellAnswered, false);
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

test("action controller keeps ring-call hangup failures visible after video stop", async () => {
  const { calls, card } = fakeCard({
    _doorstationView() {
      return { action: "hang_up" };
    },
    _hass: {
      async callService(domain, service, data) {
        calls.push(["service", domain, service, data]);
        if (service === "hangup_doorbell_call") {
          throw new Error("ring hangup failed");
        }
      },
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
    ["close_peer", false],
  ]);
  assert.equal(card._error, "ring hangup failed");
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

for (const key of ["door_unlock", "stair_light"]) {
  test(`${key} uses one HA button press without changing media`, async () => {
    const { calls, card } = fakeCard({ _deviceActionEntity: () => `button.${key}` });
    const actions = new C300XCardActions(card);
    await actions.handleDeviceAction(key);
    assert.deepEqual(calls, [
      ["clear_notice"], ["update_state"],
      ["service", "button", "press", { entity_id: `button.${key}` }],
      ["update_state"],
    ]);
    assert.equal(actions.deviceActionPending(key), false);
  });
}

test("physical actions prevent duplicate requests and retain errors", async () => {
  let reject;
  let presses = 0;
  const { card } = fakeCard({
    _deviceActionEntity: () => "button.door",
    _hass: { callService() {
      presses++;
      return new Promise((_resolve, fail) => { reject = fail; });
    } },
  });
  const actions = new C300XCardActions(card);
  const pending = actions.handleDeviceAction("door_unlock");
  assert.equal(actions.deviceActionPending("door_unlock"), true);
  await actions.handleDeviceAction("door_unlock");
  assert.equal(presses, 1);
  reject(new Error("Not permitted"));
  await pending;
  assert.equal(card._error, "Not permitted");
  assert.equal(actions.deviceActionPending("door_unlock"), false);
});

test("missing or unavailable device buttons do not execute commands", async () => {
  const { calls, card } = fakeCard({ _deviceActionEntity: () => "" });
  const actions = new C300XCardActions(card);
  await actions.handleDeviceAction("door_unlock");
  card._deviceActionEntity = () => "button.door";
  card._hass.states = { "button.door": { state: "unavailable" } };
  await actions.handleDeviceAction("door_unlock");
  assert.deepEqual(calls, []);
});
