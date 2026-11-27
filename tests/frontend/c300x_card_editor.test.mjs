import assert from "node:assert/strict";
import test from "node:test";

import {
  C300X_CAMERA_KEY,
  c300xDeviceActionEntity,
  c300xEntryId,
  c300xResolveEntity,
} from "../../custom_components/bticino_c300x/frontend/c300x-entity-resolver.js";

function installCustomElementStubs() {
  const definitions = new Map();
  globalThis.HTMLElement = class {};
  globalThis.CustomEvent = class {
    constructor(type, init = {}) {
      this.type = type;
      this.detail = init.detail;
      this.bubbles = init.bubbles;
      this.composed = init.composed;
    }
  };
  globalThis.customElements = {
    define(name, constructor) {
      definitions.set(name, constructor);
    },
    get(name) {
      return definitions.get(name);
    },
  };
  return definitions;
}

let importCounter = 0;

async function importEditorModule() {
  importCounter += 1;
  return import(
    `../../custom_components/bticino_c300x/frontend/c300x-card-editor.js?test=${importCounter}`
  );
}

test("card editor module registers the same custom element tag", async () => {
  const definitions = installCustomElementStubs();

  const module = await importEditorModule();

  assert.equal(module.C300X_CARD_EDITOR_TAG, "c300x-doorbell-call-card-editor");
  assert.equal(
    definitions.get("c300x-doorbell-call-card-editor"),
    module.C300XDoorbellCallCardEditor,
  );
});

test("card editor stub config takes the doorbell camera from the registry", async () => {
  installCustomElementStubs();
  const module = await importEditorModule();
  const config = module.c300xDoorbellCardStubConfig({
    states: { "camera.kitchen": {} },
    entities: {
      "camera.kitchen": { platform: "bticino_c300x", translation_key: "doorbell_camera", device_id: "unit20" },
    },
  });

  assert.deepEqual(config, {
    entity: "camera.kitchen",
    mode: "auto",
    ringback_tone: true,
    ringback_volume: 12,
  });
});

test("card editor stub config never guesses a camera from its entity id", async () => {
  installCustomElementStubs();
  const module = await importEditorModule();
  // Neither a 2.x entity id in the states nor the bare name without any
  // entity names the station's camera.
  for (const states of [{ "camera.bticino_c300x_doorbell_camera": {} }, {}]) {
    assert.equal(module.c300xDoorbellCardStubConfig({ states, entities: {} }).entity, "");
  }
});

function createEditor(module, config = {}, language = "en") {
  const events = [];
  const listeners = new Map();
  const form = { addEventListener: (name, handler) => listeners.set(name, handler) };
  const editor = new module.C300XDoorbellCallCardEditor();
  editor.attachShadow = () => (editor.shadowRoot = { querySelector: () => form });
  editor.dispatchEvent = (event) => events.push(event);
  editor.hass = { language, states: {} };
  editor.setConfig(config);
  return { editor, form, events, change: (value) => listeners.get("value-changed")({ detail: { value } }) };
}

test("media history defaults on and editor preserves an explicit opt-out", async () => {
  installCustomElementStubs();
  const module = await importEditorModule();
  const { editor, form, change } = createEditor(module);
  assert.equal(form.data.show_media_history, true);
  assert.deepEqual(form.schema.find((field) => field.name === "show_media_history").selector, { boolean: {} });
  change({ ...form.data, show_media_history: false });
  assert.equal(editor._config.show_media_history, false);
  change({ ...editor._config, name: "Front door" });
  assert.equal(editor._config.show_media_history, false);
  change({ ...editor._config, show_media_history: true });
  assert.equal(editor._config.show_media_history, undefined);
});

test("editor exposes independent default-on device action switches in every mode", async () => {
  installCustomElementStubs();
  const module = await importEditorModule();
  for (const mode of ["auto", "doorbell_call", "home_call"]) {
    const { editor, form, events, change } = createEditor(module, { mode });
    for (const key of ["show_door_unlock", "show_stair_light"]) {
      assert.equal(form.data[key], true);
      assert.deepEqual(form.schema.find((field) => field.name === key).selector, { boolean: {} });
    }
    for (const [showDoor, showLight] of [[false, true], [true, false], [false, false], [true, true]]) {
      change({ ...form.data, show_door_unlock: showDoor, show_stair_light: showLight });
      const event = events.at(-1);
      assert.equal(event.type, "config-changed");
      assert.equal(event.bubbles, true);
      assert.equal(event.composed, true);
      assert.equal(event.detail.config.show_door_unlock, showDoor ? undefined : false);
      assert.equal(event.detail.config.show_stair_light, showLight ? undefined : false);
      assert.equal(event.detail.config.show_media_readiness, undefined);
      editor.setConfig(event.detail.config);
      assert.equal(form.data.show_door_unlock, showDoor);
      assert.equal(form.data.show_stair_light, showLight);
    }
  }
});

test("editor preserves hidden readiness and device buttons when changing other options", async () => {
  installCustomElementStubs();
  const module = await importEditorModule();
  const { form, events, change } = createEditor(module, {
    show_media_readiness: false, show_door_unlock: false, show_stair_light: false,
  });
  change({ ...form.data, name: "Side door", mode: "doorbell_call" });
  const config = events.at(-1).detail.config;
  assert.equal(config.name, "Side door");
  assert.equal(config.show_media_readiness, false);
  assert.equal(config.show_door_unlock, false);
  assert.equal(config.show_stair_light, false);
});

test("device action visibility labels are translated in every supported language", async () => {
  installCustomElementStubs();
  const module = await importEditorModule();
  for (const language of ["en", "de", "fr", "it", "es"]) {
    const { form } = createEditor(module, {}, language);
    for (const key of ["show_door_unlock", "show_stair_light"]) {
      assert.notEqual(form.computeLabel({ name: key }), key);
    }
  }
});

test("editor does not write its default entity into a card that names its device by entry_id", async () => {
  installCustomElementStubs();
  const module = await importEditorModule();
  const events = [];
  const listeners = new Map();
  const form = { addEventListener: (name, handler) => listeners.set(name, handler) };
  const editor = new module.C300XDoorbellCallCardEditor();
  editor.attachShadow = () => (editor.shadowRoot = { querySelector: () => form });
  editor.dispatchEvent = (event) => events.push(event);
  editor.hass = { language: "en", states: { "camera.bticino_c300x_doorbell_camera_a": {} } };
  editor.setConfig({ type: "custom:c300x-doorbell-call-card", entry_id: "entry-b" });

  // The form sends back everything it shows, including the default entity.
  listeners.get("value-changed")({ detail: { value: { ...form.data, show_door_unlock: false } } });

  const saved = events.at(-1).detail.config;
  assert.equal(saved.entry_id, "entry-b");
  assert.equal("entity" in saved, false);
  assert.equal(saved.show_door_unlock, false);

  // An entity the user picks is written.
  listeners.get("value-changed")({ detail: { value: { ...saved, entity: "camera.other" } } });
  assert.equal(events.at(-1).detail.config.entity, "camera.other");
  assert.equal(events.at(-1).detail.config.entry_id, undefined);
});

function threeCameraHass() {
  const hass = { language: "en", states: {}, entities: {}, devices: {} };
  for (const id of ["a", "b", "c"]) {
    hass.devices[id] = { config_entry_id: `entry-${id}` };
    hass.states[`camera.${id}`] = { attributes: { door_entity_id: `button.${id}_door_unlock` } };
    hass.entities[`camera.${id}`] = {
      platform: "bticino_c300x", translation_key: "doorbell_camera", device_id: id,
    };
    for (const key of ["door_unlock", "stair_light"]) {
      hass.states[`button.${id}_${key}`] = { attributes: {} };
      hass.entities[`button.${id}_${key}`] = {
        platform: "bticino_c300x", translation_key: key === "door_unlock" ? "door" : key, device_id: id,
      };
    }
  }
  return hass;
}

test("entry-only editor displays B and preserves inference on unrelated edits", async () => {
  installCustomElementStubs();
  const module = await importEditorModule();
  const { editor, form, events, change } = createEditor(module, { entry_id: "entry-b" });
  editor.hass = threeCameraHass();
  assert.equal(form.data.entity, "camera.b");
  for (const update of [{ name: "Back door" }, { show_door_unlock: false }, { mode: "doorbell_call" }]) {
    change({ ...form.data, ...update });
    const saved = events.at(-1).detail.config;
    assert.equal(saved.entry_id, "entry-b");
    assert.equal("entity" in saved, false);
    editor.setConfig(saved);
    assert.equal(form.data.entity, "camera.b");
  }
});

test("choosing A or C updates the owner and routes actions only to that camera", async () => {
  installCustomElementStubs();
  const module = await importEditorModule();
  for (const selected of ["a", "c"]) {
    const { editor, form, events, change } = createEditor(module, { entry_id: "entry-b" });
    const hass = threeCameraHass();
    editor.hass = hass;
    change({ ...form.data, entity: `camera.${selected}` });
    const saved = events.at(-1).detail.config;
    assert.equal(saved.entity, `camera.${selected}`);
    assert.equal(saved.entry_id, `entry-${selected}`);
    assert.equal(c300xResolveEntity(hass, saved, "camera", C300X_CAMERA_KEY), saved.entity);
    assert.equal(c300xEntryId(hass, saved, saved.entity), saved.entry_id);
    for (const key of ["door_unlock", "stair_light"]) {
      assert.equal(c300xDeviceActionEntity(hass, saved, key), `button.${selected}_${key}`);
    }
    // Another form edit before HA calls setConfig must not restore entry B.
    change({ ...form.data, name: "Selected camera" });
    assert.equal(events.at(-1).detail.config.entry_id, `entry-${selected}`);
    assert.equal(events.at(-1).detail.config.entity, `camera.${selected}`);
  }
});

test("registry arrival resolves the displayed camera without changing saved config", async () => {
  installCustomElementStubs();
  const module = await importEditorModule();
  const { editor, form, events, change } = createEditor(module, { entry_id: "entry-b" });
  assert.equal(form.data.entity, "");
  assert.equal(events.length, 0);
  editor.hass = threeCameraHass();
  assert.equal(form.data.entity, "camera.b");
  assert.equal(events.length, 0);
  change({ ...form.data, show_stair_light: false });
  assert.equal(events.at(-1).detail.config.entity, undefined);
  assert.equal(events.at(-1).detail.config.entry_id, "entry-b");
});

test("changing an explicitly configured camera also replaces its old entry owner", async () => {
  installCustomElementStubs();
  const module = await importEditorModule();
  const { editor, form, events, change } = createEditor(module, { entity: "camera.b", entry_id: "entry-b" });
  editor.hass = threeCameraHass();
  change({ ...form.data, entity: "camera.c" });
  assert.equal(events.at(-1).detail.config.entry_id, "entry-c");
  change({ ...form.data, entity: "camera.b" });
  assert.equal(events.at(-1).detail.config.entry_id, "entry-b");
});

// A shadow root that, like the browser, builds a new ha-form for every innerHTML.
function createRebuildingEditor(module, config = {}) {
  const forms = [];
  const editor = new module.C300XDoorbellCallCardEditor();
  editor.attachShadow = () => (editor.shadowRoot = {
    set innerHTML(_html) {
      const listeners = new Map();
      forms.push({ listeners, addEventListener: (name, handler) => listeners.set(name, handler) });
    },
    querySelector: () => forms.at(-1),
  });
  editor.dispatchEvent = (event) => {
    // hui-element-editor answers every config-changed with setConfig.
    if (event.type === "config-changed") editor.setConfig(event.detail.config);
  };
  editor.hass = { language: "en", states: {} };
  editor.setConfig(config);
  const change = (value) => forms.at(-1).listeners.get("value-changed")({ detail: { value } });
  return { editor, forms, change };
}

test("editing keeps the one ha-form and changes its schema in place", async () => {
  installCustomElementStubs();
  const module = await importEditorModule();
  const { editor, forms, change } = createRebuildingEditor(module);
  const form = forms[0];
  for (const name of ["F", "Fr", "Fro", "Front"]) {
    change({ ...form.data, name });
  }
  change({ ...form.data, show_door_unlock: false });
  assert.equal(forms.length, 1, "ha-form was built again");
  assert.equal(form.data.name, "Front");
  assert.equal(form.data.show_door_unlock, false);
  assert.ok(form.schema.some((field) => field.name === "ringback_tone"));

  change({ ...form.data, mode: "doorbell_call" });
  assert.equal(forms.length, 1);
  assert.equal(form.schema.some((field) => field.name === "ringback_tone"), false);

  const english = form.schema[0].selector.select.options[0].label;
  editor.hass = { language: "de", states: {} };
  assert.equal(forms.length, 1);
  assert.notEqual(form.schema[0].selector.select.options[0].label, english);
  const hass = { language: "de", states: {} };
  const schema = form.schema;
  editor.hass = hass;
  assert.equal(form.hass, hass);
  assert.equal(form.schema, schema, "an unchanged language rebuilt the schema");
});
