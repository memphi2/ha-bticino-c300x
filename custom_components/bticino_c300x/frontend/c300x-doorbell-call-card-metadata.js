import "./c300x-doorbell-call-card.js?v=512334210b48e785";
import { c300xDocumentationUrlOfPage } from "./c300x-entity-resolver.js?v=512334210b48e785";

const C300X_CARD_TAG = "c300x-doorbell-call-card";
const C300X_CARD_TYPE = `custom:${C300X_CARD_TAG}`;
const C300X_PLATFORM = "bticino_c300x";
const C300X_CAMERA_TRANSLATION_KEY = "doorbell_camera";

const C300X_METADATA_TRANSLATIONS = {
  en: {
    doorstation_card: "Doorstation card",
  },
  de: {
    doorstation_card: "Türstation-Card",
  },
  fr: {
    doorstation_card: "Carte platine",
  },
  it: {
    doorstation_card: "Scheda postazione porta",
  },
  es: {
    doorstation_card: "Tarjeta del videoportero",
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

// The registry role, never the entity id, marks the doorbell camera.
function c300xMetadataIsDoorbellCamera(hass, entityId) {
  const registryEntry = hass?.entities?.[entityId];
  return entityId.split(".")[0] === "camera"
    && registryEntry?.platform === C300X_PLATFORM
    && registryEntry?.translation_key === C300X_CAMERA_TRANSLATION_KEY;
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
        entity: entityId,
        mode: "auto",
      },
    },
  ];
}

window.customCards = window.customCards || [];
window.customCards = window.customCards.filter((card) => card.type !== C300X_CARD_TAG);
window.customCards.push({
  type: C300X_CARD_TAG,
  name: "BTicino Doorbell Call Card",
  preview: false,
  description: "Doorbell video and Home Call controls of the BTicino door station.",
  get documentationURL() {
    return c300xDocumentationUrlOfPage();
  },
  getEntitySuggestion: c300xMetadataEntitySuggestion,
});
