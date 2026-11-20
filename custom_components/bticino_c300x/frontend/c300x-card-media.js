import { c300xMediaState } from "./c300x-state-model.js?v=44746bffe997cf92";
import "./c300x-media-controls.js?v=44746bffe997cf92";

// Archive playback never owns a device session. Only the existing card actions
// may start/answer/hang up; this adapter gives those sessions visual priority.
export class C300XCardMedia {
  constructor(card) {
    this.card = card;
    this.fullscreenGeneration = 0;
    this.fullscreenPending = false;
    this.controls = card.shadowRoot.querySelector("c300x-media-controls");
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
      busy: !!busy, live: live && !!card._webrtc.remoteStream.getVideoTracks?.().length,
      hasAudio: !!card._webrtc?.remoteStream?.getAudioTracks?.().length,
      scaledVolume: !!card._webrtc?.gainEngaged,
      volume: card._playbackVolume ?? 1, muted: card._playbackMuted === true,
      still: this.card._snapshotEl?.hidden === false,
      stillAt: this.card._snapshotEl?.hidden === false ? this.card._snapshotCapturedAt : null,
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
