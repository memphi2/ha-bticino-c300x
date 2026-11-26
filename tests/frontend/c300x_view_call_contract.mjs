// The card ends an on-demand view by its call, with the camera attributes
// Home Assistant really publishes for it (tests/test_card_view_call.py).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { C300XCardActions } from "../../custom_components/bticino_c300x/frontend/c300x-card-actions.js";

const { attributes } = JSON.parse(readFileSync(0, "utf8"));
const calls = [];
const card = {
  _error: "",
  _hass: { async callService(...args) { calls.push(args); } },
  _lifecycle: {
    activeHomeCallSession: false, answeringDoorbell: false, doorbellAnswered: false,
    hangupInProgress: false, ringPreviewActive: false, startingCall: false,
  },
  _webrtc: { pc: null, running: false },
  _clearNotice() {},
  _closePeer() {},
  _updateState() {},
  _isHomeCallMode() { return false; },
  _doorstationView() { return { action: "hang_up" }; },
  // No Stop doorbell video button: the view ends by its call.
  _stopVideoData() { throw new Error("device_unresolved"); },
  _serviceData() { return { entity_id: "camera.door" }; },
  _cameraEntity() { return { state: "streaming", attributes }; },
  // As the card's own _callData: the call id of the camera's current call.
  _callData() {
    const callId = this._cameraEntity()?.attributes?.call_id;
    return callId ? { ...this._serviceData(), call_id: callId } : this._serviceData();
  },
};
await new C300XCardActions(card).handlePrimaryAction();
assert.deepEqual(calls, [
  ["bticino_c300x", "hangup_call", { entity_id: "camera.door", call_id: attributes.call_id }],
]);
assert.equal(card._error, "");
console.log("The card ends the on-demand view by its call");
