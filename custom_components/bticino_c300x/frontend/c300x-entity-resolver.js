export const C300X_CARD_TAG = "c300x-doorbell-call-card";
export const C300X_CARD_TYPE = `custom:${C300X_CARD_TAG}`;
export const C300X_CAMERA_OBJECT_ID = "bticino_c300x_doorbell_camera";
export const C300X_MEDIA_READINESS_OBJECT_ID = "bticino_c300x_media_readiness";
export const C300X_DOCUMENTATION_URL = "https://github.com/memphi2/ha-bticino-c300x#doorbell-video-ring-calls-and-talkback";
export const C300X_DEFAULT_CONFIG = {
  mode: "auto",
  hangup_script: "",
  ringback_tone: true,
  ringback_volume: 12,
  card_height: 5,
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

export function c300xFirstEntity(hass, domain, prefix) {
  return Object.keys(hass?.states || {}).find((entityId) => {
    const [entityDomain, objectId] = entityId.split(".");
    return entityDomain === domain && objectId?.startsWith(prefix);
  });
}

export function c300xResolveEntity(hass, config, domain, baseObjectId) {
  const configured = config.entity;
  if (configured) {
    if (!hass?.states || hass.states[configured]) {
      return configured;
    }
  }
  return c300xFirstEntity(hass, domain, baseObjectId)
    || c300xEntityId(domain, baseObjectId);
}

export function c300xRelatedEntity(hass, config, domain, baseObjectId, configKey) {
  const configured = config?.[configKey];
  if (configured) {
    if (!hass?.states || hass.states[configured]) {
      return configured;
    }
  }

  const cameraEntityId = c300xResolveEntity(hass, config, "camera", C300X_CAMERA_OBJECT_ID);
  const entryId = c300xEntryId(hass, config, cameraEntityId);
  if (entryId) {
    const match = Object.entries(hass?.entities || {}).find(([entityId, registryEntry]) => {
      const [entityDomain, objectId] = entityId.split(".");
      return entityDomain === domain
        && objectId?.startsWith(baseObjectId)
        && registryEntry?.config_entry_id === entryId;
    });
    if (match) {
      return match[0];
    }
  }

  return c300xFirstEntity(hass, domain, baseObjectId);
}

export function c300xEntryId(hass, config, entityId) {
  if (config.entry_id) {
    return config.entry_id;
  }
  return hass?.entities?.[entityId || config.entity]?.config_entry_id || "";
}
