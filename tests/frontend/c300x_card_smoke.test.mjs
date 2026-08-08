import assert from "node:assert/strict";
import test from "node:test";

function installFakeDom() {
  const registry = new Map();
  const globalListeners = new Map();

  class FakeElement {
    constructor(selector = "") {
      this.selector = selector;
      this.attributes = new Map();
      this.classList = {
        toggle: () => {},
      };
      this.disabled = false;
      this.listeners = new Map();
      this.readyState = 0;
      this.srcObject = null;
      this.style = {};
      this.textContent = "";
    }

    addEventListener(type, listener) {
      this.listeners.set(type, listener);
    }

    removeEventListener(type, listener) {
      if (this.listeners.get(type) === listener) {
        this.listeners.delete(type);
      }
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
  globalThis.addEventListener = (type, listener) => {
    const listeners = globalListeners.get(type) || new Set();
    listeners.add(listener);
    globalListeners.set(type, listeners);
  };
  globalThis.removeEventListener = (type, listener) => {
    const listeners = globalListeners.get(type);
    listeners?.delete(listener);
  };
  globalThis.dispatchEvent = (event) => {
    for (const listener of globalListeners.get(event?.type) || []) {
      listener.call(globalThis, event);
    }
    return true;
  };
  globalThis.HTMLMediaElement = { HAVE_CURRENT_DATA: 2 };
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

test("card derives the PCMU browser gain from HA state, zero for speex", async () => {
  const registry = installFakeDom();

  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?card-gain-test");

  const Card = registry.get("c300x-doorbell-call-card");
  const card = new Card();
  card.setConfig({
    type: "custom:c300x-doorbell-call-card",
    entity: "camera.bticino_c300x_doorbell_camera",
  });

  const hass = fakeHass();
  hass.entities["select.bticino_c300x_audio_codec"] = {
    config_entry_id: "entry-1",
    platform: "bticino_c300x",
    translation_key: "audio_codec",
    unique_id: "entry-1_audio_codec",
  };
  hass.states["camera.bticino_c300x_doorbell_camera"].attributes.doorstation_audio_gain_db = 6;
  hass.states["select.bticino_c300x_audio_codec"] = { state: "pcmu", attributes: {} };
  card.hass = hass;

  // PCMU: the agent runs passthrough, so the card applies the configured gain.
  assert.equal(card._cardGainDb(), 6);

  // speex: the agent applies the gain, so the card stays neutral.
  hass.states["select.bticino_c300x_audio_codec"].state = "speex";
  assert.equal(card._cardGainDb(), 0);
});

test("card keeps its gain when the codec select entity blips to unavailable", async () => {
  const registry = installFakeDom();

  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?card-gain-blip-test");

  const Card = registry.get("c300x-doorbell-call-card");
  const card = new Card();
  card.setConfig({
    type: "custom:c300x-doorbell-call-card",
    entity: "camera.bticino_c300x_doorbell_camera",
  });

  const hass = fakeHass();
  hass.entities["select.bticino_c300x_audio_codec"] = {
    config_entry_id: "entry-1",
    platform: "bticino_c300x",
    translation_key: "audio_codec",
    unique_id: "entry-1_audio_codec",
  };
  hass.states["camera.bticino_c300x_doorbell_camera"].attributes.doorstation_audio_gain_db = 6;
  hass.states["select.bticino_c300x_audio_codec"] = { state: "pcmu", attributes: {} };
  card.hass = hass;
  let refreshes = 0;
  card._webrtc = { refreshGain: () => (refreshes += 1) };
  card._lastCardGainDb = 6;

  // The select entity blips to 'unavailable' (integration reload) mid-call.
  hass.states["select.bticino_c300x_audio_codec"].state = "unavailable";
  card._maybeRefreshCardGain();

  // Gain must NOT be disengaged: no refresh, last value unchanged.
  assert.equal(refreshes, 0);
  assert.equal(card._lastCardGainDb, 6);
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

test("doorbell answer transition promotes when the cloud session receives video", async () => {
  const registry = installFakeDom();

  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?answer-transition-track-test");

  const Card = registry.get("c300x-doorbell-call-card");
  const card = new Card();
  card.setConfig({
    type: "custom:c300x-doorbell-call-card",
    entity: "camera.bticino_c300x_doorbell_camera",
  });
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
  card._lifecycle.ringPreviewActive = true;

  const calls = [];
  const previous = {
    close() {
      calls.push("previous.close");
    },
  };
  card._webrtc = previous;

  let onTrack;
  let startArgs;
  let promoted = false;
  const remoteStream = {
    getVideoTracks() {
      return [{ id: "video-1", kind: "video" }];
    },
  };
  const next = {
    remoteStream,
    async start(args) {
      startArgs = args;
      onTrack();
    },
    close() {
      calls.push("next.close");
    },
    retargetMedia(element) {
      calls.push(`next.retarget:${element.selector}`);
    },
  };
  card._createWebrtcClient = (options) => {
    onTrack = options.onTrack;
    return next;
  };

  await card._replaceDoorbellWebrtcStream({
    microphoneStream: { getAudioTracks: () => [] },
    receiveAudio: true,
    onPromoted: () => {
      promoted = true;
      card._lifecycle.ringPreviewActive = false;
      card._lifecycle.doorbellAnswered = true;
    },
  });

  assert.equal(startArgs.mediaElement.selector, ".transition-video");
  assert.equal(card._webrtc, next);
  assert.equal(card._transitionWebrtc, null);
  assert.equal(card.shadowRoot.querySelector("video").srcObject, remoteStream);
  assert.equal(card.shadowRoot.querySelector(".transition-video").srcObject, null);
  assert.equal(promoted, true);
  assert.equal(card._lifecycle.ringPreviewActive, false);
  assert.equal(card._lifecycle.doorbellAnswered, true);
  assert.deepEqual(calls, ["previous.close", "next.retarget:video"]);
});

test("doorbell card claims Android notification answer launches", async () => {
  const registry = installFakeDom();
  const previousLocation = globalThis.location;
  const previousHistory = globalThis.history;
  let replacedUrl = "";
  globalThis.location = {
    href: "https://example.test/lovelace/c300x?c300x_ring_answer=camera.bticino_c300x_doorbell_camera",
    search: "?c300x_ring_answer=camera.bticino_c300x_doorbell_camera",
  };
  globalThis.history = {
    state: { nav: "state" },
    pushState() {},
    replaceState(_state, _title, url) {
      replacedUrl = url;
      globalThis.location.href = `https://example.test${url}`;
      globalThis.location.search = "";
    },
  };

  try {
    await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?android-answer-launch-test");

    const Card = registry.get("c300x-doorbell-call-card");
    const card = new Card();
    card.setConfig({
      type: "custom:c300x-doorbell-call-card",
      entity: "camera.bticino_c300x_doorbell_camera",
    });
    card._webrtc = {
      running: false,
      close() {},
      refreshGain() {},
    };
    const calls = [];
    card._startTalkback = async (options) => {
      calls.push(options || {});
      card._webrtc.running = true;
      return true;
    };
    card.hass = fakeHass({
      cameraEntity: {
        attributes: {
          friendly_name: "Door",
          media_primary_action: "hangup",
          media_state: "ring_active",
        },
        state: "streaming",
      },
    });
    await Promise.resolve();

    assert.equal(card._lifecycle.doorbellAnswered, true);
    assert.deepEqual(calls, [{}]);
    assert.equal(replacedUrl, "/lovelace/c300x");

    card._webrtc.running = false;
    card._updateState();
    await Promise.resolve();
    assert.deepEqual(calls, [{}]);
  } finally {
    if (previousLocation === undefined) {
      delete globalThis.location;
    } else {
      globalThis.location = previousLocation;
    }
    globalThis.history = previousHistory;
  }
});

test("mounted doorbell card handles notification answer URL changes", async () => {
  const registry = installFakeDom();
  const previousLocation = globalThis.location;
  const previousHistory = globalThis.history;
  let replacedUrl = "";
  globalThis.location = {
    href: "https://example.test/lovelace/c300x",
    search: "",
  };
  globalThis.history = {
    state: {},
    pushState() {},
    replaceState(_state, _title, url) {
      replacedUrl = url;
      globalThis.location.href = `https://example.test${url}`;
      globalThis.location.search = "";
    },
  };

  try {
    await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?mounted-answer-launch-test");

    const Card = registry.get("c300x-doorbell-call-card");
    const card = new Card();
    card.setConfig({
      type: "custom:c300x-doorbell-call-card",
      entity: "camera.bticino_c300x_doorbell_camera",
    });
    card.connectedCallback();
    card._webrtc = {
      running: false,
      close() {},
      refreshGain() {},
    };
    const calls = [];
    card._startTalkback = async (options) => {
      calls.push(options || {});
      card._webrtc.running = true;
      return true;
    };
    card.hass = fakeHass({
      cameraEntity: {
        attributes: {
          friendly_name: "Door",
          media_primary_action: "hangup",
          media_state: "ring_active",
        },
        state: "streaming",
      },
    });
    await Promise.resolve();

    assert.deepEqual(calls, []);
    assert.equal(card._lifecycle.doorbellAnswered, false);

    globalThis.location.href = "https://example.test/lovelace/c300x?c300x_ring_answer=camera.bticino_c300x_doorbell_camera";
    globalThis.location.search = "?c300x_ring_answer=camera.bticino_c300x_doorbell_camera";
    globalThis.dispatchEvent(new Event("location-changed"));
    await Promise.resolve();
    await Promise.resolve();

    assert.equal(card._lifecycle.doorbellAnswered, true);
    assert.deepEqual(calls, [{}]);
    assert.equal(replacedUrl, "/lovelace/c300x");
  } finally {
    delete globalThis.__c300xRingAnswerLaunchClaims;
    if (previousLocation === undefined) {
      delete globalThis.location;
    } else {
      globalThis.location = previousLocation;
    }
    globalThis.history = previousHistory;
  }
});

test("home-call card ignores notification answer launches for doorbell cards", async () => {
  const registry = installFakeDom();
  const previousLocation = globalThis.location;
  const previousHistory = globalThis.history;
  let replacedUrl = "";
  delete globalThis.__c300xRingAnswerLaunchClaims;
  globalThis.location = {
    href: "https://example.test/lovelace/c300x?c300x_ring_answer=camera.bticino_c300x_doorbell_camera",
    search: "?c300x_ring_answer=camera.bticino_c300x_doorbell_camera",
  };
  globalThis.history = {
    state: {},
    pushState() {},
    replaceState(_state, _title, url) {
      replacedUrl = url;
      globalThis.location.href = `https://example.test${url}`;
      globalThis.location.search = "";
    },
  };

  try {
    await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?home-call-answer-launch-test");

    const Card = registry.get("c300x-doorbell-call-card");
    const cameraEntity = {
      attributes: {
        friendly_name: "Door",
        media_primary_action: "hangup",
        media_state: "ring_active",
      },
      state: "streaming",
    };
    const homeCard = new Card();
    homeCard.setConfig({
      type: "custom:c300x-doorbell-call-card",
      entity: "camera.bticino_c300x_doorbell_camera",
      mode: "home_call",
    });
    homeCard._webrtc = {
      running: false,
      close() {},
      refreshGain() {},
    };
    const homeCalls = [];
    homeCard._startTalkback = async () => {
      homeCalls.push("home_call");
      return true;
    };
    homeCard.hass = fakeHass({ cameraEntity });
    await Promise.resolve();

    assert.equal(homeCard._ringAnswerLaunchPending, false);
    assert.equal(homeCard._lifecycle.doorbellAnswered, false);
    assert.deepEqual(homeCalls, []);
    assert.equal(replacedUrl, "");

    const doorbellCard = new Card();
    doorbellCard.setConfig({
      type: "custom:c300x-doorbell-call-card",
      entity: "camera.bticino_c300x_doorbell_camera",
    });
    doorbellCard._webrtc = {
      running: false,
      close() {},
      refreshGain() {},
    };
    const doorbellCalls = [];
    doorbellCard._startTalkback = async (options) => {
      doorbellCalls.push(options || {});
      doorbellCard._webrtc.running = true;
      return true;
    };
    doorbellCard.hass = fakeHass({ cameraEntity });
    await Promise.resolve();

    assert.equal(doorbellCard._lifecycle.doorbellAnswered, true);
    assert.deepEqual(doorbellCalls, [{}]);
    assert.equal(replacedUrl, "/lovelace/c300x");
  } finally {
    delete globalThis.__c300xRingAnswerLaunchClaims;
    if (previousLocation === undefined) {
      delete globalThis.location;
    } else {
      globalThis.location = previousLocation;
    }
    globalThis.history = previousHistory;
  }
});

test("doorbell card promotes preview after Android notification answer launches", async () => {
  const registry = installFakeDom();
  const previousLocation = globalThis.location;
  const previousHistory = globalThis.history;
  globalThis.location = {
    href: "https://example.test/lovelace/c300x?c300x_ring_answer=camera.bticino_c300x_doorbell_camera",
    search: "?c300x_ring_answer=camera.bticino_c300x_doorbell_camera",
  };
  globalThis.history = {
    state: {},
    pushState() {},
    replaceState(_state, _title, url) {
      globalThis.location.href = `https://example.test${url}`;
      globalThis.location.search = "";
    },
  };

  try {
    await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?android-answer-preview-promote-test");

    const Card = registry.get("c300x-doorbell-call-card");
    const card = new Card();
    card.setConfig({
      type: "custom:c300x-doorbell-call-card",
      entity: "camera.bticino_c300x_doorbell_camera",
    });
    card._lifecycle.ringPreviewActive = true;
    card._webrtc = {
      pc: {},
      running: true,
      close() {},
      refreshGain() {},
    };
    const calls = [];
    card._startTalkback = async () => {
      calls.push("talkback");
    };
    card._startAnsweredDoorbellStream = async () => {
      calls.push("answered_stream");
      card._lifecycle.ringPreviewActive = false;
      card._lifecycle.doorbellAnswered = true;
    };
    card.hass = fakeHass({
      cameraEntity: {
        attributes: {
          friendly_name: "Door",
          media_primary_action: "hangup",
          media_state: "ring_active",
        },
        state: "streaming",
      },
    });
    await Promise.resolve();

    assert.equal(card._lifecycle.doorbellAnswered, true);
    assert.deepEqual(calls, ["answered_stream"]);
  } finally {
    if (previousLocation === undefined) {
      delete globalThis.location;
    } else {
      globalThis.location = previousLocation;
    }
    globalThis.history = previousHistory;
  }
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
