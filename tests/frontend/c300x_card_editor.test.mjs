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
