import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  c300xResolveEntity, c300xRelatedEntity, c300xDeviceActionEntity, c300xEntryId,
  C300X_CAMERA_OBJECT_ID, C300X_MEDIA_READINESS_OBJECT_ID,
} from "../../custom_components/bticino_c300x/frontend/c300x-entity-resolver.js";
import { C300XCardActions } from "../../custom_components/bticino_c300x/frontend/c300x-card-actions.js";

const contract = JSON.parse(readFileSync(0, "utf8"));
assert.equal(contract.expected.length, 2);
for (const snapshot of ["enabled", "disabled"]) {
  const hass = contract[snapshot];
  const calls = [];
  hass.callService = async (...args) => { calls.push(args); };
  for (const [index, expected] of contract.expected.entries()) {
    const config = { entry_id: expected.entry_id };
    assert.equal(c300xResolveEntity(hass, config, "camera", C300X_CAMERA_OBJECT_ID), expected.doorbell_camera);
    assert.equal(c300xEntryId(hass, config, expected.doorbell_camera), expected.entry_id);
    assert.equal(c300xRelatedEntity(hass, config, "sensor", C300X_MEDIA_READINESS_OBJECT_ID, "readiness_entity"), expected.media_readiness);
    assert.equal(hass.states[expected.doorbell_camera].attributes.media_primary_action, "start_stream");
    const card = { _hass: hass, _deviceActionEntity: (key) => c300xDeviceActionEntity(hass, config, key),
      _clearNotice() {}, _updateState() {} };
    const actions = new C300XCardActions(card);
    for (const key of ["door_unlock", "stair_light"]) {
      const unavailable = snapshot === "disabled" && index === 1 && key === "stair_light";
      assert.equal(card._deviceActionEntity(key), unavailable ? "" : expected[key]);
      const before = calls.length;
      await actions.handleDeviceAction(key);
      if (unavailable) assert.equal(calls.length, before, "Disabled control fell back to another device");
      else assert.deepEqual(calls.at(-1), ["button", "press", { entity_id: expected[key] }]);
    }
  }
  const mismatch = { entry_id: contract.expected[0].entry_id, entity: contract.expected[1].doorbell_camera };
  assert.equal(c300xDeviceActionEntity(hass, mismatch, "door_unlock"), "");
}
console.log("Generated HA/card contract passed: renamed devices, display registry, disabled controls and action routing");
