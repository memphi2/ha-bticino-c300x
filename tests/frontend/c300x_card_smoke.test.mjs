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
  delete globalThis.requestAnimationFrame;
  delete globalThis.cancelAnimationFrame;

  return registry;
}

function fakeHass({ cameraEntity, connection } = {}) {
  return {
    connection,
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
      "camera.bticino_c300x_doorbell_camera": cameraEntity || {
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

test("doorbell card updates from direct camera state events without page reload", async () => {
  const registry = installFakeDom();
  const subscriptions = [];
  const connection = {
    subscribeEvents(callback, eventType) {
      subscriptions.push({ callback, eventType, active: true });
      return () => {
        subscriptions.at(-1).active = false;
      };
    },
  };
  const busyCamera = {
    attributes: {
      friendly_name: "Door",
      media_primary_action: "wait",
      media_state: "ring_active",
    },
    state: "streaming",
  };
  const idleCamera = {
    attributes: {
      friendly_name: "Door",
      media_primary_action: "start_stream",
      media_state: "idle",
    },
    state: "idle",
  };

  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?state-event-test");

  const Card = registry.get("c300x-doorbell-call-card");
  const card = new Card();
  card.setConfig({
    type: "custom:c300x-doorbell-call-card",
    entity: "camera.bticino_c300x_doorbell_camera",
  });
  card.hass = fakeHass({ cameraEntity: busyCamera, connection });

  await Promise.resolve();
  assert.equal(subscriptions.length, 1);
  assert.equal(subscriptions[0].eventType, "state_changed");
  assert.equal(card.shadowRoot.querySelector(".row-action").disabled, true);

  subscriptions[0].callback({
    data: {
      entity_id: "camera.bticino_c300x_doorbell_camera",
      new_state: idleCamera,
    },
  });

  assert.equal(card._cameraEntity().attributes.media_state, "idle");
  assert.equal(card.shadowRoot.querySelector(".row-action").disabled, false);
  card.disconnectedCallback();
  assert.equal(subscriptions[0].active, false);
});

test("doorbell card coalesces unchanged hass updates into one animation frame", async () => {
  const registry = installFakeDom();
  const frames = [];
  globalThis.requestAnimationFrame = (callback) => {
    frames.push(callback);
    return frames.length;
  };
  globalThis.cancelAnimationFrame = () => {};

  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?render-signature-test");

  const Card = registry.get("c300x-doorbell-call-card");
  const card = new Card();
  card.setConfig({
    type: "custom:c300x-doorbell-call-card",
    entity: "camera.bticino_c300x_doorbell_camera",
  });

  let renderCalls = 0;
  const updateState = card._updateState.bind(card);
  card._updateState = () => {
    renderCalls += 1;
    updateState();
  };

  card.hass = fakeHass();
  card.hass = fakeHass();

  assert.equal(frames.length, 1);
  assert.equal(renderCalls, 0);
  frames.shift()();
  assert.equal(renderCalls, 1);

  card.hass = fakeHass();
  assert.equal(frames.length, 1);
  frames.shift()();
  assert.equal(renderCalls, 1);

  card.hass = fakeHass({
    cameraEntity: {
      attributes: {
        friendly_name: "Door",
        media_primary_action: "wait",
        media_state: "ring_active",
      },
      state: "streaming",
    },
  });
  frames.shift()();

  assert.equal(renderCalls, 2);
});
