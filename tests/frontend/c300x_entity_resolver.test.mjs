import assert from "node:assert/strict";
import test from "node:test";

import {
  C300X_AUDIO_CODEC_OBJECT_ID,
  C300X_CAMERA_OBJECT_ID,
  C300X_DEFAULT_CONFIG,
  C300X_MEDIA_READINESS_OBJECT_ID,
  C300X_PLATFORM,
  c300xDeviceActionEntity,
  c300xEntityId,
  c300xEntryId,
  c300xFirstEntity,
  c300xObjectSuffix,
  c300xRelatedEntity,
  c300xResolveEntity,
} from "../../custom_components/bticino_c300x/frontend/c300x-entity-resolver.js";

function hass({
  states = {},
  entities = {},
  devices = {},
} = {}) {
  return { states, entities, devices };
}

function registryEntry({
  configEntryId = "entry-1",
  platform = C300X_PLATFORM,
  translationKey = "doorbell_camera",
  uniqueId = "device_doorbell_camera",
} = {}) {
  return {
    config_entry_id: configEntryId,
    platform,
    translation_key: translationKey,
    unique_id: uniqueId,
  };
}

test("default config stays minimal and auto mode based", () => {
  assert.deepEqual(C300X_DEFAULT_CONFIG, {
    mode: "auto",
    ringback_tone: true,
    ringback_volume: 12,
  });
});

test("physical actions stay on the selected device and default door", () => {
  const state = hass({
    entities: {
      "camera.front": registryEntry({ configEntryId: "entry-2" }),
      "button.bticino_c300x_stair_light": registryEntry({ configEntryId: "entry-2", translationKey: "reboot" }),
      "button.wrong_door": registryEntry({ translationKey: "door_unlock" }),
      "button.garage": registryEntry({ configEntryId: "entry-2", translationKey: "door_unlock" }),
      "button.front_door": registryEntry({ configEntryId: "entry-2", translationKey: "door_unlock" }),
      "button.front_light": registryEntry({ configEntryId: "entry-2", translationKey: "stair_light" }),
    },
    states: {
      "camera.front": {},
      "button.bticino_c300x_stair_light": {},
      "button.wrong_door": { attributes: { lock_id: "default" } },
      "button.garage": { attributes: { lock_id: "garage" } },
      "button.front_door": { attributes: { lock_id: "default" } },
      "button.front_light": {},
    },
  });
  const config = { entity: "camera.front" };
  assert.equal(c300xDeviceActionEntity(state, config, "door_unlock"), "button.front_door");
  assert.equal(c300xDeviceActionEntity(state, config, "stair_light"), "button.front_light");
  assert.equal(c300xDeviceActionEntity(state, { ...config, entry_id: "entry-1" }, "door_unlock"), "");
  assert.equal(c300xDeviceActionEntity(state, { entity: "camera.missing" }, "door_unlock"), "");
  assert.equal(c300xDeviceActionEntity(state, config, "reboot"), "");
  delete state.states["button.front_door"];
  assert.equal(c300xDeviceActionEntity(state, config, "door_unlock"), "");
  delete state.entities["camera.front"];
  assert.equal(c300xDeviceActionEntity(state, config, "stair_light"), "");
});

test("physical actions use HA display registry device IDs without full registry metadata", () => {
  const state = hass({
    entities: {
      "camera.front": { platform: C300X_PLATFORM, device_id: "front", translation_key: "doorbell_camera" },
      "button.other": { platform: C300X_PLATFORM, device_id: "other", translation_key: "door_unlock" },
      "button.door": { platform: C300X_PLATFORM, device_id: "front", translation_key: "door_unlock" },
      "button.light": { platform: C300X_PLATFORM, device_id: "front", translation_key: "stair_light" },
    },
    states: {
      "camera.front": {},
      "button.other": { attributes: { lock_id: "default" } },
      "button.door": { attributes: { lock_id: "default" } },
      "button.light": {},
    },
  });
  const config = { entity: "camera.front" };
  assert.equal(c300xDeviceActionEntity(state, config, "door_unlock"), "button.door");
  assert.equal(c300xDeviceActionEntity(state, config, "stair_light"), "button.light");
  state.devices = { front: { config_entries: ["entry-1"] } };
  assert.equal(c300xDeviceActionEntity(state, { ...config, entry_id: "entry-1" }, "door_unlock"), "button.door");
  assert.equal(c300xDeviceActionEntity(state, { ...config, entry_id: "entry-2" }, "door_unlock"), "");
  delete state.entities["button.door"].device_id;
  assert.equal(c300xDeviceActionEntity(state, config, "door_unlock"), "");
});

test("object suffix and entity id helpers keep multi-device suffixes stable", () => {
  assert.equal(c300xObjectSuffix(C300X_CAMERA_OBJECT_ID, C300X_CAMERA_OBJECT_ID), "");
  assert.equal(c300xObjectSuffix(`${C300X_CAMERA_OBJECT_ID}_entry2`, C300X_CAMERA_OBJECT_ID), "_entry2");
  assert.equal(c300xObjectSuffix("other_camera", C300X_CAMERA_OBJECT_ID), null);
  assert.equal(
    c300xEntityId("camera", C300X_CAMERA_OBJECT_ID, "_entry2"),
    `camera.${C300X_CAMERA_OBJECT_ID}_entry2`,
  );
});

test("first entity prefers registry matches for the requested config entry", () => {
  const state = hass({
    states: {
      [`camera.${C300X_CAMERA_OBJECT_ID}`]: {},
      "camera.custom_door": {},
      [`sensor.${C300X_MEDIA_READINESS_OBJECT_ID}`]: {},
    },
    entities: {
      [`camera.${C300X_CAMERA_OBJECT_ID}`]: registryEntry({ configEntryId: "entry-1" }),
      "camera.custom_door": registryEntry({
        configEntryId: "entry-2",
        translationKey: "doorbell_camera",
        uniqueId: "custom_doorbell_camera",
      }),
      [`sensor.${C300X_MEDIA_READINESS_OBJECT_ID}`]: registryEntry({
        configEntryId: "entry-1",
        translationKey: "media_readiness",
        uniqueId: "device_media_readiness",
      }),
    },
  });

  assert.equal(
    c300xFirstEntity(state, "camera", C300X_CAMERA_OBJECT_ID, "entry-2"),
    "camera.custom_door",
  );
  assert.equal(
    c300xFirstEntity(state, "camera", C300X_CAMERA_OBJECT_ID, "missing-entry"),
    undefined,
  );
});

test("registry entries without states are ignored when HA states are available", () => {
  const state = hass({
    states: {
      [`camera.${C300X_CAMERA_OBJECT_ID}_visible`]: {},
    },
    entities: {
      "camera.hidden": registryEntry({
        configEntryId: "entry-1",
        translationKey: "doorbell_camera",
      }),
      [`camera.${C300X_CAMERA_OBJECT_ID}_visible`]: registryEntry({
        configEntryId: "entry-1",
        translationKey: "doorbell_camera",
      }),
    },
  });

  assert.equal(
    c300xFirstEntity(state, "camera", C300X_CAMERA_OBJECT_ID, "entry-1"),
    `camera.${C300X_CAMERA_OBJECT_ID}_visible`,
  );
});

test("configured camera never falls back to another camera when missing", () => {
  const state = hass({
    states: {
      "camera.configured": {},
      "camera.fallback": {},
    },
    entities: {
      "camera.fallback": registryEntry({ configEntryId: "entry-1" }),
    },
  });

  assert.equal(
    c300xResolveEntity(
      state,
      { entity: "camera.configured", entry_id: "entry-1" },
      "camera",
      C300X_CAMERA_OBJECT_ID,
    ),
    "camera.configured",
  );
  assert.equal(
    c300xResolveEntity(
      state,
      { entity: "camera.missing", entry_id: "entry-1" },
      "camera",
      C300X_CAMERA_OBJECT_ID,
    ),
    "camera.missing",
  );
});

test("related media readiness follows the selected camera config entry", () => {
  const state = hass({
    states: {
      [`camera.${C300X_CAMERA_OBJECT_ID}`]: {},
      "sensor.readiness_one": {},
      "sensor.readiness_two": {},
    },
    entities: {
      [`camera.${C300X_CAMERA_OBJECT_ID}`]: registryEntry({ configEntryId: "entry-2" }),
      "sensor.readiness_one": registryEntry({
        configEntryId: "entry-1",
        translationKey: "media_readiness",
        uniqueId: "one_media_readiness",
      }),
      "sensor.readiness_two": registryEntry({
        configEntryId: "entry-2",
        translationKey: "media_readiness",
        uniqueId: "two_media_readiness",
      }),
    },
  });

  assert.equal(
    c300xEntryId(state, {}, `camera.${C300X_CAMERA_OBJECT_ID}`),
    "entry-2",
  );
  assert.equal(
    c300xRelatedEntity(
      state,
      { entity: `camera.${C300X_CAMERA_OBJECT_ID}` },
      "sensor",
      C300X_MEDIA_READINESS_OBJECT_ID,
      "media_readiness_entity",
    ),
    "sensor.readiness_two",
  );
});

test("configured related entity wins when it exists", () => {
  const state = hass({
    states: {
      "sensor.manual_readiness": {},
    },
  });

  assert.equal(
    c300xRelatedEntity(
      state,
      { media_readiness_entity: "sensor.manual_readiness" },
      "sensor",
      C300X_MEDIA_READINESS_OBJECT_ID,
      "media_readiness_entity",
    ),
    "sensor.manual_readiness",
  );
});

function displayHass(device) {
  const entities = {};
  const states = {};
  for (const id of ["other", "front"]) {
    for (const [domain, key] of [
      ["camera", "doorbell_camera"], ["sensor", "media_readiness"],
      ["select", "audio_codec"], ["button", "door_unlock"], ["button", "stair_light"],
    ]) {
      const entityId = `${domain}.${id}_${key}`;
      entities[entityId] = { platform: C300X_PLATFORM, device_id: id, translation_key: key };
      states[entityId] = { attributes: { lock_id: "default" } };
    }
  }
  return hass({ entities, states, devices: { front: device, other: { config_entry_id: "other-entry" } } });
}

for (const [name, device] of [
  ["current", { config_entry_id: "front-entry" }],
  ["legacy", { config_entries: ["front-entry"] }],
  ["current with obsolete legacy owners", { config_entry_id: "front-entry", config_entries: ["other-entry"] }],
]) {
  test(`display registry resolves renamed camera, sensors, controls and service owner (${name})`, () => {
    const state = displayHass(device);
    const config = { entity: "camera.front_doorbell_camera", entry_id: "front-entry" };
    assert.equal(c300xFirstEntity(state, "camera", C300X_CAMERA_OBJECT_ID, "front-entry"), config.entity);
    assert.equal(c300xEntryId(state, config, config.entity), "front-entry");
    assert.equal(c300xRelatedEntity(state, config, "sensor", C300X_MEDIA_READINESS_OBJECT_ID), "sensor.front_media_readiness");
    assert.equal(c300xRelatedEntity(state, config, "select", C300X_AUDIO_CODEC_OBJECT_ID), "select.front_audio_codec");
    assert.equal(c300xDeviceActionEntity(state, config, "door_unlock"), "button.front_door_unlock");
    assert.equal(c300xDeviceActionEntity(state, config, "stair_light"), "button.front_stair_light");

    const wrong = { ...config, entry_id: "other-entry" };
    assert.equal(c300xEntryId(state, wrong, config.entity), "");
    assert.equal(c300xRelatedEntity(state, wrong, "sensor", C300X_MEDIA_READINESS_OBJECT_ID), undefined);
    assert.equal(c300xDeviceActionEntity(state, wrong, "door_unlock"), "");
  });
}

test("same-device lookups do not need an owner but service routing requires an unambiguous owner", () => {
  for (const device of [undefined, {}, { config_entries: [] }, { config_entries: ["front-entry", "other-entry"] }]) {
    const state = displayHass(device);
    const config = { entity: "camera.front_doorbell_camera" };
    assert.equal(c300xEntryId(state, config, config.entity), "");
    assert.equal(c300xRelatedEntity(state, config, "select", C300X_AUDIO_CODEC_OBJECT_ID), "select.front_audio_codec");
    assert.equal(c300xDeviceActionEntity(state, config, "door_unlock"), "button.front_door_unlock");
    assert.equal(c300xDeviceActionEntity(state, { ...config, entry_id: "front-entry" }, "door_unlock"), "");
  }
});

test("missing related entities never resolve to another device, even with the same owner", () => {
  const state = displayHass({ config_entry_id: "front-entry" });
  state.devices.other.config_entry_id = "front-entry";
  const config = { entity: "camera.front_doorbell_camera" };
  delete state.states["sensor.front_media_readiness"];
  delete state.states["select.front_audio_codec"];
  delete state.states["button.front_door_unlock"];
  assert.equal(c300xRelatedEntity(state, config, "sensor", C300X_MEDIA_READINESS_OBJECT_ID), undefined);
  assert.equal(c300xRelatedEntity(state, config, "select", C300X_AUDIO_CODEC_OBJECT_ID), undefined);
  assert.equal(c300xDeviceActionEntity(state, config, "door_unlock"), "");
  assert.equal(c300xResolveEntity(state, { entry_id: "missing" }, "camera", C300X_CAMERA_OBJECT_ID), "");
  delete state.entities[config.entity];
  assert.equal(c300xRelatedEntity(state, config, "sensor", C300X_MEDIA_READINESS_OBJECT_ID), undefined);
  assert.equal(c300xEntryId(state, config, config.entity), "");
});

test("a missing manual related entity and conflicting registry roles never trigger name guessing", () => {
  const state = displayHass({ config_entry_id: "front-entry" });
  const config = { entity: "camera.front_doorbell_camera", media_readiness_entity: "sensor.removed" };
  assert.equal(c300xRelatedEntity(state, config, "sensor", C300X_MEDIA_READINESS_OBJECT_ID, "media_readiness_entity"), "sensor.removed");
  const misleading = `sensor.${C300X_MEDIA_READINESS_OBJECT_ID}`;
  state.entities[misleading] = { platform: C300X_PLATFORM, device_id: "front", translation_key: "other" };
  state.states[misleading] = {};
  delete state.states["sensor.front_media_readiness"];
  delete state.states["sensor.other_media_readiness"];
  assert.equal(c300xFirstEntity(state, "sensor", C300X_MEDIA_READINESS_OBJECT_ID), undefined);
});
