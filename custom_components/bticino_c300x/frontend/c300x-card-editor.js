import {
  c300xLanguage,
  c300xLocalize,
} from "./c300x-translations.js?v=0192c2a09a110325";
import {
  C300X_CAMERA_OBJECT_ID,
  C300X_DEFAULT_CONFIG,
  c300xEntityId,
  c300xEntryId,
  c300xFirstEntity,
  c300xResolveEntity,
} from "./c300x-entity-resolver.js?v=0192c2a09a110325";

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
      ...C300X_DEFAULT_CONFIG,
      ...config,
    };
    this._render();
  }

  set hass(hass) {
    const languageChanged = c300xLanguage(this._hass) !== c300xLanguage(hass);
    this._hass = hass;
    const entity = c300xResolveEntity(hass, this._config, "camera", C300X_CAMERA_OBJECT_ID);
    if (!this._form || languageChanged || entity !== this._displayedEntity) {
      this._render();
      return;
    }
    this._form.hass = hass;
  }

  // HA calls setConfig after every config-changed: the form is made once and
  // only gets new data, or the field being edited would lose the focus.
  _ensureForm() {
    if (this._form) {
      return this._form;
    }
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <ha-form></ha-form>
    `;
    const form = root.querySelector("ha-form");
    form.computeLabel = (schema) => this._label(schema.name);
    form.addEventListener("value-changed", (event) => {
      this._setConfig(event.detail.value || {});
    });
    this._form = form;
    return form;
  }

  _render() {
    if (!this._config || !this._hass) {
      return;
    }
    const form = this._ensureForm();
    form.hass = this._hass;
    // An inferred camera is display-only until the user changes the picker.
    this._displayedEntity = c300xResolveEntity(
      this._hass, this._config, "camera", C300X_CAMERA_OBJECT_ID,
    );
    form.data = {
      ...this._config,
      entity: this._displayedEntity,
      show_media_readiness: this._config.show_media_readiness !== false,
      show_door_unlock: this._config.show_door_unlock !== false,
      show_stair_light: this._config.show_stair_light !== false,
      show_media_history: this._config.show_media_history !== false,
      show_picture_controls: this._config.show_picture_controls !== false,
    };
    const schemaKey = `${this._config.mode === "doorbell_call"}:${c300xLanguage(this._hass)}`;
    if (schemaKey !== this._schemaKey) {
      this._schemaKey = schemaKey;
      form.schema = this._schema(this._config.mode === "doorbell_call");
    }
  }

  _schema(doorbellOnlyMode) {
    return [
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
      {
        name: "show_door_unlock",
        selector: { boolean: {} },
      },
      {
        name: "show_stair_light",
        selector: { boolean: {} },
      },
      {
        name: "show_media_history",
        selector: { boolean: {} },
      },
      { name: "show_picture_controls", selector: { boolean: {} } },
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
  }

  _setConfig(config) {
    const nextConfig = { ...config };
    const modeChanged = this._config.mode !== nextConfig.mode;
    const entityChanged = (nextConfig.entity || "") !== this._displayedEntity;
    for (const [key, value] of Object.entries(nextConfig)) {
      if (value === "") {
        delete nextConfig[key];
      }
    }
    for (const key of ["show_media_readiness", "show_door_unlock", "show_stair_light", "show_media_history", "show_picture_controls"]) {
      if (nextConfig[key] !== false) {
        delete nextConfig[key];
      }
    }
    if (nextConfig.mode === "doorbell_call") {
      delete nextConfig.ringback_tone;
      delete nextConfig.ringback_volume;
    }
    delete nextConfig.home_call_entity;
    delete nextConfig.doorbell_state_entity;
    if (!this._config.entity && !entityChanged) {
      delete nextConfig.entity;
    } else if (entityChanged && nextConfig.entity) {
      const entryId = c300xEntryId(this._hass, {}, nextConfig.entity);
      if (entryId) nextConfig.entry_id = entryId;
      else delete nextConfig.entry_id;
    }
    if (JSON.stringify(this._config) === JSON.stringify(nextConfig)) {
      return;
    }
    this._config = nextConfig;
    c300xFireConfigChanged(this, nextConfig);
    if (modeChanged || entityChanged) {
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
