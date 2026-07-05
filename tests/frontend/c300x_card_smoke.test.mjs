import assert from "node:assert/strict";
import test from "node:test";

function installFakeDom() {
  const registry = new Map();

  class FakeElement {
    constructor(selector = "") {
      this.selector = selector;
      this.attributes = new Map();
      this.classList = {
        toggle: () => {},
      };
      this.disabled = false;
      this.listeners = new Map();
      this.srcObject = null;
      this.style = {};
      this.textContent = "";
    }

    addEventListener(type, listener) {
      this.listeners.set(type, listener);
    }

    dispatch(type) {
      return this.listeners.get(type)?.({ stopPropagation() {} });
    }

    play() {
      return Promise.resolve();
    }

    querySelector(selector) {
      return this.children?.get(selector) || null;
    }

    setAttribute(name, value) {
      this.attributes.set(name, value);
    }
  }

  class FakeShadowRoot extends FakeElement {
    set innerHTML(value) {
      this.html = value;
      this.children = new Map(
        [
          "video",
          ".transition-video",
          "audio",
          ".media",
          ".empty",
          ".body",
          ".row-action",
          ".action-icon",
          ".home-action",
          ".home-action-icon",
          ".mic-action",
          ".mic-icon",
          ".title",
          ".secondary",
          ".readiness",
          ".readiness-icon",
          ".readiness-text",
        ].map((selector) => [selector, new FakeElement(selector)]),
      );
    }

    get innerHTML() {
      return this.html;
    }
  }

  globalThis.HTMLElement = class {
    attachShadow() {
      this.shadowRoot = new FakeShadowRoot();
      return this.shadowRoot;
    }
  };
  globalThis.customElements = {
    define(name, element) {
      registry.set(name, element);
    },
    get(name) {
      return registry.get(name);
    },
  };
  globalThis.document = {
    createElement(name) {
      return new FakeElement(name);
    },
  };
  globalThis.Event = class {
    constructor(type) {
      this.type = type;
    }
  };
  globalThis.history = { pushState() {} };
  globalThis.window = globalThis;
  globalThis.window.customCards = [];
  globalThis.window.clearTimeout = clearTimeout;
  globalThis.window.setTimeout = setTimeout;

  return registry;
}

function fakeHass() {
  return {
    entities: {
      "camera.bticino_c300x_doorbell_camera": {
        config_entry_id: "entry-1",
        platform: "bticino_c300x",
        translation_key: "doorbell_camera",
        unique_id: "entry-1_doorbell_camera",
      },
      "sensor.bticino_c300x_media_readiness": {
        config_entry_id: "entry-1",
        platform: "bticino_c300x",
        translation_key: "media_readiness",
        unique_id: "entry-1_media_readiness",
      },
    },
    states: {
      "camera.bticino_c300x_doorbell_camera": {
        attributes: {
          friendly_name: "Door",
          media_primary_action: "start_stream",
          media_state: "idle",
        },
        state: "idle",
      },
      "sensor.bticino_c300x_media_readiness": {
        attributes: {
          failed_checks: [],
        },
        state: "ready",
      },
    },
    formatEntityName(entity) {
      return entity.attributes.friendly_name;
    },
  };
}

test("doorbell card custom element renders with fake Home Assistant state", async () => {
  const registry = installFakeDom();

  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js");

  const Card = registry.get("c300x-doorbell-call-card");
  assert.equal(typeof Card, "function");
  const card = new Card();

  card.setConfig({
    type: "custom:c300x-doorbell-call-card",
    entity: "camera.bticino_c300x_doorbell_camera",
  });
  card.hass = fakeHass();

  assert.match(card.shadowRoot.innerHTML, /<ha-card>/);
  assert.equal(card.shadowRoot.querySelector(".title").textContent, "Door");
  assert.equal(card.shadowRoot.querySelector(".row-action").disabled, false);
  assert.equal(globalThis.window.customCards.length, 1);
  assert.equal(globalThis.window.customCards[0].type, "c300x-doorbell-call-card");
});
