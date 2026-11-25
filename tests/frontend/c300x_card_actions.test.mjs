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
      return { entity_id: "camera.door" };
    },
    _callData() {
      return { ...this._serviceData(), call_id: "0badc0de-1" };
    },
    _stopVideoData() {
      return { entity_id: "button.stop_video" };
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
    ["service", "bticino_c300x", "answer_call", { entity_id: "camera.door", call_id: "0badc0de-1" }],
    ["answered_stream"],
    ["update_state"],
  ]);
  assert.equal(card._lifecycle.answeringDoorbell, false);
  assert.equal(card._lifecycle.doorbellAnswered, true);
});

test("an answered call stays answered when its stream does not start", async () => {
  const { calls, card } = fakeCard({
    _doorstationView: () => ({ action: "answer" }),
    async _startTalkback() {
      calls.push(["talkback"]);
      // The failure path of the real start reports the error and closes the
      // peer: that clears the peer state and ends the media generation.
      card._error = "WebRTC offer failed";
      card._mediaGeneration += 1;
      card._lifecycle.doorbellAnswered = false;
      card._lifecycle.answeringDoorbell = false;
      return false;
    },
  });
  await new C300XCardActions(card).handlePrimaryAction();
  assert.deepEqual(calls.slice(0, 2), [
    ["service", "bticino_c300x", "answer_call", { entity_id: "camera.door", call_id: "0badc0de-1" }],
    ["talkback"],
  ]);
  // Hang up must stay possible for the call that is answered on the device.
  assert.equal(card._lifecycle.doorbellAnswered, true);
  assert.equal(card._lifecycle.answeringDoorbell, false);
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

test("answering a ring call is single-flight while the service is pending", async () => {
  let answer;
  const { calls, card } = fakeCard({
    _doorstationView: () => ({ action: "answer" }),
    _hass: { callService() {
      calls.push(["answer"]);
      return new Promise((resolve) => { answer = resolve; });
    } },
  });
  const actions = new C300XCardActions(card);
  const first = actions.handlePrimaryAction();
  await actions.handlePrimaryAction();
  assert.deepEqual(calls, [["answer"]]);
  answer();
  await first;
  assert.equal(calls.filter(([kind]) => kind === "talkback").length, 1);
});

test("a stale device-action error cannot overwrite a replacement card's feedback", async () => {
  let fail;
  const { calls, card } = fakeCard({
    _deviceActionEntity: () => "button.door_unlock",
    _hass: { callService() {
      return new Promise((resolve, reject) => { fail = reject; });
    } },
  });
  const actions = new C300XCardActions(card);
  const action = actions.handleDeviceAction("door_unlock");
  card._resourceGeneration = 1;
  card._lifecycle = { ...card._lifecycle };
  card._error = "New camera feedback";
  fail(new Error("Old camera error"));
  await action;
  assert.equal(card._error, "New camera feedback");
  assert.deepEqual(calls, [["clear_notice"], ["update_state"]]);
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
    ["service", "bticino_c300x", "hangup_call", { entity_id: "camera.door", call_id: "0badc0de-1" }],
    ["service", "button", "press", { entity_id: "button.stop_video" }],
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
        if (service === "hangup_call") {
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
    ["service", "bticino_c300x", "hangup_call", { entity_id: "camera.door", call_id: "0badc0de-1" }],
    ["service", "button", "press", { entity_id: "button.stop_video" }],
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
  test(`hidden ${key} cannot execute a device action`, async () => {
    const { calls, card } = fakeCard({
      _config: { [`show_${key}`]: false },
      _deviceActionEntity: () => `button.${key}`,
    });
    const actions = new C300XCardActions(card);
    await actions.handleDeviceAction(key);
    assert.deepEqual(calls, []);
    assert.equal(actions.deviceActionPending(key), false);
  });

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

test("hanging up a call that already ended is not an error", async () => {
  const { calls, card } = fakeCard({
    _doorstationView: () => ({ action: "hang_up" }),
    _hass: {
      async callService(domain, service, data) {
        calls.push(["service", domain, service, data]);
        if (service === "hangup_call") {
          throw { code: "service_validation_error", translation_key: "call_not_current", message: "gone" };
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
  await new C300XCardActions(card).handlePrimaryAction();
  assert.deepEqual(calls, [
    ["service", "bticino_c300x", "hangup_call", { entity_id: "camera.door", call_id: "0badc0de-1" }],
    ["service", "button", "press", { entity_id: "button.stop_video" }],
    ["close_peer", true],
  ]);
  assert.equal(card._error, "");
});
