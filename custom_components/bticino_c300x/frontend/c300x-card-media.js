import { c300xMediaState } from "./c300x-state-model.js?v=598781cfd4f44c2d";
import "./c300x-media-controls.js?v=598781cfd4f44c2d";
import "./c300x-picture-controls.js?v=598781cfd4f44c2d";

// Archive playback never owns a device session. Only the existing card actions
// may start/answer/hang up; this adapter gives those sessions visual priority.
export class C300XCardMedia {
  constructor(card) {
    this.card = card;
    this.fullscreenGeneration = 0;
    this.fullscreenPending = false;
    this.controls = card.shadowRoot.querySelector("c300x-media-controls");
    this.picture = card.shadowRoot.querySelector("c300x-picture-controls");
    this.target = card.shadowRoot.querySelector("ha-card");
    this.frame = card.shadowRoot.querySelector("dialog");
    this.controls?.addEventListener("media-expand", () => this.setExpanded(true));
    this.controls?.addEventListener("media-collapse", () => this.setExpanded(false));
    // A drag that starts on a control and ends beside the window is not a dismissal.
    this.frame?.addEventListener("pointerdown", (event) => { this.pressedBeside = event.target === this.frame; });
    this.frame?.addEventListener("click", (event) => {
      if (event.target === this.frame && this.pressedBeside) this.setExpanded(false);
      this.pressedBeside = false;
    });
    this.frame?.addEventListener("close", () => this.collapsed());
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
    // The open picture panel covers the toolbar on a short picture; adjusting
    // the picture needs no volume, so the toolbar steps aside until it closes.
    this.picture?.addEventListener("picture-toggle", () => {
      this.controls?.toggleAttribute("picture-open", this.picture.open === true);
    });
    this.target?.addEventListener("fullscreenchange", () => this.configure());
  }

  get browsing() { return this.controls?.browsing === true; }
  get expanded() { return this.frame?.open === true; }

  // The card itself becomes the window: its media elements never move, so a
  // running stream or call is not interrupted by opening or closing it.
  setExpanded(expanded) {
    const frame = this.frame;
    if (this.card._disposed || typeof frame?.showModal !== "function" || expanded === this.expanded) return;
    if (!expanded) { frame.close(); this.collapsed(); return; }
    this.card.style?.setProperty?.("min-height", `${this.card.offsetHeight || 0}px`);
    frame.removeAttribute("role");
    frame.setAttribute("aria-label", this.card._titleEl?.textContent || "");
    try { frame.showModal(); } catch (_error) { this.collapsed(); return; }
    this.wasExpanded = true;
    this.configure();
    this.controls?.focusControl?.("close");
  }

  collapsed() {
    this.fullscreenGeneration++;
    this.exitFullscreen();
    this.card.style?.removeProperty?.("min-height");
    this.frame?.setAttribute("role", "none");
    this.frame?.removeAttribute("aria-label");
    this.configure();
    if (this.wasExpanded) this.controls?.focusControl?.("expand");
    this.wasExpanded = false;
  }

  exitFullscreen() {
    if (this.card.shadowRoot?.fullscreenElement === this.target) {
      this.target.ownerDocument.exitFullscreen?.().catch?.(() => {});
    }
  }

  pictureSession(entity) {
    const card = this.card;
    const attrs = entity?.attributes;
    if (!card._entryId() || card._isHomeCallMode() || attrs?.picture_controls_supported !== true
      || card._config.show_picture_controls === false) return null;
    const state = c300xMediaState(entity);
    if (/^(ring_pending|ring_preview_active|ring_answering|ring_active)$/.test(state)) return "ring";
    if (state === "on_demand_active" && attrs.picture_controls_scope === "ring_and_on_demand"
      && entity.state !== "unavailable" && entity.state !== "unknown" && attrs.external_media_active !== true
      && !this.browsing && card._webrtc?.remoteStream?.getVideoTracks?.().some(track => track.readyState === "live")) return "on_demand";
    return null;
  }

  configure() {
    const card = this.card;
    if (card._disposed || !card._config) return;
    const entity = card._cameraEntity();
    const state = c300xMediaState(entity);
    const lifecycle = card._lifecycle;
    const live = !!card._webrtc?.remoteStream;
    this.picture?.configure?.(card._hass, card._entryId(), this.pictureSession(entity));
    // The panel is see-through only over a live picture; over the empty text
    // or a still it stays opaque.
    this.picture?.toggleAttribute?.("live", !this.browsing
      && !!card._webrtc?.remoteStream?.getVideoTracks?.().some(track => track.readyState === "live"));
    const busy = live || !!card._webrtc?.running || !!card._transitionWebrtc
      || card._talkbackStarting || lifecycle.startingCall || lifecycle.answeringDoorbell
      || lifecycle.hangupInProgress || lifecycle.activeHomeCallSession
      || /^(ring_|home_call_)/.test(state) || entity?.attributes?.external_media_active === true;
    this.controls?.configure?.({
      hass: card._hass, entryId: card._entryId(),
      enabled: !card._isHomeCallMode() && card._config.show_media_history !== false,
      busy: !!busy, live: live && !!card._webrtc.remoteStream.getVideoTracks?.().length,
      hasAudio: !!card._webrtc?.remoteStream?.getAudioTracks?.().length,
      scaledVolume: !!card._webrtc?.gainEngaged,
      volume: card._playbackVolume ?? 1, muted: card._playbackMuted === true,
      still: this.card._snapshotEl?.hidden === false,
      // While browsing the still is hidden, but it is what the card returns to.
      stillAt: card._snapshotUrl && (card._snapshotEl?.hidden === false || this.browsing)
        ? card._snapshotCapturedAt : null,
      expandAvailable: typeof this.frame?.showModal === "function", expanded: this.expanded,
      fullscreenAvailable: this.expanded && typeof this.target?.requestFullscreen === "function",
      fullscreen: this.target?.ownerDocument?.fullscreenElement === this.target
        || card.shadowRoot.fullscreenElement === this.target,
    });
  }

  clear() { this.controls?.clearMedia?.(); }

  reattached() {
    if (this.expanded) this.frame.close();
  }

  deactivate() {
    this.fullscreenGeneration++;
    this.controls?.deactivate?.();
    if (this.expanded) this.frame.close();
    this.exitFullscreen();
    this.card.style?.removeProperty?.("min-height");
    this.frame?.setAttribute("role", "none");
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
