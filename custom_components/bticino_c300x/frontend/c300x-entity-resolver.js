export const C300X_CARD_TAG = "c300x-doorbell-call-card";
export const C300X_CARD_TYPE = `custom:${C300X_CARD_TAG}`;
export const C300X_PLATFORM = "bticino_c300x";
// Entities are found by their registry role (platform and translation key)
// and their device, never by an entity id.
export const C300X_CAMERA_KEY = "doorbell_camera";
export const C300X_MEDIA_READINESS_KEY = "media_readiness";
export const C300X_STOP_VIDEO_KEY = "stop_doorbell_video";
export const C300X_DOCUMENTATION_URL = "https://github.com/memphi2/ha-bticino-c300x#doorbell-video-ring-calls-and-talkback";
export const C300X_DEFAULT_CONFIG = {
  mode: "auto",
  ringback_tone: true,
  ringback_volume: 12,
};

function c300xStateExists(hass, entityId) {
  return !hass?.states || !!hass.states[entityId];
}

function c300xRegistryEntryId(hass, registryEntry) {
  const device = hass?.devices?.[registryEntry?.device_id];
  // Current HA exposes a single owner; older display registries only list owners.
  return device?.config_entry_id || registryEntry?.config_entry_id
    || (device?.config_entries?.length === 1 ? device.config_entries[0] : "")
    || "";
}

// Outdoor unit devices hang below their station: compare the stations.
function c300xStationDevice(hass, deviceId) {
  return hass?.devices?.[deviceId]?.via_device_id || deviceId;
}

function c300xSameDevice(hass, camera, candidate) {
  if (camera?.device_id) {
    return !!candidate?.device_id
      && c300xStationDevice(hass, candidate.device_id) === c300xStationDevice(hass, camera.device_id);
  }
  const entryId = c300xRegistryEntryId(hass, camera);
  return !!entryId && c300xRegistryEntryId(hass, candidate) === entryId;
}

export function c300xRegistryEntityMatches(entityId, registryEntry, domain, translationKey) {
  return entityId.split(".")[0] === domain
    && registryEntry?.platform === C300X_PLATFORM
    && registryEntry?.translation_key === translationKey;
}

export function c300xFirstEntity(hass, domain, translationKey, entryId = "") {
  return Object.entries(hass?.entities || {}).find(
    ([entityId, registryEntry]) => (
      c300xStateExists(hass, entityId)
      && (!entryId || c300xRegistryEntryId(hass, registryEntry) === entryId)
      && c300xRegistryEntityMatches(entityId, registryEntry, domain, translationKey)
    ),
  )?.[0];
}

export function c300xResolveEntity(hass, config, domain, translationKey) {
  return config?.entity
    || c300xFirstEntity(hass, domain, translationKey, config?.entry_id || "")
    || "";
}

export function c300xRelatedEntity(hass, config, domain, translationKey, configKey) {
  const configured = config?.[configKey];
  if (configured) {
    return configured;
  }

  const cameraEntityId = c300xResolveEntity(hass, config, "camera", C300X_CAMERA_KEY);
  const camera = hass?.entities?.[cameraEntityId];
  if (camera?.platform !== C300X_PLATFORM
    || (config?.entry_id && !c300xEntryId(hass, config, cameraEntityId))) {
    return undefined;
  }
  return Object.keys(hass?.entities || {}).find((entityId) => (
    c300xStateExists(hass, entityId)
    && c300xSameDevice(hass, camera, hass.entities[entityId])
    && c300xRegistryEntityMatches(entityId, hass.entities[entityId], domain, translationKey)
  ));
}

// The device page names a C100X "Classe 100X"; every other device keeps the C300X texts.
export function c300xDeviceModel(hass, entityId) {
  const deviceId = hass?.entities?.[entityId]?.device_id;
  return hass?.devices?.[deviceId]?.model === "Classe 100X" ? "C100X" : "C300X";
}

export function c300xEntryId(hass, config, entityId) {
  const registryEntry = hass?.entities?.[entityId || config?.entity];
  if (registryEntry?.platform !== C300X_PLATFORM) {
    return "";
  }
  const entryId = c300xRegistryEntryId(hass, registryEntry);
  return config?.entry_id && config.entry_id !== entryId ? "" : entryId;
}

export function c300xDeviceActionEntity(hass, config, key) {
  if (!config || !["door_unlock", "stair_light"].includes(key)) {
    return "";
  }
  const camera = c300xResolveEntity(hass, config, "camera", C300X_CAMERA_KEY);
  const cameraRegistry = hass?.entities?.[camera];
  const entryId = c300xEntryId(hass, config, camera);
  // HA's display registry exposes device_id, not config_entry_id or unique_id.
  // Physical actions must never fall back to a different device.
  if (cameraRegistry?.platform !== C300X_PLATFORM
    || (config.entry_id && !entryId)) {
    return "";
  }
  if (key === "door_unlock") {
    // The camera names the door of the calling outdoor unit, else of the default one.
    const door = hass?.states?.[camera]?.attributes?.door_entity_id;
    const entry = hass.entities?.[door];
    return door && hass?.states?.[door] && entry?.platform === C300X_PLATFORM
      && c300xSameDevice(hass, cameraRegistry, entry) ? door : "";
  }
  return Object.keys(hass?.entities || {}).find((entityId) => {
    const entry = hass.entities[entityId];
    return !!hass?.states?.[entityId]
      && entityId.startsWith("button.")
      && entry.platform === C300X_PLATFORM
      && c300xSameDevice(hass, cameraRegistry, entry)
      && entry.translation_key === key;
  }) || "";
}
