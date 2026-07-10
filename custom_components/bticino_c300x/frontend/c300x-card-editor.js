import {
  c300xLanguage,
  c300xLocalize,
} from "./c300x-translations.js?v=615e3b720e2a7be6";
import {
  C300X_CAMERA_OBJECT_ID,
  C300X_DEFAULT_CONFIG,
  c300xEntityId,
  c300xFirstEntity,
} from "./c300x-entity-resolver.js?v=615e3b720e2a7be6";

export const C300X_CARD_EDITOR_TAG = "c300x-doorbell-call-card-editor";

export function c300xDoorbellCardStubConfig(hass, entityId) {
  const entity = entityId || c300xFirstEntity(
    hass,
    "camera",
    C300X_CAMERA_OBJECT_ID,
  );
  return {
    entity: entity || c300xEntityId("camera", C300X_CAMERA_OBJECT_ID),
    ...C300X_DEFAULT_CONFIG,
  };
}

function c300xFireConfigChanged(element, config) {
  element.dispatchEvent(new CustomEvent("config-changed", {
    detail: { config },
    bubbles: true,
    composed: true,
  }));
}

export class C300XDoorbellCallCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = {
      ...c300xDoorbellCardStubConfig(this._hass),
      ...config,
    };
    this._render();
  }

  set hass(hass) {
    const languageChanged = c300xLanguage(this._hass) !== c300xLanguage(hass);
    this._hass = hass;
    if (!this.shadowRoot || languageChanged) {
      this._render();
      return;
    }
    const form = this.shadowRoot.querySelector("ha-form");
    if (form) {
      form.hass = hass;
    }
  }

  _render() {
    if (!this._config || !this._hass) {
      return;
    }
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    const doorbellOnlyMode = this._config.mode === "doorbell_call";
    root.innerHTML = `
      <ha-form></ha-form>
    `;

    const form = root.querySelector("ha-form");
    form.hass = this._hass;
    form.data = {
      ...this._config,
      show_media_readiness: this._config.show_media_readiness !== false,
    };
    form.schema = [
      {
        name: "mode",
        required: true,
        selector: {
          select: {
            mode: "dropdown",
            options: [
              { value: "auto", label: this._label("auto_mode") },
              { value: "doorbell_call", label: this._label("doorbell_call") },
              { value: "home_call", label: this._label("home_call") },
            ],
          },
        },
      },
      {
        name: "entity",
        required: false,
        selector: { entity: { domain: "camera" } },
      },
      {
        name: "name",
        selector: { entity_name: {} },
        context: { entity: "entity" },
      },
      {
        name: "show_media_readiness",
        selector: { boolean: {} },
      },
      ...(doorbellOnlyMode ? [] : [
        {
          name: "ringback_tone",
          selector: { boolean: {} },
        },
        {
          name: "ringback_volume",
          selector: {
            number: {
              min: 0,
              max: 100,
              step: 1,
              mode: "slider",
              unit_of_measurement: "%",
            },
          },
        },
      ]),
    ];
    form.computeLabel = (schema) => this._label(
      {
        ringback_tone: "ringback_tone",
        ringback_volume: "ringback_volume",
        show_media_readiness: "show_media_readiness",
      }[schema.name] || schema.name,
    );
    form.addEventListener("value-changed", (event) => {
      this._setConfig(event.detail.value || {});
    });
  }

  _setConfig(config) {
    const nextConfig = { ...config };
    const modeChanged = this._config.mode !== nextConfig.mode;
    for (const [key, value] of Object.entries(nextConfig)) {
      if (value === "") {
        delete nextConfig[key];
      }
    }
    if (nextConfig.show_media_readiness !== false) {
      delete nextConfig.show_media_readiness;
    }
    if (nextConfig.mode === "doorbell_call") {
      delete nextConfig.ringback_tone;
      delete nextConfig.ringback_volume;
    }
    delete nextConfig.home_call_entity;
    delete nextConfig.doorbell_state_entity;
    if (JSON.stringify(this._config) === JSON.stringify(nextConfig)) {
      return;
    }
    this._config = nextConfig;
    c300xFireConfigChanged(this, nextConfig);
    if (modeChanged) {
      this._render();
    }
  }

  _label(key) {
    return c300xLocalize(this._hass, key);
  }
}

if (!customElements.get(C300X_CARD_EDITOR_TAG)) {
  customElements.define(C300X_CARD_EDITOR_TAG, C300XDoorbellCallCardEditor);
}
