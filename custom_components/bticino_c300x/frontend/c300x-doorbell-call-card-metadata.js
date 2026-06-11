const C300X_CARD_TAG = "c300x-doorbell-call-card";
const C300X_CARD_TYPE = `custom:${C300X_CARD_TAG}`;
const C300X_CAMERA_OBJECT_ID = "bticino_c300x_doorbell_camera";
const C300X_DOORBELL_STATE_OBJECT_ID = "bticino_c300x_doorbell_state";
const C300X_DOORBELL_STATE_UNIQUE_SUFFIX = "_doorbell_state";
const C300X_DOORBELL_STATE_TRANSLATION_KEY = "doorbell_state";
const C300X_HOME_CALL_OBJECT_ID = "bticino_c300x_home_call_active";
const C300X_HOME_CALL_UNIQUE_SUFFIX = "_home_call_active";
const C300X_HOME_CALL_TRANSLATION_KEY = "home_call_active";
const C300X_DOCUMENTATION_URL = "https://github.com/memphi2/ha-bticino-c300x#doorbell-video-ring-calls-and-talkback";

const C300X_METADATA_TRANSLATIONS = {
  en: {
    card_description: "Doorbell video and Home Call controls for BTicino C300X.",
    doorbell_call: "Doorbell / On-demand",
    home_call: "Home Call",
  },
  de: {
    card_description: "Türvideo- und Home-Call-Bedienung für BTicino C300X.",
    doorbell_call: "Türklingel / On-Demand",
    home_call: "Home Call",
  },
  fr: {
    card_description: "Contrôles vidéo de sonnette et Home Call pour BTicino C300X.",
    doorbell_call: "Sonnette / à la demande",
    home_call: "Home Call",
  },
  it: {
    card_description: "Controlli video campanello e Home Call per BTicino C300X.",
    doorbell_call: "Campanello / on-demand",
    home_call: "Home Call",
  },
};

function c300xMetadataLanguage(hass) {
  const language = (hass?.language || hass?.locale?.language || "en").toLowerCase();
  return language.split("-")[0];
}

function c300xMetadataLocalize(hass, key) {
  const language = c300xMetadataLanguage(hass);
  return (
    C300X_METADATA_TRANSLATIONS[language] ||
    C300X_METADATA_TRANSLATIONS.en
  )[key] || C300X_METADATA_TRANSLATIONS.en[key] || key;
}

function c300xMetadataObjectSuffix(objectId, baseObjectId) {
  if (objectId === baseObjectId) {
    return "";
  }
  if (objectId?.startsWith(`${baseObjectId}_`)) {
    return objectId.slice(baseObjectId.length);
  }
  return null;
}

function c300xMetadataEntityId(domain, baseObjectId, suffix) {
  return `${domain}.${baseObjectId}${suffix || ""}`;
}

function c300xMetadataStubConfig(entity) {
  return {
    entity: entity || c300xMetadataEntityId("camera", C300X_CAMERA_OBJECT_ID),
    mode: "doorbell_call",
    hangup_script: "",
  };
}

function c300xMetadataRegistryEntity(hass, entityId, uniqueSuffix, translationKey) {
  const entity = hass?.entities?.[entityId] || {};
  const uniqueId = entity.unique_id || entity.uniqueId || "";
  return entity.translation_key === translationKey
    || entity.translationKey === translationKey
    || (uniqueSuffix && uniqueId.endsWith(uniqueSuffix));
}

function c300xMetadataRelatedCamera(hass, entityId, suffix) {
  if (suffix !== null) {
    return c300xMetadataEntityId("camera", C300X_CAMERA_OBJECT_ID, suffix);
  }
  const entryId = hass?.entities?.[entityId]?.config_entry_id;
  const entities = hass?.entities || {};
  if (entryId) {
    for (const candidateId of Object.keys(entities)) {
      const [domain, objectId] = candidateId.split(".");
      if (
        entities[candidateId]?.config_entry_id === entryId
        && domain === "camera"
        && objectId?.startsWith(C300X_CAMERA_OBJECT_ID)
      ) {
        return candidateId;
      }
    }
  }
  return c300xMetadataEntityId("camera", C300X_CAMERA_OBJECT_ID);
}

function c300xMetadataEntitySuggestion(hass, entityId) {
  const [domain, objectId] = entityId.split(".");
  if (!domain || !objectId) {
    return null;
  }

  if (domain === "camera") {
    const suffix = c300xMetadataObjectSuffix(objectId, C300X_CAMERA_OBJECT_ID);
    if (suffix === null) {
      return null;
    }
    return [
      {
        label: c300xMetadataLocalize(hass, "doorbell_call"),
        config: {
          type: C300X_CARD_TYPE,
          ...c300xMetadataStubConfig(entityId),
        },
      },
      {
        label: c300xMetadataLocalize(hass, "home_call"),
        config: {
          type: C300X_CARD_TYPE,
          ...c300xMetadataStubConfig(entityId),
          mode: "home_call",
        },
      },
    ];
  }

  if (domain === "sensor") {
    const suffix = c300xMetadataObjectSuffix(objectId, C300X_DOORBELL_STATE_OBJECT_ID);
    if (
      suffix === null
      && !c300xMetadataRegistryEntity(
        hass,
        entityId,
        C300X_DOORBELL_STATE_UNIQUE_SUFFIX,
        C300X_DOORBELL_STATE_TRANSLATION_KEY,
      )
    ) {
      return null;
    }
    return {
      config: {
        type: C300X_CARD_TYPE,
        ...c300xMetadataStubConfig(
          c300xMetadataRelatedCamera(hass, entityId, suffix),
        ),
        doorbell_state_entity: entityId,
      },
    };
  }

  if (domain === "binary_sensor") {
    const suffix = c300xMetadataObjectSuffix(objectId, C300X_HOME_CALL_OBJECT_ID);
    if (
      suffix === null
      && !c300xMetadataRegistryEntity(
        hass,
        entityId,
        C300X_HOME_CALL_UNIQUE_SUFFIX,
        C300X_HOME_CALL_TRANSLATION_KEY,
      )
    ) {
      return null;
    }
    return {
      label: c300xMetadataLocalize(hass, "home_call"),
      config: {
        type: C300X_CARD_TYPE,
        ...c300xMetadataStubConfig(
          c300xMetadataRelatedCamera(hass, entityId, suffix),
        ),
        mode: "home_call",
        home_call_entity: entityId,
      },
    };
  }

  return null;
}

window.customCards = window.customCards || [];
window.customCards = window.customCards.filter((card) => card.type !== C300X_CARD_TAG);
window.customCards.push({
  type: C300X_CARD_TAG,
  name: "C300X Doorbell Call Card",
  preview: true,
  description: C300X_METADATA_TRANSLATIONS.en.card_description,
  documentationURL: C300X_DOCUMENTATION_URL,
  getEntitySuggestion: c300xMetadataEntitySuggestion,
});
