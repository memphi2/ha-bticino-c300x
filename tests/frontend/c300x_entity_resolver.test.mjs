import assert from "node:assert/strict";
import test from "node:test";

import {
  C300X_CAMERA_OBJECT_ID,
  C300X_DEFAULT_CONFIG,
  C300X_MEDIA_READINESS_OBJECT_ID,
  C300X_PLATFORM,
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
} = {}) {
  return { states, entities };
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
    `camera.${C300X_CAMERA_OBJECT_ID}`,
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

test("configured camera is used only while it exists in HA states", () => {
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
    "camera.fallback",
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
