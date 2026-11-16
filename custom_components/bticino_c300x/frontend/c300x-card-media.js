import { c300xMediaState } from "./c300x-state-model.js?v=1402c4dbdb9334ff";
import "./c300x-media-controls.js?v=1402c4dbdb9334ff";

// Archive playback never owns a device session. Only the existing card actions
// may start/answer/hang up; this adapter gives those sessions visual priority.
export class C300XCardMedia {
  constructor(card) {
    this.card = card;
    this.fullscreenGeneration = 0;
    this.fullscreenPending = false;
    this.controls = card.shadowRoot.querySelector("c300x-media-controls");
    this.target = card.shadowRoot.querySelector("ha-card");
    this.controls?.addEventListener("archive-changed", () => card._scheduleUpdate());
    this.controls?.addEventListener("media-volume", (event) => {
      if (card._disposed) return;
      event.stopPropagation();
      const volume = Number(event.detail?.volume);
      if (!Number.isFinite(volume)) return;
      card._playbackVolume = Math.max(0, Math.min(1, volume));
      card._playbackMuted = event.detail?.muted === true;
      card._webrtc?.refreshPlayback();
      card._transitionWebrtc?.refreshPlayback();
      this.configure();
    });
    this.controls?.addEventListener("media-fullscreen", () => this.toggleFullscreen());
    this.target?.addEventListener("fullscreenchange", () => this.configure());
  }

  get browsing() { return this.controls?.browsing === true; }

  configure() {
    const card = this.card;
    if (card._disposed || !card._config) return;
    const entity = card._cameraEntity();
    const state = c300xMediaState(entity);
    const lifecycle = card._lifecycle;
    const live = !!card._webrtc?.remoteStream;
    const busy = live || !!card._webrtc?.running || !!card._transitionWebrtc
      || card._talkbackStarting || lifecycle.startingCall || lifecycle.answeringDoorbell
      || lifecycle.hangupInProgress || lifecycle.activeHomeCallSession
      || /^(ring_|home_call_)/.test(state) || entity?.attributes?.external_media_active === true;
    this.controls?.configure?.({
      hass: card._hass, entryId: card._entryId(),
      enabled: !card._isHomeCallMode() && card._config.show_media_history !== false,
      busy: !!busy, live,
      hasAudio: !!card._webrtc?.remoteStream?.getAudioTracks?.().length,
      volume: card._playbackVolume ?? 1, muted: card._playbackMuted === true,
      fullscreenAvailable: typeof this.target?.requestFullscreen === "function",
      fullscreen: this.target?.ownerDocument?.fullscreenElement === this.target
        || card.shadowRoot.fullscreenElement === this.target,
    });
  }

  clear() { this.controls?.clearMedia?.(); }

  deactivate() {
    this.fullscreenGeneration++;
    this.controls?.deactivate?.();
    if (this.card.shadowRoot?.fullscreenElement === this.target) {
      this.target.ownerDocument.exitFullscreen?.().catch?.(() => {});
    }
  }

  async toggleFullscreen() {
    if (this.card._disposed || !this.target || this.fullscreenPending) return;
    const generation = this.fullscreenGeneration;
    this.fullscreenPending = true;
    try {
      const document = this.target.ownerDocument;
      if (this.card.shadowRoot.fullscreenElement === this.target) {
        await document.exitFullscreen?.();
      } else {
        await this.target.requestFullscreen?.();
      }
      if (generation !== this.fullscreenGeneration
        && this.card.shadowRoot.fullscreenElement === this.target) {
        await document.exitFullscreen?.();
      }
    } catch (_error) {
      // Unsupported/denied fullscreen leaves playback and the call untouched.
    } finally { this.fullscreenPending = false; }
    this.configure();
  }
}
