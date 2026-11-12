import assert from "node:assert/strict";
import test from "node:test";

function installFakeDom() {
  const registry = new Map();
  const globalListeners = new Map();

  class FakeElement {
    constructor(selector = "") {
      this.selector = selector;
      this.attributes = new Map();
      const classes = new Set();
      this.classList = {
        toggle(name, force) {
          const enabled = force ?? !classes.has(name);
          if (enabled) classes.add(name);
          else classes.delete(name);
          return enabled;
        },
        contains: (name) => classes.has(name),
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

    removeAttribute(name) {
      this.attributes.delete(name);
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
          ".door-action",
          ".light-action",
          ".device-actions",
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
    devices: { "device-1": { config_entry_id: "entry-1" } },
    entities: {
      "camera.bticino_c300x_doorbell_camera": {
        device_id: "device-1",
        platform: "bticino_c300x",
        translation_key: "doorbell_camera",
      },
      "sensor.bticino_c300x_media_readiness": {
        device_id: "device-1",
        platform: "bticino_c300x",
        translation_key: "media_readiness",
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

test("readiness warnings do not open Repairs while blockers do", async () => {
  const registry = installFakeDom();
  const paths = [];
  globalThis.history = {
    pushState(_state, _title, path) {
      paths.push(path);
    },
  };

  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?readiness-action-test");

  const Card = registry.get("c300x-doorbell-call-card");
  const card = new Card();
  card.setConfig({
    type: "custom:c300x-doorbell-call-card",
    entity: "camera.bticino_c300x_doorbell_camera",
  });
  const hass = fakeHass();
  const readiness = hass.states["sensor.bticino_c300x_media_readiness"];
  readiness.state = "warning";
  readiness.attributes = {
    failed_checks: [],
    forwarding_homeassistant: false,
    warnings: ["forwarding_homeassistant"],
  };
  card.hass = hass;

  const readinessElement = card.shadowRoot.querySelector(".readiness");
  assert.equal(
    card.shadowRoot.querySelector(".readiness-text").textContent,
    "Ring Call requires Home Assistant forwarding",
  );
  assert.equal(readinessElement.attributes.has("role"), false);
  readinessElement.dispatch("click");
  assert.deepEqual(paths, []);

  readiness.state = "blocked";
  readiness.attributes.failed_checks = ["firewall"];
  card.hass = hass;
  assert.equal(card.shadowRoot.querySelector(".readiness-text").textContent, "Media blocked");
  assert.equal(readinessElement.attributes.get("role"), "button");
  readinessElement.dispatch("click");
  assert.deepEqual(paths, ["/config/repairs"]);
});

test("footer device buttons follow HA state, localize and dispatch existing actions", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?device-actions-test");
  const Card = registry.get("c300x-doorbell-call-card");
  const card = new Card();
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
  const hass = fakeHass();
  const calls = [];
  hass.language = "de";
  hass.entities["camera.bticino_c300x_doorbell_camera"] = {
    device_id: "device-1", platform: "bticino_c300x", translation_key: "doorbell_camera",
  };
  hass.callService = async (...args) => calls.push(args);
  for (const key of ["door_unlock", "stair_light"]) {
    hass.entities[`button.${key}`] = {
      device_id: "device-1", platform: "bticino_c300x", translation_key: key,
    };
    hass.states[`button.${key}`] = { state: "unknown", attributes: { lock_id: "default" } };
  }
  card.hass = hass;
  const door = card.shadowRoot.querySelector(".door-action");
  const light = card.shadowRoot.querySelector(".light-action");
  assert.equal(door.title, "Tür öffnen");
  assert.equal(light.attributes.get("aria-label"), "Treppenlicht");
  assert.equal(door.disabled, false);
  assert.equal(light.disabled, false);
  assert.equal(door.classList.contains("hidden"), false);
  assert.equal(light.classList.contains("hidden"), false);
  await door.dispatch("click");
  await light.dispatch("click");
  assert.deepEqual(calls, [
    ["button", "press", { entity_id: "button.door_unlock" }],
    ["button", "press", { entity_id: "button.stair_light" }],
  ]);
  for (const [showDoor, showLight] of [[false, true], [true, false], [false, false], [true, true]]) {
    const previousSignature = card._renderSignature();
    card.setConfig({ ...card._config, show_door_unlock: showDoor, show_stair_light: showLight });
    assert.notEqual(card._renderSignature(), previousSignature);
    assert.equal(door.classList.contains("hidden"), !showDoor);
    assert.equal(light.classList.contains("hidden"), !showLight);
    assert.equal(door.disabled, !showDoor);
    assert.equal(light.disabled, !showLight);
    assert.equal(card.shadowRoot.querySelector(".device-actions").classList.contains("hidden"), !showDoor && !showLight);
  }
  hass.states["button.door_unlock"].state = "unavailable";
  card.hass = hass;
  assert.equal(door.disabled, true);
  delete hass.states["button.stair_light"];
  card.hass = hass;
  assert.equal(light.disabled, true);
});

test("call services use the camera device owner and reject missing or ambiguous assignments", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?service-device-owner-test");
  const card = new (registry.get("c300x-doorbell-call-card"))();
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
  const hass = fakeHass();
  const calls = [];
  hass.callService = async (...args) => calls.push(args);
  card.hass = hass;
  await card._actions.answerDoorbellCall();
  assert.deepEqual(calls, [["bticino_c300x", "answer_doorbell_call", { entry_id: "entry-1" }]]);
  hass.devices = { "device-1": { config_entries: ["entry-1"] } };
  assert.deepEqual(card._serviceData(), { entry_id: "entry-1" });
  for (const device of [undefined, { config_entries: ["entry-1", "entry-2"] }]) {
    hass.devices = { "device-1": device };
    await assert.rejects(card._actions.answerDoorbellCall(), /Camera device assignment unavailable/);
    await assert.rejects(card._actions.stopDoorbellVideo(), /Camera device assignment unavailable/);
    await assert.rejects(card._actions.stopHomeCall(), /Camera device assignment unavailable/);
    assert.equal(calls.length, 1);
  }
  hass.devices = { "device-1": { config_entry_id: "entry-1" } };
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera", entry_id: "entry-2" });
  await assert.rejects(card._actions.answerDoorbellCall(), /Camera device assignment unavailable/);
  assert.equal(calls.length, 1);
});

test("registry changes invalidate cached codec and a removed camera does not retain old state", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?registry-cache-test");
  const card = new (registry.get("c300x-doorbell-call-card"))();
  const cameraId = "camera.bticino_c300x_doorbell_camera";
  card.setConfig({ entity: cameraId });
  const hass = fakeHass();
  for (const [id, mode] of [["1", "pcmu"], ["2", "speex"]]) {
    hass.entities[`select.codec_${id}`] = {
      device_id: `device-${id}`, platform: "bticino_c300x", translation_key: "audio_codec",
    };
    hass.states[`select.codec_${id}`] = { state: mode, attributes: {} };
  }
  card.hass = hass;
  assert.equal(card._audioCodecMode(), "pcmu");
  hass.entities = {
    ...hass.entities,
    [cameraId]: { ...hass.entities[cameraId], device_id: "device-2" },
  };
  card.hass = hass;
  assert.equal(card._audioCodecMode(), "speex");
  assert.ok(hass.states["select.codec_1"]);
  delete hass.states[cameraId];
  hass.entities = { ...hass.entities };
  delete hass.entities[cameraId];
  hass.states["camera.other"] = { attributes: { media_state: "ring_active" }, state: "idle" };
  hass.entities["camera.other"] = { device_id: "device-2", platform: "bticino_c300x", translation_key: "doorbell_camera" };
  card.hass = hass;
  assert.equal(card._resolvedCameraEntityId(), cameraId);
  assert.equal(card._cameraEntity(), undefined);
  assert.equal(card._audioCodecMode(), null);
  assert.throws(() => card._serviceData(), /Camera device assignment unavailable/);
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
    device_id: "device-1",
    platform: "bticino_c300x",
    translation_key: "audio_codec",
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
    device_id: "device-1",
    platform: "bticino_c300x",
    translation_key: "audio_codec",
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

test("reconfiguration disposes media, timers and subscriptions before replacing resources", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?reconfigure-cleanup");
  const Card = registry.get("c300x-doorbell-call-card");
  const card = new Card();
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
  card.hass = fakeHass();
  const cleaned = [];
  card._webrtc.close = () => cleaned.push("peer");
  card._transitionWebrtc = { close: () => cleaned.push("transition") };
  card._micStream = { getTracks: () => [{ stop: () => cleaned.push("mic") }] };
  card._unsubscribeStateEvents = () => cleaned.push("subscription");
  card._ringbackTone.stop = () => cleaned.push("tone");
  card._showTemporaryNotice("old notice");
  const timer = card._noticeTimer;
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera", name: "Updated" });
  assert.deepEqual(new Set(cleaned), new Set(["peer", "transition", "mic", "subscription", "tone"]));
  assert.equal(timer._destroyed, true);
  assert.equal(card._micStream, null);
  card.disconnectedCallback();
  card.disconnectedCallback();
});

test("reconfiguration rejects an old subscription resolving after the new one", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?late-subscription");
  const Card = registry.get("c300x-doorbell-call-card");
  const card = new Card();
  const pending = [];
  const removed = [];
  const hass = fakeHass({ connection: {
    subscribeEvents: () => new Promise((resolve) => pending.push(resolve)),
  } });
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
  card.hass = hass;
  card.setConfig({ ...card._config, name: "Updated" });
  card.hass = hass;
  assert.equal(pending.length, 2);
  pending[1](() => removed.push("new"));
  await Promise.resolve();
  pending[0](() => removed.push("old"));
  await Promise.resolve();
  assert.deepEqual(removed, ["old"]);
  card.disconnectedCallback();
  assert.deepEqual(removed, ["old", "new"]);
});

test("microphone permission resolving after disposal cannot restart media", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?late-microphone");
  const Card = registry.get("c300x-doorbell-call-card");
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  try {
    for (const reconfigure of [false, true]) {
      let release;
      let stops = 0;
      let starts = 0;
      Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
        mediaDevices: { getUserMedia: () => new Promise((resolve) => { release = resolve; }) },
      } });
      const card = new Card();
      card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
      card.hass = fakeHass();
      card._webrtc.start = async () => { starts++; };
      const starting = card._startTalkback();
      if (reconfigure) card.setConfig({ ...card._config, name: "Updated" });
      else card.disconnectedCallback();
      card._webrtc.start = async () => { starts++; };
      release({ getTracks: () => [{ stop: () => { stops++; } }], getAudioTracks: () => [] });
      assert.equal(await starting, false);
      assert.equal(starts, 0);
      assert.equal(stops, 1);
      assert.equal(card._micStream, null);
      card.disconnectedCallback();
    }
  } finally {
    if (descriptor) Object.defineProperty(globalThis, "navigator", descriptor);
    else delete globalThis.navigator;
  }
});

test("a pending ring answer cannot start media on a reconfigured camera", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?late-answer-reconfigure");
  const Card = registry.get("c300x-doorbell-call-card");
  const card = new Card();
  card._ensureDoorbellPreview = async () => {};
  const hass = fakeHass({ cameraEntity: { state: "idle", attributes: {
    media_primary_action: "answer_ring", media_state: "ring_pending",
  } } });
  hass.entities["camera.second"] = { device_id: "device-2", platform: "bticino_c300x" };
  hass.devices["device-2"] = { config_entry_id: "entry-2" };
  hass.states["camera.second"] = { state: "idle", attributes: { media_state: "idle" } };
  let answer;
  const calls = [];
  hass.callService = (domain, service, data) => {
    calls.push([service, data.entry_id]);
    return new Promise((resolve) => { answer = resolve; });
  };
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
  card.hass = hass;
  const answering = card._actions.handlePrimaryAction();
  card.setConfig({ entity: "camera.second" });
  const starts = [];
  card._startTalkback = async () => { starts.push(card._resolvedCameraEntityId()); };
  answer();
  await answering;

  assert.deepEqual(calls, [["answer_doorbell_call", "entry-1"]]);
  assert.deepEqual(starts, []);
  assert.equal(card._lifecycle.doorbellAnswered, false);
  card.disconnectedCallback();
});

test("a pending ring hangup cannot stop or close a reconfigured camera", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?late-hangup-reconfigure");
  const Card = registry.get("c300x-doorbell-call-card");
  const card = new Card();
  const hass = fakeHass();
  hass.entities["camera.second"] = { device_id: "device-2", platform: "bticino_c300x" };
  hass.devices["device-2"] = { config_entry_id: "entry-2" };
  hass.states["camera.second"] = { state: "idle", attributes: { media_state: "idle" } };
  let hangup;
  const calls = [];
  hass.callService = async (domain, service, data) => {
    calls.push([service, data.entry_id]);
    if (service === "hangup_doorbell_call") await new Promise((resolve) => { hangup = resolve; });
  };
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
  card.hass = hass;
  card._lifecycle.doorbellAnswered = true;
  const hangingUp = card._actions.hangupDoorstation();
  card.setConfig({ entity: "camera.second" });
  let closes = 0;
  card._webrtc.close = () => { closes++; };
  hangup();
  await hangingUp;

  assert.deepEqual(calls, [
    ["hangup_doorbell_call", "entry-1"], ["stop_doorbell_video", "entry-1"],
  ]);
  assert.equal(closes, 0);
  card.disconnectedCallback();
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

test("primary hangup remains available while ring answer waits for microphone permission", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?primary-hangup-pending-microphone");
  const Card = registry.get("c300x-doorbell-call-card");
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  const card = new Card();
  let grant;
  let acknowledge;
  let answering;
  try {
    Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
      mediaDevices: { getUserMedia: () => new Promise((resolve) => { grant = resolve; }) },
    } });
    card._ensureDoorbellPreview = async () => {};
    card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
    const cameraEntity = { state: "idle", attributes: {
      media_primary_action: "answer_ring", media_state: "ring_pending",
    } };
    const hass = fakeHass({ cameraEntity });
    const calls = [];
    hass.callService = async (_domain, service) => {
      calls.push(service);
      if (service === "answer_doorbell_call") {
        await new Promise((resolve) => { acknowledge = resolve; });
      }
    };
    card.hass = hass;
    card._webrtc.start = async () => {};

    answering = card._actions.handlePrimaryAction();
    await card._actions.handlePrimaryAction();
    assert.deepEqual(calls, ["answer_doorbell_call"], "answer taps remain coalesced");
    acknowledge();
    await new Promise(setImmediate);
    assert.equal(typeof grant, "function");
    assert.equal(card._lifecycle.answeringDoorbell, true);

    cameraEntity.attributes.media_state = "ring_active";
    cameraEntity.attributes.media_primary_action = "hangup";
    card.hass = hass;
    assert.equal(card._doorstationView().action, "hang_up");
    assert.equal(card._actionButtonEl.disabled, false);
    await card._actionButtonEl.dispatch("click");
    assert.deepEqual(calls, [
      "answer_doorbell_call", "hangup_doorbell_call", "stop_doorbell_video",
    ]);
  } finally {
    card.disconnectedCallback();
    acknowledge?.();
    grant?.({ getTracks: () => [{ stop() {} }], getAudioTracks: () => [] });
    await answering;
    if (descriptor) Object.defineProperty(globalThis, "navigator", descriptor);
    else delete globalThis.navigator;
  }
});
