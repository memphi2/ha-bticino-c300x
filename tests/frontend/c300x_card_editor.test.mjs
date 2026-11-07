import assert from "node:assert/strict";
import test from "node:test";

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

test("card editor stub config resolves configured doorbell cameras", async () => {
  installCustomElementStubs();
  const module = await importEditorModule();
  const config = module.c300xDoorbellCardStubConfig({
    states: {
      "camera.bticino_c300x_doorbell_camera_kitchen": {},
    },
  });

  assert.deepEqual(config, {
    entity: "camera.bticino_c300x_doorbell_camera_kitchen",
    mode: "auto",
    ringback_tone: true,
    ringback_volume: 12,
  });
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
  for (const language of ["en", "de", "fr", "it"]) {
    const { form } = createEditor(module, {}, language);
    for (const key of ["show_door_unlock", "show_stair_light"]) {
      assert.notEqual(form.computeLabel({ name: key }), key);
    }
  }
});
