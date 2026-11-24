import { C300XMediaHistory } from "./c300x-media-history.js?v=fd15372fe9ca5af1";
import { mediaLocalize, mediaStamp } from "./c300x-media-translations.js?v=fd15372fe9ca5af1";
import { MEDIA_CONTROLS_TEMPLATE } from "./c300x-media-controls-template.js?v=fd15372fe9ca5af1";

const boundedVolume = (value) => Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 1;
const time = (value) => {
  const seconds = Math.floor(Number.isFinite(value) && value > 0 ? value : 0);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
};

// iOS leaves the volume of media elements to the hardware keys: a value
// written to it is ignored. Only mute works there, so the slider is not shown.
function volumeFixed() {
  try {
    const probe = document.createElement("video");
    probe.volume = 0.5;
    return probe.volume !== 0.5;
  } catch (_error) {
    return false;
  }
}

export class C300XMediaControls extends HTMLElement {
  constructor() {
    super();
    this.config = { enabled: true, busy: false, live: false, hasAudio: false,
      volume: 1, muted: false, fullscreenAvailable: false, fullscreen: false,
      expandAvailable: false, expanded: false, still: false };
    this.history = new C300XMediaHistory(() => this.changed());
    this.archiveVolume = 1;
    this.archiveMuted = false;
    this.wasBrowsing = false;
    this.renderedUrl = "";
    this.configuring = false;
    this.historyChanged = false;
  }

  get browsing() { return !!this.history.selected; }

  connectedCallback() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" }).innerHTML = MEDIA_CONTROLS_TEMPLATE;
      this.nodes = Object.fromEntries(["archive", "stamp", "toolbar", "mode", "status", "timeline", "seek",
        "elapsed", "info", "previous", "next", "play", "mute", "volume", "fullscreen", "expand", "close"]
        .map((name) => [name, this.shadowRoot.querySelector(`.${name}`)]));
      this.video = this.shadowRoot.querySelector("video");
      this.volumeFixed = volumeFixed();
      this.img = this.shadowRoot.querySelector("img");
      const on = (name, event, callback) => this.nodes[name].addEventListener(event, callback);
      // A disabled arrow lets clicks through to the picture; a quick second
      // tap on an arrow that just became disabled must not open the window.
      const step = (offset) => { this.navigatedAt = Date.now(); void this.history.step(offset); };
      on("previous", "click", () => step(1));
      on("next", "click", () => step(-1));
      on("play", "click", () => void this.togglePlay());
      on("mute", "click", () => this.setVolume(this.audioVolume, !this.audioMuted));
      on("volume", "input", (event) => this.setVolume(Number(event.target.value), false));
      on("seek", "input", (event) => {
        const value = Number(event.target.value), duration = this.video.duration;
        if (this.isVideo && this.history.url && Number.isFinite(value) && Number.isFinite(duration)) {
          this.video.currentTime = Math.min(duration, Math.max(0, value));
          this.renderTransport();
        }
      });
      const send = (name) => this.dispatchEvent(new Event(name, { bubbles: true, composed: true }));
      on("expand", "click", () => {
        if (this.history.listPromise || Date.now() - (this.navigatedAt || 0) < 700) return;
        if (this.config.expandAvailable && !this.config.expanded) send("media-expand");
      });
      on("close", "click", () => send("media-collapse"));
      on("fullscreen", "click", () => {
        if (this.config.fullscreenAvailable) this.dispatchEvent(new Event("media-fullscreen", { bubbles: true, composed: true }));
      });
      for (const event of ["timeupdate", "durationchange", "loadedmetadata", "play", "pause", "ended", "volumechange"]) {
        this.video.addEventListener(event, () => this.renderTransport());
      }
      for (const media of [this.video, this.img]) media.addEventListener("error", () => {
        if (this.history.url && media.getAttribute("src") === this.history.url) {
          this.history.mediaUnavailable();
        }
      });
    }
    this.configure(this.config);
  }

  configure({ hass, entryId, enabled = true, busy = false, live = false, hasAudio = false,
    volume = 1, muted = false, label = "", fullscreenAvailable = false, fullscreen = false,
    expandAvailable = false, expanded = false, still = false, stillAt = null, scaledVolume = false } = {}) {
    const next = { hass, entryId, enabled, busy, live, hasAudio, volume: boundedVolume(volume),
      muted: !!muted, label: typeof label === "string" ? label : "", fullscreenAvailable, fullscreen,
      expandAvailable: !!expandAvailable, expanded: !!expanded, still: !!still, stillAt,
      scaledVolume: !!scaledVolume };
    this.config = next;
    // Always refresh transport/auth, but batch its synchronous invalidations.
    const wasActive = this.history.active;
    this.configuring = true;
    try { this.history.configure({ ...next, connected: this.isConnected }); }
    finally { this.configuring = false; }
    if (!this.nodes) return;
    const signature = JSON.stringify([enabled, busy, live, hasAudio, next.volume,
      next.muted, next.label, fullscreenAvailable, fullscreen, next.expandAvailable, next.expanded, next.still, next.stillAt, next.scaledVolume, this.history.active,
      hass?.language || hass?.locale?.language || "en"]);
    const changed = this.historyChanged || wasActive !== this.history.active
      || signature !== this.configureSignature;
    this.historyChanged = false;
    this.configureSignature = signature;
    if (changed) this.changed();
  }

  changed() {
    if (this.configuring) { this.historyChanged = true; return; }
    this.render();
    const browsing = this.browsing;
    if (browsing !== this.wasBrowsing) {
      this.wasBrowsing = browsing;
      this.dispatchEvent(new Event("archive-changed", { bubbles: true, composed: true }));
    }
  }

  clearMedia() { this.history.clearMedia(); }
  focusControl(name) { this.nodes?.[name]?.focus?.(); }
  deactivate() { this.history.deactivate(); }
  get isVideo() { return this.history.selected?.kind === "video"; }
  get audioVolume() { return this.browsing ? this.archiveVolume : this.config.volume; }
  get audioMuted() { return this.browsing ? this.archiveMuted : this.config.muted; }
  label(key) { return mediaLocalize(this.config.hass, key); }

  buttonLabel(name, key) {
    const text = this.label(key);
    this.nodes[name].setAttribute("aria-label", text);
    this.nodes[name].title = text;
  }

  setVolume(value, muted) {
    const volume = boundedVolume(value);
    if (this.browsing) {
      if (!this.isVideo) return;
      this.archiveVolume = volume;
      this.archiveMuted = !!muted;
      this.video.volume = volume;
      this.video.muted = !!muted;
    } else if (this.config.hasAudio) {
      this.config.volume = volume;
      this.config.muted = !!muted;
      this.dispatchEvent(new CustomEvent("media-volume", { detail: { volume, muted: !!muted }, bubbles: true, composed: true }));
    }
    this.renderTransport();
  }

  async togglePlay() {
    if (!this.isVideo || !this.history.url || this.config.busy) return;
    const url = this.history.url;
    if (!this.video.paused) this.video.pause();
    else {
      try { await this.video.play(); }
      catch {
        if (this.history.url === url) {
          this.history.error = "unavailable";
          this.render();
        }
      }
    }
  }

  resetMedia() {
    this.renderedUrl = "";
    this.video.pause();
    this.video.removeAttribute("src");
    this.video.load();
    this.img.removeAttribute("src");
    this.video.hidden = this.img.hidden = true;
  }

  render() {
    if (!this.nodes) return;
    const { history: h, nodes: n, config: c } = this;
    if (this.renderedUrl !== h.url) {
      this.resetMedia();
      this.renderedUrl = h.url;
      if (h.url && h.selected) {
        const media = this.isVideo ? this.video : this.img;
        if (this.isVideo) { media.volume = this.archiveVolume; media.muted = this.archiveMuted; }
        media.src = h.url;
        media.hidden = false;
      }
    }
    n.archive.hidden = !this.browsing;
    n.archive.setAttribute("aria-busy", String(!!h.mediaAbort));
    const available = c.enabled && h.active && !c.busy;
    n.previous.hidden = !available;
    n.next.hidden = !available;
    n.previous.disabled = !!h.listPromise || (!h.dirty && h.neighbour(1) >= h.items.length);
    n.next.disabled = !this.browsing || !!h.listPromise;
    n.expand.hidden = !c.expandAvailable || c.expanded;
    n.close.hidden = !c.expanded;
    this.buttonLabel("expand", "expand");
    this.buttonLabel("close", "close");
    n.fullscreen.hidden = !c.fullscreenAvailable;
    n.fullscreen.disabled = !c.fullscreenAvailable;
    n.fullscreen.setAttribute("aria-pressed", String(!!c.fullscreen));
    n.fullscreen.querySelector("ha-icon").setAttribute("icon", c.fullscreen ? "mdi:fullscreen-exit" : "mdi:fullscreen");
    n.toolbar.setAttribute("aria-label", this.label("controls"));
    for (const name of ["previous", "next"]) this.buttonLabel(name, name);
    this.buttonLabel("fullscreen", c.fullscreen ? "exit_fullscreen" : "fullscreen");
    n.mode.textContent = this.browsing ? this.label(h.selected.kind)
      : c.label || (c.live ? this.label("live") : c.still ? this.label("image") : "");
    n.mode.title = n.mode.textContent;
    n.status.textContent = h.error ? this.label(h.error) : h.mediaAbort || h.listPromise ? this.label("loading") : "";
    n.status.title = n.status.textContent;
    n.status.hidden = !n.status.textContent;
    n.info.hidden = !n.mode.textContent && !n.status.textContent;
    n.stamp.hidden = !this.isVideo;
    if (this.isVideo) n.toolbar.setAttribute("data-dated", "");
    else n.toolbar.removeAttribute("data-dated");
    if (h.selected) {
      const date = mediaStamp(c.hass, h.selected.at), label = `${this.label(h.selected.kind)}: ${date}`;
      this.img.alt = label;
      this.video.setAttribute("aria-label", label);
      if (this.isVideo) {
        n.stamp.textContent = mediaStamp(c.hass, h.selected.at);
        n.stamp.dateTime = new Date(h.selected.at * 1000).toISOString();
      }
    }
    this.renderTransport();
  }

  renderTransport() {
    if (!this.nodes) return;
    const { nodes: n, video, config: c } = this;
    const isVideo = this.isVideo, audio = isVideo || (!this.browsing && c.hasAudio);
    n.play.hidden = n.timeline.hidden = !isVideo;
    n.play.disabled = !this.history.url || c.busy;
    const playing = isVideo && !video.paused && !video.ended;
    this.buttonLabel("play", playing ? "pause" : "play");
    n.play.querySelector("ha-icon").setAttribute("icon", playing ? "mdi:pause" : "mdi:play");
    n.mute.hidden = !audio;
    n.volume.hidden = !audio || (this.volumeFixed && (this.browsing || !c.scaledVolume));
    this.buttonLabel("mute", this.audioMuted ? "unmute" : "mute");
    n.mute.setAttribute("aria-pressed", String(!!this.audioMuted));
    n.mute.querySelector("ha-icon").setAttribute("icon", this.audioMuted || !this.audioVolume ? "mdi:volume-off" : "mdi:volume-high");
    n.volume.value = String(this.audioVolume);
    n.volume.setAttribute("aria-label", this.label("volume"));
    n.volume.title = this.label("volume");
    const duration = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : 0;
    n.seek.max = String(duration);
    n.seek.disabled = !isVideo || !duration || !this.history.url;
    n.seek.value = String(Math.min(duration, video.currentTime || 0));
    n.seek.setAttribute("aria-label", this.label("seek"));
    n.seek.setAttribute("aria-valuetext", `${time(video.currentTime)} / ${time(duration)}`);
    n.elapsed.textContent = `${time(video.currentTime)} / ${time(duration)}`;
    n.toolbar.hidden = n.play.hidden && n.mute.hidden;
  }
}

if (!customElements.get("c300x-media-controls")) customElements.define("c300x-media-controls", C300XMediaControls);
