export const C300X_CARD_TAG = "c300x-doorbell-call-card";
export const C300X_CARD_TYPE = `custom:${C300X_CARD_TAG}`;
export const C300X_CAMERA_OBJECT_ID = "bticino_c300x_doorbell_camera";
export const C300X_DOCUMENTATION_URL = "https://github.com/memphi2/ha-bticino-c300x#doorbell-video-ring-calls-and-talkback";
export const C300X_DEFAULT_CONFIG = {
  mode: "doorbell_call",
  hangup_script: "",
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

export function c300xFirstEntity(hass, domain, prefix) {
  return Object.keys(hass?.states || {}).find((entityId) => {
    const [entityDomain, objectId] = entityId.split(".");
    return entityDomain === domain && objectId?.startsWith(prefix);
  });
}

export function c300xEntryId(hass, config) {
  if (config.entry_id) {
    return config.entry_id;
  }
  return hass?.entities?.[config.entity]?.config_entry_id || "";
}
