import "./c300x-doorbell-call-card.js?v=1881449574e33b00";

const C300X_CARD_TAG = "c300x-doorbell-call-card";
const C300X_CARD_TYPE = `custom:${C300X_CARD_TAG}`;
const C300X_PLATFORM = "bticino_c300x";
const C300X_CAMERA_OBJECT_ID = "bticino_c300x_doorbell_camera";
const C300X_CAMERA_TRANSLATION_KEY = "doorbell_camera";
const C300X_DOCUMENTATION_URL = "https://github.com/memphi2/ha-bticino-c300x#doorbell-video-ring-calls-and-talkback";

const C300X_METADATA_TRANSLATIONS = {
  en: {
    card_description: "Doorbell video and Home Call controls for BTicino C300X.",
    doorstation_card: "Doorstation card",
  },
  de: {
    card_description: "Türvideo- und Home-Call-Bedienung für BTicino C300X.",
    doorstation_card: "Türstation-Card",
  },
  fr: {
    card_description: "Contrôles vidéo de sonnette et Home Call pour BTicino C300X.",
    doorstation_card: "Carte platine",
  },
  it: {
    card_description: "Controlli video campanello e Home Call per BTicino C300X.",
    doorstation_card: "Scheda postazione porta",
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
    mode: "auto",
  };
}

function c300xMetadataIsDoorbellCamera(hass, entityId) {
  const [domain, objectId] = entityId.split(".");
  if (domain !== "camera") {
    return false;
  }
  const registryEntry = hass?.entities?.[entityId];
  const uniqueId = String(registryEntry?.unique_id || "");
  return (
    c300xMetadataObjectSuffix(objectId, C300X_CAMERA_OBJECT_ID) !== null
    || (
      registryEntry?.platform === C300X_PLATFORM
      && (
        registryEntry?.translation_key === C300X_CAMERA_TRANSLATION_KEY
        || uniqueId.endsWith(`_${C300X_CAMERA_TRANSLATION_KEY}`)
      )
    )
  );
}

function c300xMetadataEntitySuggestion(hass, entityId) {
  if (!entityId || !c300xMetadataIsDoorbellCamera(hass, entityId)) {
    return null;
  }

  return [
    {
      label: c300xMetadataLocalize(hass, "doorstation_card"),
      config: {
        type: C300X_CARD_TYPE,
        ...c300xMetadataStubConfig(entityId),
      },
    },
  ];
}

window.customCards = window.customCards || [];
window.customCards = window.customCards.filter((card) => card.type !== C300X_CARD_TAG);
window.customCards.push({
  type: C300X_CARD_TAG,
  name: "C300X Doorbell Call Card",
  preview: false,
  description: C300X_METADATA_TRANSLATIONS.en.card_description,
  documentationURL: C300X_DOCUMENTATION_URL,
  getEntitySuggestion: c300xMetadataEntitySuggestion,
});
