export const C300X_CARD_TAG = "c300x-doorbell-call-card";
export const C300X_CARD_TYPE = `custom:${C300X_CARD_TAG}`;
export const C300X_PLATFORM = "bticino_c300x";
export const C300X_CAMERA_OBJECT_ID = "bticino_c300x_doorbell_camera";
export const C300X_MEDIA_READINESS_OBJECT_ID = "bticino_c300x_media_readiness";
export const C300X_AUDIO_CODEC_OBJECT_ID = "bticino_c300x_audio_codec";
export const C300X_DOCUMENTATION_URL = "https://github.com/memphi2/ha-bticino-c300x#doorbell-video-ring-calls-and-talkback";
export const C300X_DEFAULT_CONFIG = {
  mode: "auto",
  ringback_tone: true,
  ringback_volume: 12,
};

export function c300xObjectSuffix(objectId, baseObjectId) {
  if (objectId === baseObjectId) {
    return "";
  }
  if (objectId?.startsWith(`${baseObjectId}_`)) {
    return objectId.slice(baseObjectId.length);
  }
  return null;
}

export function c300xEntityId(domain, baseObjectId, suffix) {
  return `${domain}.${baseObjectId}${suffix || ""}`;
}

function c300xTranslationKey(baseObjectId) {
  return baseObjectId.startsWith(`${C300X_PLATFORM}_`)
    ? baseObjectId.slice(C300X_PLATFORM.length + 1)
    : baseObjectId;
}

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

function c300xSameDevice(hass, camera, candidate) {
  if (camera?.device_id) {
    return candidate?.device_id === camera.device_id;
  }
  const entryId = c300xRegistryEntryId(hass, camera);
  return !!entryId && c300xRegistryEntryId(hass, candidate) === entryId;
}

function c300xRegistryEntityMatches(
  entityId,
  registryEntry,
  domain,
  baseObjectId,
) {
  const [entityDomain, objectId] = entityId.split(".");
  if (entityDomain !== domain) {
    return false;
  }
  const translationKey = c300xTranslationKey(baseObjectId);
  const uniqueId = String(registryEntry?.unique_id || "");
  return (
    registryEntry?.platform === C300X_PLATFORM
    && (
      registryEntry?.translation_key
        ? registryEntry.translation_key === translationKey
        : uniqueId.endsWith(`_${translationKey}`)
          || c300xObjectSuffix(objectId, baseObjectId) !== null
    )
  );
}

export function c300xFirstEntity(hass, domain, baseObjectId, entryId = "") {
  const registryMatch = Object.entries(hass?.entities || {}).find(
    ([entityId, registryEntry]) => (
      c300xStateExists(hass, entityId)
      && (!entryId || c300xRegistryEntryId(hass, registryEntry) === entryId)
      && c300xRegistryEntityMatches(
        entityId,
        registryEntry,
        domain,
        baseObjectId,
      )
    ),
  );
  if (registryMatch) {
    return registryMatch[0];
  }
  if (entryId) {
    return undefined;
  }

  return Object.keys(hass?.states || {}).find((entityId) => {
    const [entityDomain, objectId] = entityId.split(".");
    return !hass?.entities?.[entityId]
      && entityDomain === domain && c300xObjectSuffix(objectId, baseObjectId) !== null;
  });
}

export function c300xResolveEntity(hass, config, domain, baseObjectId) {
  const configured = config?.entity;
  if (configured) {
    return configured;
  }
  return c300xFirstEntity(hass, domain, baseObjectId, config?.entry_id || "")
    || (config?.entry_id ? "" : c300xEntityId(domain, baseObjectId));
}

export function c300xRelatedEntity(hass, config, domain, baseObjectId, configKey) {
  const configured = config?.[configKey];
  if (configured) {
    return configured;
  }

  const cameraEntityId = c300xResolveEntity(hass, config, "camera", C300X_CAMERA_OBJECT_ID);
  const camera = hass?.entities?.[cameraEntityId];
  if (camera?.platform !== C300X_PLATFORM
    || (config?.entry_id && !c300xEntryId(hass, config, cameraEntityId))) {
    return undefined;
  }
  return Object.keys(hass?.entities || {}).find((entityId) => (
    c300xStateExists(hass, entityId)
    && c300xSameDevice(hass, camera, hass.entities[entityId])
    && c300xRegistryEntityMatches(entityId, hass.entities[entityId], domain, baseObjectId)
  ));
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
  const camera = config.entity || c300xResolveEntity(hass, config, "camera", C300X_CAMERA_OBJECT_ID);
  const cameraRegistry = hass?.entities?.[camera];
  const entryId = c300xEntryId(hass, config, camera);
  // HA's display registry exposes device_id, not config_entry_id or unique_id.
  // Physical actions must never fall back to a different device.
  if (cameraRegistry?.platform !== C300X_PLATFORM
    || (config.entry_id && !entryId)) {
    return "";
  }
  return Object.keys(hass?.entities || {}).find((entityId) => {
    const state = hass?.states?.[entityId];
    const entry = hass.entities[entityId];
    return !!state
      && entityId.startsWith("button.")
      && entry.platform === C300X_PLATFORM
      && c300xSameDevice(hass, cameraRegistry, entry)
      && (entry.translation_key === key || (entryId && entry.unique_id === `${entryId}_${key}`))
      && (key !== "door_unlock" || state.attributes?.lock_id === "default");
  }) || "";
}
