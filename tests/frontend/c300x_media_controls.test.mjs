import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { C300X_MEDIA_TRANSLATIONS, mediaDate, mediaLanguage, mediaLocalize } from "../../custom_components/bticino_c300x/frontend/c300x-media-translations.js";

class Node extends EventTarget {
  constructor() {
    super();
    this.attributes = new Map();
    this.children = new Map();
    this.hidden = false;
    this.paused = true;
    this.duration = 120;
    this.currentTime = 0;
    this.plays = this.pauses = this.loads = 0;
  }
  querySelector(selector) {
    if (!this.children.has(selector)) this.children.set(selector, new Node());
    return this.children.get(selector);
  }
  setAttribute(key, value) { this.attributes.set(key, String(value)); }
  getAttribute(key) { return this.attributes.get(key) ?? null; }
  removeAttribute(key) { this.attributes.delete(key); }
  set src(value) { this.setAttribute("src", value); }
  get src() { return this.getAttribute("src"); }
  async play() { this.paused = false; this.plays++; this.dispatchEvent(new Event("play")); }
  pause() { this.paused = true; this.pauses++; }
  load() { this.loads++; this.currentTime = 0; }
}
globalThis.HTMLElement = class extends EventTarget {
  isConnected = false;
  attachShadow() { return this.shadowRoot = new Node(); }
};
globalThis.customElements = { get() {}, define() {} };
const { C300XMediaControls } = await import("../../custom_components/bticino_c300x/frontend/c300x-media-controls.js");
const tick = () => new Promise(setImmediate);
const item = (id = "a", kind = "image", at = 10) => ({ id: id.repeat(64), kind, at,
  expires_at: Date.now() / 1000 + 3600, revision: "first" });

function harness(t, initial = [item()], options = {}) {
  const state = { items: initial, fetches: 0, subscriptions: 0, released: 0, events: [], volumes: [], fullscreens: 0 };
  const controls = state.controls = new C300XMediaControls();
  const hass = state.hass = { language: "en", user: { id: "alice" }, auth: {}, connection: {
    async subscribeMessage(callback) { state.callback = callback; state.subscriptions++; return () => state.released++; },
  }, async fetchWithAuth(path) {
    state.fetches++;
    if (path.endsWith("/entry")) return new Response(JSON.stringify({ items: state.items }), { headers: { "Content-Type": "application/json" } });
    const video = state.items.find((entry) => path.endsWith(entry.id))?.kind === "video";
    return new Response("media", { headers: { "Content-Type": video ? "video/mp4" : "image/jpeg" } });
  } };
  controls.addEventListener("archive-changed", (event) => state.events.push({ browsing: controls.browsing, bubbles: event.bubbles, composed: event.composed }));
  controls.addEventListener("media-volume", (event) => state.volumes.push(event));
  controls.addEventListener("media-fullscreen", (event) => { state.fullscreens++; state.fullscreenEvent = event; });
  state.configure = (extra = {}) => controls.configure({ hass, entryId: "entry", ...options, ...extra });
  state.configure();
  controls.isConnected = true;
  controls.connectedCallback();
  state.click = (name) => controls.nodes[name].dispatchEvent(new Event("click"));
  t.after(() => controls.deactivate());
  return state;
}

test("default config leaves parent preview intact and subscribes lazily after attachment", async (t) => {
  const s = harness(t);
  await tick();
  assert.equal(s.controls.config.enabled, true);
  assert.equal(s.controls.browsing, false);
  assert.equal(s.controls.nodes.archive.hidden, true);
  assert.equal(s.controls.video.src, null);
  assert.equal(s.fetches, 0);
  assert.equal(s.subscriptions, 1);
  assert.equal(s.controls.nodes.previous.hidden, false);
  assert.equal(s.controls.nodes.previous.disabled, false);
  assert.equal(s.controls.nodes.next.disabled, true);
});

for (const options of [{}, { busy: true }, { enabled: false }]) {
  test(`unchanged configuration skips renders while refreshing hass: ${JSON.stringify(options)}`, async (t) => {
    const s = harness(t, [], options), c = s.controls;
    await tick();
    let renders = 0, configurations = 0;
    const render = c.render.bind(c), configure = c.history.configure.bind(c.history);
    c.render = () => { renders++; render(); };
    c.history.configure = (value) => { configurations++; configure(value); };
    let latest;
    for (let index = 0; index < 100; index++) {
      latest = { ...s.hass, fetchWithAuth: s.hass.fetchWithAuth.bind(s.hass), states: { unrelated: index } };
      s.configure({ hass: latest });
    }
    assert.equal(renders, 0);
    assert.equal(configurations, 100);
    assert.equal(c.history.hass, latest);
    assert.equal(c.history.hass.fetchWithAuth, latest.fetchWithAuth);
    assert.equal(s.subscriptions, options.enabled === false ? 0 : 1);
    assert.equal(s.fetches, 0);
  });
}

for (const boundary of ["deactivate", "closed", "reconnect"]) {
  test(`${boundary} reactivation restores navigation despite an unchanged configuration signature`, async (t) => {
    const s = harness(t), c = s.controls;
    await tick();
    assert.equal(c.nodes.previous.hidden, false);
    if (boundary === "closed") s.callback({ entry_id: "entry", closed: true });
    else c.deactivate();  // "reconnect": a removed card ends its controls
    assert.equal(c.history.active, false);
    assert.equal(c.nodes.previous.hidden, true);
    let renders = 0;
    const render = c.render.bind(c);
    c.render = () => { renders++; render(); };
    if (boundary === "reconnect") {
      c.isConnected = true;
      c.connectedCallback();
    } else s.configure();
    assert.equal(c.history.active, true);
    assert.equal(c.nodes.previous.hidden, false);
    assert.equal(c.nodes.previous.disabled, false);
    assert.equal(renders, 1);
    assert.equal(s.fetches, 0);
    s.configure();
    assert.equal(renders, 1);
    await tick();
    assert.equal(s.subscriptions, 2);
    assert.equal(s.released, 1);
    s.click("previous");
    await tick();
    assert.equal(c.browsing, true);
  });
}

test("configuration renders changed presentation and in-place language updates once", async (t) => {
  const s = harness(t), c = s.controls;
  let renders = 0;
  const render = c.render.bind(c);
  c.render = () => { renders++; render(); };
  for (const change of [{ busy: true }, { live: true }, { hasAudio: true }, { volume: 0.5 },
    { muted: true }, { label: "Camera" }, { fullscreenAvailable: true }, { fullscreen: true }]) {
    const before = renders;
    s.configure(change);
    assert.equal(renders, before + 1);
    s.configure(change);
    assert.equal(renders, before + 1);
  }
  s.hass.language = "de-DE";
  const before = renders;
  s.configure();
  assert.equal(renders, before + 1);
  assert.equal(c.nodes.previous.getAttribute("aria-label"), "\u00c4ltere Medien");
  delete s.hass.language;
  s.hass.locale = { language: "fr" };
  s.configure();
  assert.equal(c.nodes.previous.getAttribute("aria-label"), "M\u00e9dias plus anciens");
});

for (const identity of ["auth", "connection", "user"]) {
  test(`${identity} replacement clears playback and coalesces configuration rendering`, async (t) => {
    const s = harness(t, [item("a", "video")]), c = s.controls;
    await c.history.step(1);
    await c.togglePlay();
    await tick();
    let renders = 0;
    const render = c.render.bind(c);
    c.render = () => { renders++; render(); };
    const hass = { ...s.hass, [identity]: { ...s.hass[identity] } };
    if (identity === "user") hass.user.id = "bob";
    s.configure({ hass });
    assert.equal(renders, 1);
    assert.equal(c.history.hass, hass);
    assert.equal(c.browsing, false);
    assert.deepEqual(c.history.items, []);
    assert.equal(c.video.src, null);
    assert.equal(c.video.paused, true);
    assert.equal(s.events.at(-1).browsing, false);
    await tick();
    assert.equal(s.released, 1);
    assert.equal(s.subscriptions, 2);
    s.configure({ hass });
    assert.equal(renders, 1);
  });
}

test("navigation swaps inline media without false browsing toggles or starting playback", async (t) => {
  const s = harness(t, [item("a", "image", 40), item("b", "video", 20)]), c = s.controls;
  await c.history.step(1);
  assert.equal(c.browsing, true);
  assert.equal(c.img.hidden, false);
  assert.equal(c.nodes.stamp.hidden, true);
  assert.equal(c.nodes.play.hidden, true);
  assert.equal(c.nodes.mute.hidden, true);
  assert.match(c.img.alt, /^Snapshot:/);
  await c.history.step(1);
  assert.equal(c.img.hidden, true);
  assert.equal(c.video.hidden, false);
  assert.equal(c.nodes.stamp.hidden, false);
  assert.equal(c.nodes.play.hidden, false);
  assert.equal(c.video.plays, 0);
  assert.equal(c.nodes.previous.disabled, true);
  assert.deepEqual(s.events, [{ browsing: true, bubbles: true, composed: true }]);
  c.clearMedia();
  assert.equal(c.browsing, false);
  assert.equal(c.video.src, null);
  assert.equal(c.video.paused, true);
  assert.equal(c.nodes.archive.hidden, true);
  assert.equal(s.events.at(-1).browsing, false);
  assert.equal(c.video.plays, 0);
});

test("play, pause, scrubber and local volume operate only on selected archive video", async (t) => {
  const s = harness(t, [item("a", "video")], { hasAudio: true }), c = s.controls;
  await c.history.step(1);
  s.click("play");
  await tick();
  assert.equal(c.video.plays, 1);
  assert.equal(c.nodes.play.getAttribute("aria-label"), "Pause");
  c.nodes.seek.value = "32.5";
  c.nodes.seek.dispatchEvent(new Event("input"));
  assert.equal(c.video.currentTime, 32.5);
  assert.equal(c.nodes.elapsed.textContent, "0:32 / 2:00");
  c.setVolume(0.4, true);
  assert.equal(c.video.volume, 0.4);
  assert.equal(c.video.muted, true);
  assert.equal(s.volumes.length, 0);
  assert.equal(c.nodes.mute.getAttribute("aria-label"), "Unmute");
  s.click("play");
  assert.equal(c.video.paused, true);
  c.video.duration = Infinity;
  c.renderTransport();
  assert.equal(c.nodes.seek.disabled, true);
});

test("metadata insertion and parent hass updates do not reset or pause an existing video", async (t) => {
  const s = harness(t, [item("a", "video")]), c = s.controls;
  await c.history.step(1);
  await c.togglePlay();
  c.video.currentTime = 35;
  const url = c.video.src, pauses = c.video.pauses, loads = c.video.loads;
  s.items.unshift(item("b", "image", 60));
  s.callback({ entry_id: "entry" });
  await c.history.listPromise;
  s.configure();
  assert.equal(c.video.src, url);
  assert.equal(c.video.currentTime, 35);
  assert.equal(c.video.pauses, pauses);
  assert.equal(c.video.loads, loads);
  assert.equal(c.video.paused, false);
  assert.equal(s.events.length, 1);
  s.items[1] = { ...s.items[1], revision: "changed" };
  s.callback({ entry_id: "entry" });
  await c.history.listPromise;
  assert.equal(c.browsing, false);
  assert.equal(c.video.src, null);
  assert.equal(c.video.paused, true);
});

test("ring busy, clear and detach synchronously stop playback and reset the overlay", async (t) => {
  const s = harness(t, [item("a", "video")]), c = s.controls;
  await c.history.step(1);
  await c.togglePlay();
  s.configure({ busy: true });
  assert.equal(c.browsing, false);
  assert.equal(c.video.src, null);
  assert.equal(c.video.paused, true);
  assert.equal(c.nodes.previous.hidden, true);
  s.configure();
  await c.history.step(1);
  c.clearMedia();
  assert.equal(c.video.src, null);
  await c.history.step(1);
  c.deactivate();  // the card was removed
  assert.equal(c.video.src, null);
  assert.equal(c.browsing, false);
  assert.equal(c.history.active, false);
});

test("history disable leaves live volume and fullscreen functional without subscriptions", async (t) => {
  const s = harness(t, [], { enabled: false, live: true, hasAudio: true, volume: 0.7, fullscreenAvailable: true }), c = s.controls;
  await tick();
  assert.equal(s.subscriptions, 0);
  assert.equal(c.nodes.previous.hidden, true);
  assert.equal(c.nodes.mute.hidden, false);
  assert.equal(c.nodes.fullscreen.hidden, false);
  assert.equal(c.nodes.mode.textContent, "Live");
  c.setVolume(0.25, false);
  assert.deepEqual(s.volumes[0].detail, { volume: 0.25, muted: false });
  assert.equal(s.volumes[0].bubbles, true);
  assert.equal(s.volumes[0].composed, true);
  s.click("mute");
  assert.deepEqual(s.volumes[1].detail, { volume: 0.25, muted: true });
  s.click("fullscreen");
  assert.equal(s.fullscreens, 1);
  assert.equal(s.fullscreenEvent.composed, true);
  s.configure({ fullscreen: true });
  assert.equal(c.nodes.fullscreen.getAttribute("aria-pressed"), "true");
  assert.equal(c.nodes.fullscreen.getAttribute("aria-label"), "Exit full screen");
  s.configure({ fullscreenAvailable: false });
  assert.equal(c.nodes.fullscreen.hidden, true);
  assert.equal(c.nodes.fullscreen.disabled, true);
  s.click("fullscreen");
  assert.equal(s.fullscreens, 1);
});

test("the picture requests the window, navigation lies on the picture and close ends it", async (t) => {
  const s = harness(t, [item("a"), item("b", "image", 20)], { expandAvailable: true }), c = s.controls;
  const sent = [];
  for (const name of ["media-expand", "media-collapse"]) c.addEventListener(name, (event) => sent.push([name, event.composed]));
  await tick();
  assert.equal(c.nodes.expand.hidden, false);
  assert.equal(c.nodes.close.hidden, true);
  assert.equal(c.nodes.expand.getAttribute("aria-label"), "Open large view");
  s.click("expand");
  assert.deepEqual(sent, [["media-expand", true]]);
  s.configure({ expanded: true });
  assert.equal(c.nodes.expand.hidden, true);
  assert.equal(c.nodes.close.hidden, false);
  assert.equal(c.nodes.close.getAttribute("aria-label"), "Close");
  s.click("expand");
  assert.equal(sent.length, 1);
  s.click("close");
  assert.deepEqual(sent[1], ["media-collapse", true]);
  s.configure({ expandAvailable: false });
  assert.equal(c.nodes.expand.hidden, true);
  s.click("expand");
  assert.equal(sent.length, 2);
  const template = readFileSync(new URL("../../custom_components/bticino_c300x/frontend/c300x-media-controls-template.js", import.meta.url), "utf8");
  const stage = template.slice(template.indexOf('<div class="stage">'), template.indexOf('<div class="toolbar"'));
  assert.match(stage, /class="expand"/);
  assert.match(stage, /button\("previous nav"/);
  assert.match(stage, /button\("next nav"/);
  assert.match(stage, /button\("close"/);
  assert.match(template, /\.nav:disabled \{ opacity: 0; pointer-events: none; \}/);
  assert.match(stage, /button\("fullscreen"/);
  assert.match(stage, /class="mode"/);
  assert.equal(template.includes('"current"'), false);
  assert.equal(c.nodes.toolbar.hidden, true);
  assert.equal(c.nodes.info.hidden, true);
  s.configure({ expandAvailable: true, expanded: true, fullscreenAvailable: true });
  assert.equal(c.nodes.fullscreen.hidden, false);
  assert.equal(c.nodes.toolbar.hidden, true);
  s.configure({ expandAvailable: true, still: true });
  assert.equal(c.nodes.info.hidden, false);
  assert.equal(c.nodes.mode.textContent, "Snapshot");
  s.configure({ expandAvailable: true, live: true });
  assert.equal(c.nodes.mode.textContent, "Live");
  assert.doesNotMatch(template.slice(template.indexOf('<div class="toolbar"')), /"previous|"next/);
});

test("mode labels are text-only; volume normalization and language updates are safe", async (t) => {
  const s = harness(t, [], { enabled: false, label: '<img src="x">', volume: NaN, hasAudio: true }), c = s.controls;
  assert.equal(c.nodes.mode.textContent, '<img src="x">');
  assert.equal(c.config.volume, 1);
  s.hass.language = "de-DE";
  s.configure({ volume: -1 });
  assert.equal(c.config.volume, 0);
  assert.equal(c.nodes.volume.getAttribute("aria-label"), "Lautst\u00e4rke");
  c.setVolume(10, false);
  assert.equal(s.volumes[0].detail.volume, 1);
});

test("four standalone translations cover controls and follow HA language fallback conventions", () => {
  const keys = Object.keys(C300X_MEDIA_TRANSLATIONS.en).sort();
  for (const language of ["en", "de", "fr", "it"]) {
    assert.deepEqual(Object.keys(C300X_MEDIA_TRANSLATIONS[language]).sort(), keys);
    assert.ok(Object.values(C300X_MEDIA_TRANSLATIONS[language]).every((value) => typeof value === "string" && value));
  }
  assert.equal(mediaLanguage({ locale: { language: "fr-CH" } }), "fr");
  assert.equal(mediaLocalize({ language: "it-IT" }, "play"), "Riproduci");
  assert.equal(mediaLocalize({ language: "zz" }, "play"), "Play");
  assert.doesNotThrow(() => mediaDate({ language: "not_a_locale" }, 10));
});

test("new media modules keep HA controls on a picture that fills the card, without device APIs", () => {
  const root = new URL("../../custom_components/bticino_c300x/frontend/", import.meta.url);
  const template = readFileSync(new URL("c300x-media-controls-template.js", root), "utf8");
  assert.match(template, /\.archive \{ position: absolute; inset: 0;/);
  assert.match(template, /\.stage \{ position: absolute; inset: 0;/);
  assert.equal(template.includes("toolbar-height"), false);
  assert.match(template, /object-fit: contain/);
  assert.match(template, /type="range"/);
  assert.match(template, /<ha-icon/);
  assert.match(template, /:focus-visible/);
  for (const module of ["controls", "controls-template", "history", "translations"]) {
    const source = readFileSync(new URL(`c300x-media-${module}.js`, root), "utf8");
    for (const forbidden of ["callService", "callWS", "getUserMedia", "RTCPeerConnection", "setInterval", "autoplay", "srcObject", "paper-", "mwc-"]) {
      assert.equal(source.includes(forbidden), false, `${module}: ${forbidden}`);
    }
    assert.ok(source.split("\n").length < 400, module);
  }
});

test("the volume slider is hidden where the platform fixes the media volume", async (t) => {
  const previous = globalThis.document;
  globalThis.document = { createElement: () => ({ get volume() { return 1; }, set volume(_value) {} }) };
  t.after(() => { globalThis.document = previous; });
  const s = harness(t, [], { enabled: false, live: true, hasAudio: true }), c = s.controls;
  await tick();
  assert.equal(c.nodes.mute.hidden, false);
  assert.equal(c.nodes.volume.hidden, true);
  s.click("mute");
  assert.equal(s.volumes[0].detail.muted, true);
});

test("with a fixed media volume the slider stays for a live stream scaled by the card", async (t) => {
  const previous = globalThis.document;
  globalThis.document = { createElement: () => ({ get volume() { return 1; }, set volume(_value) {} }) };
  t.after(() => { globalThis.document = previous; });
  const s = harness(t, [], { enabled: false, live: true, hasAudio: true, scaledVolume: true }), c = s.controls;
  await tick();
  assert.equal(c.nodes.volume.hidden, false);
  s.configure({ live: true, hasAudio: true, scaledVolume: false });
  assert.equal(c.nodes.volume.hidden, true);
});

test("an arrow that cannot be used lets clicks through to the picture", async (t) => {
  const template = readFileSync(new URL("../../custom_components/bticino_c300x/frontend/c300x-media-controls-template.js", import.meta.url), "utf8");
  assert.match(template, /\.nav:disabled \{[^}]*pointer-events: none/);
  const s = harness(t, [item()]), c = s.controls;
  await tick();
  assert.equal(c.nodes.next.disabled, true, "nothing newer while no saved item is open");
  s.click("previous");
  await tick();
  assert.equal(c.browsing, true);
  assert.equal(c.nodes.previous.disabled, true, "the oldest item has nothing older");
});

test("the controls keep the open saved item when the card is moved", async (t) => {
  const s = harness(t, [item()]), c = s.controls;
  await tick();
  s.click("previous");
  await tick();
  assert.equal(c.browsing, true);
  assert.equal(c.disconnectedCallback, undefined, "only the card decides when its controls end");
  c.isConnected = true;
  c.connectedCallback();
  assert.equal(c.browsing, true);
  assert.equal(c.history.active, true);
});
