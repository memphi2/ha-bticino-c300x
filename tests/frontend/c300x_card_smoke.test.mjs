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
          ".snapshot-preview",
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

test("snapshot preview has an accessible timestamp without an overlay and hides during live video", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?snapshot-wiring");
  const card = new (registry.get("c300x-doorbell-call-card"))();
  const hass = fakeHass();
  const attrs = hass.states["camera.bticino_c300x_doorbell_camera"].attributes;
  attrs.stream_snapshots = true;
  hass.language = "en";
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
  try {
    card.hass = hass;
    assert.equal(card._snapshotEl.hidden, true);
    const updates = [];
    card._snapshots.update = (args) => updates.push(args);
    const capturedAt = 1800000000;
    card._snapshots.showPreview("blob:archive", capturedAt);
    assert.equal(card._snapshotEl.hidden, false);
    assert.equal(card._snapshotLabelEl, undefined);
    assert.ok(card._snapshotEl.attributes.get("aria-label").endsWith(new Date(capturedAt * 1000).toLocaleString("en")));
    assert.match(card._snapshotEl.attributes.get("aria-label"), /Archived image \(not live\)/);
    assert.equal(updates.at(-1).entryId, "entry-1");
    assert.equal(updates.at(-1).attributes, attrs);
    card._webrtc = { remoteStream: {}, running: true, close() {} };
    card._updateState();
    assert.equal("active" in updates.at(-1), false);
    assert.equal(card._snapshotEl.hidden, true);
    card._lifecycle.activeHomeCallSession = true;
    card._updateState();
    card._webrtc.remoteStream = null;
    attrs.stream_snapshots = false;
    card._updateState();
    assert.equal(card._snapshotEl.hidden, true);
  } finally {
    card.disconnectedCallback();
  }
});

test("reattaching an idle card reloads its cancelled archive without starting video", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?snapshot-reattach");
  const card = new (registry.get("c300x-doorbell-call-card"))();
  const hass = fakeHass();
  const requests = [];
  const resolvers = [];
  hass.fetchWithAuth = (url, options) => {
    requests.push({ url, ...options });
    return new Promise((resolve) => resolvers.push(resolve));
  };
  Object.assign(hass.states["camera.bticino_c300x_doorbell_camera"].attributes, {
    stream_snapshots: true, snapshot_latest: "image", snapshot_captured_at: Date.now() / 1000,
  });
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
  try {
    card.hass = hass;
    assert.equal(requests.length, 1);
    assert.equal(card._webrtc.running, false);
    card.disconnectedCallback();
    assert.equal(requests[0].signal.aborted, true);
    card.connectedCallback();
    assert.equal(requests.length, 2);
    hass.devices = { "device-1": { config_entry_id: "entry-2" } };
    card.hass = hass;
    assert.equal(requests.length, 3);
    assert.match(requests[2].url, /\/entry-2\/image$/);
    assert.equal(requests[1].signal.aborted, true);
    assert.equal(card._webrtc.running, false);
  } finally {
    card.disconnectedCallback();
    for (const resolve of resolvers) resolve({ ok: false });
    await new Promise(setImmediate);
  }
});

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
  // A narrow card cuts the readiness text; the tooltip carries it in full.
  assert.equal(readinessElement.title, "Ring Call requires Home Assistant forwarding");
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

test("card disposal closes ringback contexts and reattachment recreates them", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?ringback-disposal");
  const card = new (registry.get("c300x-doorbell-call-card"))();
  const previousAudioContext = window.AudioContext;
  const contexts = [];
  window.AudioContext = class {
    constructor() {
      this.state = "running";
      this.destination = {};
      this.closes = 0;
      contexts.push(this);
    }
    createGain() {
      return { gain: { value: 0 }, connect() {}, disconnect() {} };
    }
    createOscillator() {
      return { frequency: { value: 0 }, connect() {}, disconnect() {}, start() {}, stop() {} };
    }
    close() {
      this.closes++;
      this.state = "closed";
      return Promise.resolve();
    }
  };
  try {
    card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
    card._syncRingbackTone(true);
    card._syncRingbackTone(false);
    assert.equal(contexts[0].closes, 0, "ordinary stop keeps the context reusable");
    card._syncRingbackTone(true);
    assert.equal(contexts.length, 1);
    card.disconnectedCallback();
    card.disconnectedCallback();
    assert.equal(contexts[0].closes, 1);
    assert.equal(card._ringbackTone._context, null);
    assert.equal(card._ringbackTone._timer, null);
    assert.deepEqual(card._ringbackTone._oscillators, []);

    card.connectedCallback();
    card._syncRingbackTone(true);
    assert.equal(contexts.length, 2);
    card.setConfig({ entity: "camera.replacement" });
    assert.equal(contexts[1].closes, 1);
    card._syncRingbackTone(true);
    assert.equal(contexts.length, 3);
    card.disconnectedCallback();
    assert.deepEqual(contexts.map((context) => context.closes), [1, 1, 1]);
  } finally {
    card.disconnectedCallback();
    if (previousAudioContext === undefined) delete window.AudioContext;
    else window.AudioContext = previousAudioContext;
  }
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

test("failed automatic preview waits for a new ring lifecycle", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?failed-preview");
  const Card = registry.get("c300x-doorbell-call-card");
  const card = new Card();
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
  let starts = 0;
  card._webrtc.start = async () => { starts++; throw new Error("provider unavailable"); };
  const ringing = fakeHass({cameraEntity: {state: "idle", attributes: {
    media_state: "ring_pending", media_primary_action: "answer_ring",
  }}});
  try {
    card.hass = ringing;
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(starts, 1);
    for (let i = 0; i < 5; i++) card._updateState();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(starts, 1);
    assert.equal(card._error, "provider unavailable");
    card.hass = fakeHass();
    card.hass = ringing;
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(starts, 2);
  } finally {
    card.disconnectedCallback();
  }
});

test("failed passive answered preview waits for a new ring lifecycle", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?failed-passive-preview");
  const card = new (registry.get("c300x-doorbell-call-card"))();
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
  card.hass = fakeHass();
  let starts = 0;
  card._createWebrtcClient = () => ({
    close() {},
    async start() {
      starts++;
      // Bound the reproduction even if the immediate retry loop regresses.
      if (starts >= 6) await new Promise(() => {});
      throw new Error("provider unavailable");
    },
  });
  const answered = fakeHass({ cameraEntity: { state: "idle", attributes: {
    media_state: "ring_active", media_primary_action: "wait",
  } } });
  const markPreview = () => {
    card._lifecycle.ringPreviewStarted = true;
    card._lifecycle.ringPreviewActive = true;
  };
  try {
    markPreview();
    card.hass = answered;
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(starts, 1);
    for (let i = 0; i < 5; i++) card._updateState();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(starts, 1);
    assert.equal(card._error, "provider unavailable");
    card.hass = fakeHass();
    markPreview();
    card.hass = answered;
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(starts, 2);
  } finally {
    card.disconnectedCallback();
  }
});

test("stale passive preview failure cannot suppress a replacement card session", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?stale-passive-preview");
  const card = new (registry.get("c300x-doorbell-call-card"))();
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
  let rejectStart;
  card._replaceDoorbellWebrtcStream = () => new Promise((_, reject) => { rejectStart = reject; });
  const pending = card._startPassiveAnsweredDoorbellPreview();
  card.setConfig({ entity: "camera.replacement" });
  try {
    rejectStart(new Error("old provider failed"));
    await pending;
    assert.equal(card._lifecycle.ringPreviewSuppressed, false);
    assert.equal(card._lifecycle.passiveAnsweredPreviewStarted, false);
    assert.equal(card._error, "");
  } finally {
    card.disconnectedCallback();
  }
});

for (const preview of [false, true]) {
  for (const cancellation of ["reconfigure", "dispose", "hangup"]) {
    for (const outcome of ["resolve", "reject"]) {
      test(`stale notification answer ${preview ? "preview" : "talkback"} ${outcome} after ${cancellation} leaves replacement untouched`, async () => {
        const registry = installFakeDom();
        await import(`../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?notification-stale-${preview}-${cancellation}-${outcome}`);
        const card = new (registry.get("c300x-doorbell-call-card"))();
        card.setConfig({ entity: "camera.old" });
        card._updateState = () => {};
        card._lifecycle.ringPreviewActive = preview;
        card._webrtc = { pc: preview ? {} : null, close() {} };
        let settle;
        const start = () => new Promise((resolve, reject) => {
          settle = () => outcome === "resolve" ? resolve(true) : reject(new Error("old provider failed"));
        });
        card._startTalkback = start;
        card._startAnsweredDoorbellStream = start;
        card._ringAnswerLaunchPending = true;
        let consumed = 0;
        card._consumeRingAnswerLaunchRequest = () => { consumed++; };
        const pending = card._startNotificationAnsweredDoorbellStream();
        if (cancellation === "reconfigure") card.setConfig({ entity: "camera.replacement" });
        else if (cancellation === "dispose") card.disconnectedCallback();
        else card._cancelPendingMediaStart();
        assert.equal(card._ringAnswerLaunchStarting, false, "cancel releases the old start synchronously");
        assert.equal(card._ringAnswerLaunchPending, false);
        assert.equal(consumed, cancellation === "hangup" ? 1 : 0, "disposal must preserve the URL for another card");
        card._lifecycle.doorbellAnswered = true;
        card._ringAnswerLaunchPending = true;
        card._ringAnswerLaunchStarting = true;
        card._ringAnswerLaunchClaimKey = "replacement-claim";
        card._error = "replacement error";
        consumed = 0;
        let renders = 0;
        card._updateState = () => { renders++; };
        try {
          settle();
          await pending;
          assert.equal(card._lifecycle.doorbellAnswered, true);
          assert.equal(card._ringAnswerLaunchPending, true);
          assert.equal(card._ringAnswerLaunchStarting, true);
          assert.equal(card._ringAnswerLaunchClaimKey, "replacement-claim");
          assert.equal(card._error, "replacement error");
          assert.equal(consumed, 0, "old completion must not consume a new URL marker");
          assert.equal(renders, 0, "old finally must not render a replacement or disposed card");
        } finally {
          card.disconnectedCallback();
        }
      });
    }
  }
}

test("notification answer transport failure releases its own start and consumes only its launch", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?notification-own-failure");
  const card = new (registry.get("c300x-doorbell-call-card"))();
  card.setConfig({ entity: "camera.old" });
  card._updateState = () => {};
  card._prepareMicrophone = async () => {};
  let starts = 0;
  card._webrtc = {
    close() {},
    async start() { starts++; throw new Error("provider unavailable"); },
  };
  let consumed = 0;
  card._consumeRingAnswerLaunchRequest = () => { consumed++; };
  card._ringAnswerLaunchPending = true;
  card._ringAnswerLaunchClaimKey = "old-claim";
  try {
    await card._startNotificationAnsweredDoorbellStream();
    assert.equal(card._error, "provider unavailable");
    assert.equal(card._ringAnswerLaunchStarting, false);
    assert.equal(card._ringAnswerLaunchPending, false);
    assert.equal(card._ringAnswerLaunchClaimKey, "");
    assert.equal(card._lifecycle.doorbellAnswered, false);
    assert.equal(consumed, 1);
    assert.equal(starts, 1);
    assert.equal(card._shouldStartNotificationAnsweredDoorbellStream("ring_active"), false);
  } finally {
    card.disconnectedCallback();
  }
});

test("failed old transition does not clear a replacement transition video", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?stale-transition-cleanup");
  const card = new (registry.get("c300x-doorbell-call-card"))();
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
  let rejectStart;
  const oldClient = {
    close() {},
    start: () => new Promise((_, reject) => { rejectStart = reject; }),
  };
  const oldTrack = { stopped: false, stop() { this.stopped = true; } };
  const oldMicrophone = { getTracks: () => [oldTrack] };
  card._micStream = oldMicrophone;
  card._createWebrtcClient = () => oldClient;
  const pending = card._replaceDoorbellWebrtcStream({ microphoneStream: oldMicrophone, onPromoted() {} });
  card.setConfig({ entity: "camera.replacement" });
  const replacementTrack = { stopped: false, stop() { this.stopped = true; } };
  const replacementMicrophone = { getTracks: () => [replacementTrack] };
  card._micStream = replacementMicrophone;
  const replacement = { close() {} };
  const stream = { id: "replacement stream" };
  card._transitionWebrtc = replacement;
  card._transitionVideoEl.srcObject = stream;
  try {
    rejectStart(new Error("old provider failed"));
    await assert.rejects(pending, /old provider failed/);
    assert.equal(card._transitionWebrtc, replacement);
    assert.equal(card._transitionVideoEl.srcObject, stream);
    assert.equal(oldTrack.stopped, true);
    assert.equal(card._micStream, replacementMicrophone);
    assert.equal(replacementTrack.stopped, false);
  } finally {
    card.disconnectedCallback();
  }
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

test("microphone permission resolving after hangup cannot restart media", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?late-microphone-stop");
  const Card = registry.get("c300x-doorbell-call-card");
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  try {
    let release;
    let stops = 0;
    let starts = 0;
    Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
      mediaDevices: { getUserMedia: () => new Promise((resolve) => { release = resolve; }) },
    } });
    const card = new Card();
    card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
    card.hass = { ...fakeHass(), callService: async () => {} };
    card._webrtc.start = async () => { starts++; };
    const starting = card._startTalkback();
    await card._actions.hangupDoorstation();
    release({ getTracks: () => [{ stop: () => { stops++; } }], getAudioTracks: () => [] });
    assert.equal(await starting, false);
    assert.equal(starts, 0);
    assert.equal(stops, 1);
    assert.equal(card._micStream, null);
    card.disconnectedCallback();
  } finally {
    if (descriptor) Object.defineProperty(globalThis, "navigator", descriptor);
    else delete globalThis.navigator;
  }
});

test("parallel microphone starts are coalesced and a cancelled start cannot replace a new stream", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?replace-microphone-start");
  const Card = registry.get("c300x-doorbell-call-card");
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  try {
    const permissions = [];
    Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
      mediaDevices: { getUserMedia: () => new Promise((resolve) => { permissions.push(resolve); }) },
    } });
    const card = new Card();
    card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
    card.hass = fakeHass();
    const starts = [];
    card._webrtc.start = async (options) => { starts.push(options.microphoneStream); };
    const oldStart = card._startTalkback();
    assert.equal(await card._startTalkback(), false);
    assert.equal(permissions.length, 1, "repeated taps must not open another microphone");
    card._closePeer(true);
    const newStart = card._startTalkback();
    let oldStops = 0;
    let newStops = 0;
    const oldStream = { getAudioTracks: () => [], getTracks: () => [{ stop() { oldStops++; } }] };
    const newStream = { getAudioTracks: () => [], getTracks: () => [{ stop() { newStops++; } }] };
    permissions[1](newStream);
    assert.equal(await newStart, true);
    permissions[0](oldStream);
    assert.equal(await oldStart, false);
    assert.deepEqual(starts, [newStream]);
    assert.equal(card._micStream, newStream);
    assert.equal(oldStops, 1);
    assert.equal(newStops, 0);
    card.disconnectedCallback();
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

test("a delayed ring hangup cannot stop a replacement session on the same camera", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?late-hangup-same-camera");
  const Card = registry.get("c300x-doorbell-call-card");
  for (const reconfigure of [false, true]) {
    const card = new Card();
    const hass = fakeHass();
    let hangup;
    const calls = [];
    hass.callService = async (domain, service) => {
      calls.push(service);
      if (service === "hangup_doorbell_call") await new Promise((resolve) => { hangup = resolve; });
    };
    const config = { entity: "camera.bticino_c300x_doorbell_camera" };
    card.setConfig(config);
    card.hass = hass;
    card._lifecycle.doorbellAnswered = true;
    const oldHangup = card._actions.hangupDoorstation();
    if (reconfigure) card.setConfig(config);
    else card._closePeer(true);
    card._webrtc.start = async () => {};
    assert.equal(await card._startTalkback({ microphone: false }), true);
    let closes = 0;
    card._webrtc.close = () => { closes++; };
    hangup();
    await oldHangup;
    assert.deepEqual(calls, ["hangup_doorbell_call"]);
    assert.equal(closes, 0);
    card.disconnectedCallback();
  }
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

test("the ringback tone plays only on the card that started the Home Call", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?ringback-owner");
  const Card = registry.get("c300x-doorbell-call-card");
  const ringing = () => fakeHass({ cameraEntity: {
    attributes: { friendly_name: "Door", media_primary_action: "hangup", media_state: "home_call_ringing" },
    state: "streaming",
  } });
  const tones = (card) => {
    const seen = [];
    card._syncRingbackTone = (active) => seen.push(!!active);
    return seen;
  };

  const other = new Card();
  other.setConfig({ type: "custom:c300x-doorbell-call-card", entity: "camera.bticino_c300x_doorbell_camera" });
  const otherTones = tones(other);
  other.hass = ringing();
  assert.deepEqual([...new Set(otherTones)], [false]);

  const caller = new Card();
  caller.setConfig({ type: "custom:c300x-doorbell-call-card", entity: "camera.bticino_c300x_doorbell_camera" });
  const callerTones = tones(caller);
  caller._lifecycle.activeHomeCallSession = true;
  caller.hass = ringing();
  assert.equal(callerTones.at(-1), true);
  other.disconnectedCallback();
  caller.disconnectedCallback();
});

function answerRaceCard(Card) {
  const card = new Card();
  card.setConfig({ type: "custom:c300x-doorbell-call-card", entity: "camera.bticino_c300x_doorbell_camera" });
  card._lifecycle.ringPreviewActive = true;
  card._lifecycle.ringPreviewStarted = true;
  card._lifecycle.lastMediaState = "ring_preview_active";
  const clients = [];
  card._createWebrtcClient = ({ onTrack } = {}) => {
    const client = {
      pc: null, running: false, remoteStream: null, options: null, onTrack,
      async start(options) {
        this.options = options;
        this.running = true;
        this.pc = {};
        this.remoteStream = { getVideoTracks: () => [{}] };
      },
      close() { this.running = false; this.pc = null; this.remoteStream = null; },
      refreshGain() {},
      retargetMedia() {},
    };
    clients.push(client);
    return client;
  };
  card._webrtc = {
    pc: {}, running: true, remoteStream: { getVideoTracks: () => [{}] },
    close() { this.running = false; this.pc = null; }, refreshGain() {},
  };
  return { card, clients };
}

function ringHass(mediaState, primaryAction, callService) {
  const hass = fakeHass({ cameraEntity: {
    attributes: { friendly_name: "Door", media_primary_action: primaryAction, media_state: mediaState },
    state: "streaming",
  } });
  if (callService) hass.callService = callService;
  return hass;
}

function fakeMicrophones() {
  const streams = [];
  const prompts = [];
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: { mediaDevices: {
    getUserMedia: () => new Promise((resolve) => prompts.push(() => {
      const tracks = [{ kind: "audio", enabled: true, stopped: false, stop() { this.stopped = true; } }];
      const stream = { getTracks: () => tracks, getAudioTracks: () => tracks };
      streams.push(stream);
      resolve(stream);
    })),
  } } });
  return { streams, prompts, restore() {
    if (descriptor) Object.defineProperty(globalThis, "navigator", descriptor);
    else delete globalThis.navigator;
  } };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test("failed answered transitions release their microphone and preserve the preview", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?failed-answer-microphone");
  const Card = registry.get("c300x-doorbell-call-card");
  for (const failure of ["offer rejection", "provider closure"]) {
    const { card } = answerRaceCard(Card);
    const microphones = fakeMicrophones();
    const preview = card._webrtc;
    let onClosed;
    let closes = 0;
    card._createWebrtcClient = (callbacks) => {
      onClosed = callbacks.onClosed;
      return {
        async start() {
          if (failure === "offer rejection") throw new Error(failure);
        },
        close() { closes++; },
      };
    };
    let answering;
    try {
      card.hass = ringHass("ring_preview_active", "answer_ring", async () => {});
      answering = card._actions.handlePrimaryAction();
      await tick();
      microphones.prompts.shift()();
      await answering;
      if (failure === "provider closure") {
        assert.equal(microphones.streams[0].getTracks()[0].stopped, false);
        const transition = card._transitionWebrtc;
        onClosed(failure);
        transition.close();
      }
      assert.equal(microphones.streams[0].getTracks()[0].stopped, true, failure);
      assert.equal(card._micStream, null);
      assert.equal(card._transitionWebrtc, null);
      assert.equal(card._webrtc, preview);
      assert.equal(preview.running, true);
      assert.equal(card._lifecycle.doorbellAnswered, true);
      assert.equal(card._error, failure);
      assert.equal(closes, 1);
    } finally {
      card.disconnectedCallback();
      microphones.prompts.shift()?.();
      await answering;
      microphones.restore();
    }
  }
});

test("the ring_active state arriving before the answer result keeps the answering card answered", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?answer-button-race");
  const microphones = fakeMicrophones();
  try {
    const { card, clients } = answerRaceCard(registry.get("c300x-doorbell-call-card"));
    let answered;
    const callService = (_domain, service) => (service === "answer_doorbell_call"
      ? new Promise((resolve) => { answered = resolve; }) : Promise.resolve());
    card.hass = ringHass("ring_preview_active", "answer_ring", callService);
    const action = card._actions.handlePrimaryAction();
    await tick();
    // Home Assistant pushes the new state before the service call returns.
    card.hass = ringHass("ring_active", "hangup", callService);
    await tick();
    assert.equal(clients.length, 0, "no receive-only preview while this card answers");
    answered();
    await tick();
    microphones.prompts.shift()();
    await tick();
    assert.equal(clients.length, 1);
    assert.equal(clients[0].options.microphoneStream, microphones.streams[0]);
    clients[0].onTrack();
    await action;
    await tick();
    assert.equal(card._lifecycle.doorbellAnswered, true);
    assert.equal(card._doorstationView().action, "hang_up");
    assert.equal(card._actionButtonEl.disabled, false);
    card.disconnectedCallback();
  } finally {
    microphones.restore();
  }
});

test("a notification answer opens one microphone and no receive-only preview beside it", async () => {
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
  const microphones = fakeMicrophones();
  try {
    await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?notification-answer-race");
    const { card, clients } = answerRaceCard(registry.get("c300x-doorbell-call-card"));
    card.hass = ringHass("ring_active", "hangup");
    await tick();
    assert.equal(clients.length, 0, "no receive-only preview while the answer waits for the microphone");
    microphones.prompts.shift()();
    await tick();
    assert.equal(clients.length, 1);
    assert.equal(clients[0].options.microphoneStream, microphones.streams[0]);
    clients[0].onTrack();
    await tick();
    assert.equal(card._lifecycle.doorbellAnswered, true);
    assert.equal(microphones.prompts.length + microphones.streams.length, 1, "one microphone request");
    card.disconnectedCallback();
    assert.deepEqual(microphones.streams.map((stream) => stream.getTracks()[0].stopped), [true]);
  } finally {
    microphones.restore();
    if (previousLocation === undefined) delete globalThis.location;
    else globalThis.location = previousLocation;
    if (previousHistory === undefined) delete globalThis.history;
    else globalThis.history = previousHistory;
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

test("journal gets connection replacements without a rendered state change, but not after disposal", async () => {
  const registry = installFakeDom();
  const frames = [];
  globalThis.requestAnimationFrame = callback => { frames.push(callback); return frames.length; };
  globalThis.cancelAnimationFrame = () => {};
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?journal-connection");
  const card = new (registry.get("c300x-doorbell-call-card"))();
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera", show_visitor_journal: true });
  const configurations = [];
  card.shadowRoot.children.set("c300x-visitor-journal", { configure: value => configurations.push(value), deactivate() {} });
  const hass = fakeHass({ connection: {} });
  card.hass = hass;
  frames.shift()();
  const signature = card._lastRenderSignature;
  let renders = 0;
  const updateState = card._updateState.bind(card);
  card._updateState = () => { renders++; updateState(); };
  const replacement = { ...hass, connection: {} };
  card.hass = replacement;
  assert.equal(configurations.at(-1).hass, replacement);
  assert.equal(configurations.at(-1).entryId, "entry-1");
  assert.equal(configurations.at(-1).enabled, true);
  frames.shift()();
  assert.equal(card._lastRenderSignature, signature);
  assert.equal(renders, 0);
  card.disconnectedCallback();
  const count = configurations.length;
  card.hass = { ...replacement, connection: {} };
  assert.equal(configurations.length, count);
});

test("primary hangup remains available while ring answer waits for microphone permission", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?primary-hangup-pending-microphone");
  const Card = registry.get("c300x-doorbell-call-card");
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  const card = new Card();
  let grant;
  let acknowledge;
  let finishHangup;
  let answering;
  let hangingUp;
  let starts = 0;
  let stops = 0;
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
      if (service === "hangup_doorbell_call") {
        await new Promise((resolve) => { finishHangup = resolve; });
      }
    };
    card.hass = hass;
    card._webrtc.start = async () => { starts++; };

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
    hangingUp = card._actionButtonEl.dispatch("click");
    assert.deepEqual(calls, ["answer_doorbell_call", "hangup_doorbell_call"]);
    grant({ getTracks: () => [{ stop() { stops++; } }], getAudioTracks: () => [] });
    await answering;
    assert.equal(starts, 0);
    assert.equal(stops, 1);
    finishHangup();
    await hangingUp;
    assert.deepEqual(calls, [
      "answer_doorbell_call", "hangup_doorbell_call", "stop_doorbell_video",
    ]);
    assert.equal(card._lifecycle.answeringDoorbell, false);
  } finally {
    card.disconnectedCallback();
    acknowledge?.();
    finishHangup?.();
    grant?.({ getTracks: () => [{ stop() {} }], getAudioTracks: () => [] });
    await answering;
    await hangingUp;
    if (descriptor) Object.defineProperty(globalThis, "navigator", descriptor);
    else delete globalThis.navigator;
  }
});

test("Home Call cannot change the owner of a doorbell start waiting for microphone permission", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?home-call-pending-doorbell-microphone");
  const Card = registry.get("c300x-doorbell-call-card");
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  try {
    for (const ring of [false, true]) {
      const card = new Card();
      let grant;
      let starting;
      let microphoneRequests = 0;
      try {
        Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
          mediaDevices: { getUserMedia: () => {
            microphoneRequests++;
            return new Promise((resolve) => { grant = resolve; });
          } },
        } });
        card._ensureDoorbellPreview = async () => {};
        card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
        const hass = fakeHass({ cameraEntity: { state: "idle", attributes: {
          media_primary_action: ring ? "answer_ring" : "start_stream",
          media_state: ring ? "ring_pending" : "idle",
        } } });
        hass.callService = async () => {};
        card.hass = hass;
        const starts = [];
        card._webrtc.start = async ({ mediaElement }) => {
          starts.push([card._webrtc._webrtcGetClientConfigCommand(), mediaElement.selector]);
        };
        starting = card._actions.handlePrimaryAction();
        await new Promise(setImmediate);
        assert.equal(typeof grant, "function");
        assert.equal(card._homeActionButtonEl.disabled, true);
        // Exercise the handler too: a stale enabled button must not change ownership.
        await card._homeActionButtonEl.dispatch("click");
        assert.equal(card._lifecycle.activeHomeCallSession, false);
        assert.equal(microphoneRequests, 1);

        grant({ getTracks: () => [{ stop() {} }], getAudioTracks: () => [] });
        await starting;
        assert.deepEqual(starts, [["camera/webrtc/get_client_config", "video"]]);
      } finally {
        card.disconnectedCallback();
        grant?.({ getTracks: () => [{ stop() {} }], getAudioTracks: () => [] });
        await starting;
      }
    }
  } finally {
    if (descriptor) Object.defineProperty(globalThis, "navigator", descriptor);
    else delete globalThis.navigator;
  }
});

test("Home Call hangup cancels its own pending microphone request", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?home-call-cancel-pending-microphone");
  const Card = registry.get("c300x-doorbell-call-card");
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  const card = new Card();
  let grant;
  let starting;
  let starts = 0;
  let stops = 0;
  try {
    Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
      mediaDevices: { getUserMedia: () => new Promise((resolve) => { grant = resolve; }) },
    } });
    card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
    const hass = fakeHass();
    const calls = [];
    hass.callService = async (_domain, service) => { calls.push(service); };
    card.hass = hass;
    card._webrtc.start = async () => { starts++; };
    starting = card._actions.handleHomeCallAction();
    await new Promise(setImmediate);
    assert.equal(card._lifecycle.startingCall, true);
    assert.equal(card._lifecycle.activeHomeCallSession, true);
    assert.equal(card._homeActionButtonEl.disabled, false);
    await card._homeActionButtonEl.dispatch("click");
    assert.deepEqual(calls, ["stop_home_call"]);

    grant({ getTracks: () => [{ stop() { stops++; } }], getAudioTracks: () => [] });
    await starting;
    assert.equal(starts, 0);
    assert.equal(stops, 1);
    assert.equal(card._lifecycle.startingCall, false);
    assert.equal(card._lifecycle.activeHomeCallSession, false);
  } finally {
    card.disconnectedCallback();
    grant?.({ getTracks: () => [{ stop() {} }], getAudioTracks: () => [] });
    await starting;
    if (descriptor) Object.defineProperty(globalThis, "navigator", descriptor);
    else delete globalThis.navigator;
  }
});

test("a card attached again during the same ring starts the preview again", async () => {
  const registry = installFakeDom();
  await import("../../custom_components/bticino_c300x/frontend/c300x-doorbell-call-card.js?reattach-preview");
  const Card = registry.get("c300x-doorbell-call-card");
  const card = new Card();
  card.setConfig({ entity: "camera.bticino_c300x_doorbell_camera" });
  let starts = 0;
  card._startTalkback = async () => { starts++; return false; };
  const ringing = fakeHass({cameraEntity: {state: "idle", attributes: {
    media_state: "ring_pending", media_primary_action: "answer_ring",
  }}});
  try {
    card.hass = ringing;
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(starts, 1);
    // The preview is running when the element is detached.
    card._lifecycle.ringPreviewStarted = true;
    card._lifecycle.ringPreviewActive = true;
    card.disconnectedCallback();
    card.connectedCallback();
    card.hass = ringing;
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(starts, 2);
  } finally {
    card.disconnectedCallback();
  }
});
