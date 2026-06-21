import {
  C300X_TRANSLATIONS,
  c300xLanguage,
  c300xLocalize,
} from "./c300x-translations.js";
import {
  C300X_CAMERA_OBJECT_ID,
  C300X_CARD_TAG,
  C300X_CARD_TYPE,
  C300X_DEFAULT_CONFIG,
  C300X_DOCUMENTATION_URL,
  C300X_MEDIA_READINESS_OBJECT_ID,
  c300xEntityId,
  c300xEntryId,
  c300xFirstEntity,
  c300xObjectSuffix,
  c300xRelatedEntity,
  c300xResolveEntity,
} from "./c300x-entity-resolver.js";
import {
  c300xCardViewModel,
  c300xIsHomeCallActive,
  c300xMediaState,
} from "./c300x-state-model.js";
import { C300XRingbackTone } from "./c300x-ringback-tone.js";
import { C300XWebrtcClient } from "./c300x-webrtc-client.js";

function c300xFireConfigChanged(element, config) {
  element.dispatchEvent(new CustomEvent("config-changed", {
    detail: { config },
    bubbles: true,
    composed: true,
  }));
}

class C300XDoorbellCallCard extends HTMLElement {
  static getStubConfig(hass, entityId) {
    const entity = entityId || c300xFirstEntity(
      hass,
      "camera",
      C300X_CAMERA_OBJECT_ID,
    );
    return {
      entity: entity || c300xEntityId("camera", C300X_CAMERA_OBJECT_ID),
      ...C300X_DEFAULT_CONFIG,
    };
  }

  static getConfigElement() {
    return document.createElement("c300x-doorbell-call-card-editor");
  }

  static getEntitySuggestion(hass, entityId) {
    const [domain, objectId] = entityId.split(".");
    if (!domain || !objectId) {
      return null;
    }

    if (domain === "camera") {
      const suffix = c300xObjectSuffix(objectId, C300X_CAMERA_OBJECT_ID);
      if (suffix === null) {
        return null;
      }
      return [
        {
          label: c300xLocalize(hass, "doorstation_card"),
          config: {
            type: C300X_CARD_TYPE,
            ...C300XDoorbellCallCard.getStubConfig(hass, entityId),
          },
        },
      ];
    }

    return null;
  }

  getGridOptions() {
    if (this._isHomeCallMode()) {
      return {
        rows: 1,
        columns: 6,
        min_rows: 1,
        max_rows: 1,
        min_columns: 3,
      };
    }
    return {
      rows: 5,
      columns: 12,
      min_rows: 5,
      max_rows: 5,
      min_columns: 6,
    };
  }

  setConfig(config) {
    this._config = {
      ...C300X_DEFAULT_CONFIG,
      ...config,
    };
    this._micStream = null;
    this._micMuted = false;
    this._webrtc = this._createWebrtcClient();
    this._transitionWebrtc = null;
    this._startingCall = false;
    this._previewStarting = false;
    this._ringPreviewStarted = false;
    this._answeringDoorbell = false;
    this._ringPreviewActive = false;
    this._doorbellAnswered = false;
    this._activeHomeCallSession = false;
    this._error = "";
    this._notice = "";
    this._ringbackTone = new C300XRingbackTone({
      getEnabled: () => this._config?.ringback_tone !== false,
      getVolume: () => this._config?.ringback_volume,
    });
    this._ensureRendered();
  }

  _createWebrtcClient({ onClosed, onTrack } = {}) {
    return new C300XWebrtcClient({
      getHass: () => this._hass,
      getEntityId: () => this._resolvedCameraEntityId(),
      isHomeCallMode: () => this._activeHomeCallSession || this._isHomeCallMode(),
      onClosed: onClosed || ((reason) => this._handleWebrtcClosed(reason)),
      onTrack: onTrack || (() => this._updateState()),
    });
  }

  set hass(hass) {
    this._hass = hass;
    this._ensureRendered();
    this._updateState();
  }

  disconnectedCallback() {
    this._stopRingbackTone();
    this._closePeer(false);
  }

  getCardSize() {
    return this._isHomeCallMode() ? 1 : 7;
  }

  _ensureRendered() {
    if (!this._config || this.shadowRoot) {
      return;
    }

    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100%;
        }
        ha-card {
          overflow: hidden;
          height: 100%;
          display: flex;
          flex-direction: column;
        }
        .media {
          position: relative;
          width: 100%;
          flex: 1 1 auto;
          background: #111;
          min-height: 0;
        }
        video {
          width: 100%;
          height: 100%;
          object-fit: contain;
          display: block;
          background: #111;
        }
        .remote-audio {
          position: absolute;
          width: 1px;
          height: 1px;
          opacity: 0;
          pointer-events: none;
        }
        .transition-video {
          position: absolute;
          width: 1px;
          height: 1px;
          opacity: 0;
          pointer-events: none;
        }
        .empty {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--secondary-text-color);
          font-size: 14px;
          pointer-events: none;
        }
        .body {
          min-height: 48px;
          padding: 4px 16px;
          display: flex;
          align-items: center;
          flex: 0 0 auto;
        }
        .entity-main {
          display: flex;
          align-items: center;
          min-width: 0;
          flex: 1 1 auto;
        }
        .row-actions {
          display: flex;
          align-items: center;
          gap: 8px;
          margin: 0 16px 0 0;
          flex: 0 0 auto;
        }
        .row-action,
        .home-action,
        .mic-action {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 40px;
          height: 40px;
          margin: 0;
          padding: 0;
          border: 0;
          color: var(--state-icon-color);
          background: color-mix(in srgb, var(--state-icon-color) 14%, transparent);
          flex: 0 0 auto;
          --mdc-icon-size: 24px;
          border-radius: 50%;
          cursor: pointer;
          font: inherit;
          transition: background-color 140ms ease, color 140ms ease, transform 140ms ease;
        }
        .row-action.active {
          color: var(--primary-color);
          background: color-mix(in srgb, var(--primary-color) 18%, transparent);
        }
        .home-action.hidden {
          display: none;
        }
        .home-action.active {
          color: var(--primary-color);
          background: color-mix(in srgb, var(--primary-color) 18%, transparent);
        }
        .home-action.dialing {
          color: var(--warning-color, var(--primary-color));
          background: color-mix(in srgb, var(--warning-color, var(--primary-color)) 20%, transparent);
          animation: c300x-ring 900ms ease-in-out infinite;
        }
        .home-action.blocked {
          color: var(--disabled-text-color);
          background: color-mix(in srgb, var(--disabled-text-color) 14%, transparent);
          cursor: default;
        }
        .row-action.dialing,
        .row-action.answerable {
          color: var(--warning-color, var(--primary-color));
          background: color-mix(in srgb, var(--warning-color, var(--primary-color)) 20%, transparent);
          animation: c300x-ring 900ms ease-in-out infinite, c300x-answer-glow 1400ms ease-in-out infinite;
        }
        .row-action.recording {
          position: relative;
          color: var(--error-color);
          background: color-mix(in srgb, var(--error-color) 18%, transparent);
          animation: c300x-record-breathe 1300ms ease-in-out infinite;
        }
        .row-action.blocked {
          color: var(--disabled-text-color);
          background: color-mix(in srgb, var(--disabled-text-color) 14%, transparent);
          cursor: default;
        }
        .row-action.recording::after {
          content: "";
          position: absolute;
          top: 7px;
          right: 7px;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--error-color);
          box-shadow: 0 0 0 0 color-mix(in srgb, var(--error-color) 45%, transparent);
          animation: c300x-record-dot 1100ms ease-out infinite;
        }
        @keyframes c300x-ring {
          0%, 100% { transform: rotate(0deg) scale(1); }
          18% { transform: rotate(-12deg) scale(1.03); }
          36% { transform: rotate(10deg) scale(1.03); }
          54% { transform: rotate(-7deg) scale(1.02); }
          72% { transform: rotate(5deg) scale(1.01); }
        }
        @keyframes c300x-answer-glow {
          0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--warning-color, var(--primary-color)) 0%, transparent); }
          45% { box-shadow: 0 0 0 8px color-mix(in srgb, var(--warning-color, var(--primary-color)) 18%, transparent); }
        }
        @keyframes c300x-record-breathe {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(1.05); }
        }
        @keyframes c300x-record-dot {
          0% { opacity: 1; box-shadow: 0 0 0 0 color-mix(in srgb, var(--error-color) 45%, transparent); }
          100% { opacity: .35; box-shadow: 0 0 0 8px color-mix(in srgb, var(--error-color) 0%, transparent); }
        }
        .row-action:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }
        .mic-action {
          width: 36px;
          height: 36px;
          --mdc-icon-size: 22px;
        }
        .mic-action.muted {
          color: var(--warning-color, var(--primary-color));
          background: color-mix(in srgb, var(--warning-color, var(--primary-color)) 18%, transparent);
        }
        .mic-action.hidden {
          display: none;
        }
        .mic-action:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }
        .action-icon {
          display: flex;
        }
        .entity-text {
          min-width: 0;
        }
        .title {
          font-size: 14px;
          font-weight: 400;
          line-height: 20px;
          color: var(--primary-text-color);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .secondary {
          color: var(--secondary-text-color);
          font-size: 13px;
          line-height: 18px;
        }
        .secondary.error {
          color: var(--error-color);
        }
        .secondary.notice {
          color: var(--warning-color, var(--secondary-text-color));
        }
        .readiness {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          margin-top: 2px;
          min-height: 18px;
          color: var(--secondary-text-color);
          font-size: 12px;
          line-height: 16px;
          cursor: pointer;
        }
        .readiness.hidden {
          display: none;
        }
        .readiness.ready {
          color: var(--success-color, #43a047);
        }
        .readiness.warning {
          color: var(--warning-color, #f9a825);
        }
        .readiness.blocked,
        .readiness.unavailable {
          color: var(--error-color);
        }
        .readiness-icon {
          --mdc-icon-size: 16px;
        }
      </style>
      <ha-card>
        <audio class="remote-audio" autoplay playsinline></audio>
        <div class="media">
          <video playsinline autoplay></video>
          <video class="transition-video" playsinline autoplay></video>
          <div class="empty"></div>
        </div>
        <div class="body">
          <div class="entity-main">
            <div class="row-actions">
              <button class="row-action" type="button">
                <ha-icon class="action-icon" icon="mdi:phone"></ha-icon>
              </button>
              <button class="home-action hidden" type="button">
                <ha-icon class="home-action-icon" icon="mdi:phone"></ha-icon>
              </button>
              <button class="mic-action hidden" type="button">
                <ha-icon class="mic-icon" icon="mdi:microphone"></ha-icon>
              </button>
            </div>
            <div class="entity-text">
              <div class="title"></div>
              <div class="secondary"></div>
              <div class="readiness hidden">
                <ha-icon class="readiness-icon" icon="mdi:check-circle"></ha-icon>
                <span class="readiness-text"></span>
              </div>
            </div>
          </div>
        </div>
      </ha-card>
    `;

    this._videoEl = root.querySelector("video");
    this._transitionVideoEl = root.querySelector(".transition-video");
    this._audioEl = root.querySelector("audio");
    this._mediaEl = root.querySelector(".media");
    this._emptyEl = root.querySelector(".empty");
    this._bodyEl = root.querySelector(".body");
    this._actionButtonEl = root.querySelector(".row-action");
    this._actionIconEl = root.querySelector(".action-icon");
    this._homeActionButtonEl = root.querySelector(".home-action");
    this._homeActionIconEl = root.querySelector(".home-action-icon");
    this._micButtonEl = root.querySelector(".mic-action");
    this._micIconEl = root.querySelector(".mic-icon");
    this._titleEl = root.querySelector(".title");
    this._secondaryEl = root.querySelector(".secondary");
    this._readinessEl = root.querySelector(".readiness");
    this._readinessIconEl = root.querySelector(".readiness-icon");
    this._readinessTextEl = root.querySelector(".readiness-text");

    this._actionButtonEl.addEventListener("click", () => this._handlePrimaryAction());
    this._homeActionButtonEl.addEventListener("click", () => this._handleHomeCallAction());
    this._readinessEl.addEventListener("click", () => this._openRepairs());
    this._micButtonEl.addEventListener("click", (event) => {
      event.stopPropagation();
      this._toggleMicMuted();
    });
    this._updateState();
  }

  _updateState() {
    if (!this.shadowRoot || !this._config) {
      return;
    }

    const homeCallMode = this._isHomeCallMode();
    const autoMode = this._isAutoMode();
    const entity = this._cameraEntity();
    const mediaState = c300xMediaState(entity);
    if (mediaState !== "ring_pending" && mediaState !== "ring_preview_active") {
      this._ringPreviewStarted = false;
    }
    const name = this._displayName(entity);
    const homeSessionActive = this._activeHomeCallSession
      && (this._webrtc.running || !!this._webrtc.remoteStream || this._startingCall);
    const doorstationActive = !homeCallMode
      && !this._activeHomeCallSession
      && (this._webrtc.running || !!this._webrtc.remoteStream);
    const view = c300xCardViewModel({
      cameraEntity: entity,
      homeCallMode,
      active: doorstationActive,
      startingCall: this._startingCall,
      doorbellAnswered: this._doorbellAnswered,
      previewStarting: this._previewStarting,
      ringPreviewActive: this._ringPreviewActive,
    });
    const homeView = c300xCardViewModel({
      cameraEntity: entity,
      homeCallMode: true,
      active: homeSessionActive,
      startingCall: this._startingCall && (homeCallMode || this._activeHomeCallSession),
      doorbellAnswered: false,
      previewStarting: false,
      ringPreviewActive: false,
    });
    const doorstationBlockedByHomeCall = !homeCallMode && homeView.actionActive;
    const actionLabel = this._label(view.actionLabelKey);

    this._titleEl.textContent = name;
    this._emptyEl.textContent = this._label(homeCallMode ? "no_active_home_call" : "no_active_door_call");
    this._bodyEl.classList.toggle("home-call", homeCallMode);
    this._bodyEl.classList.toggle("doorstation", !homeCallMode);
    this._actionIconEl.setAttribute("icon", view.actionIcon);
    this._actionButtonEl.title = actionLabel;
    this._actionButtonEl.setAttribute("aria-label", actionLabel);
    this._actionButtonEl.disabled = view.actionDisabled || doorstationBlockedByHomeCall;
    this._actionButtonEl.classList.toggle("active", view.actionActive);
    this._actionButtonEl.classList.toggle("dialing", view.actionDialing);
    this._actionButtonEl.classList.toggle("answerable", view.actionAnswerable);
    this._actionButtonEl.classList.toggle("blocked", view.actionBlocked || doorstationBlockedByHomeCall);
    this._actionButtonEl.classList.toggle("recording", view.actionRecording);
    this._updateHomeActionButton(homeView, autoMode, doorstationActive);
    this._updateMicButton();
    this._secondaryEl.textContent = this._error
      || this._notice
      || this._labelOrRaw(view.secondaryKey);
    this._secondaryEl.classList.toggle("error", !!this._error);
    this._secondaryEl.classList.toggle("notice", !this._error && !!this._notice);
    this._mediaEl.style.display = view.showMedia ? "" : "none";
    this._emptyEl.style.display = this._webrtc.remoteStream || !view.showEmpty ? "none" : "";
    this._updateReadiness();
    this._syncRingbackTone(view.ringbackActive || (autoMode && homeView.ringbackActive));
    if (view.shouldAutoPreview) {
      this._ensureDoorbellPreview();
    }
  }

  async _handlePrimaryAction() {
    if (!this._isHomeCallMode()) {
      if (this._isConfiguredCallActive() || this._activeHomeCallSession) {
        return;
      }
      const action = this._doorstationView().action;
      if (action === "external_call") {
        return;
      }
      if (action === "hang_up") {
        await this._hangupDoorstation();
        return;
      }
      if (action === "answer") {
        this._answeringDoorbell = true;
        try {
          await this._answerDoorbellCall();
          this._doorbellAnswered = true;
          if (this._ringPreviewActive && this._webrtc.pc) {
            await this._startAnsweredDoorbellStream();
          } else {
            await this._startTalkback();
          }
        } finally {
          this._answeringDoorbell = false;
        }
        return;
      }
      await this._startTalkback();
      return;
    }
    if (this._isConfiguredCallActive() || this._startingCall) {
      await this._hangup();
      return;
    }
    await this._startHomeCallAudio();
  }

  async _handleHomeCallAction() {
    if (!this._isAutoMode()) {
      return;
    }
    if (this._isConfiguredCallActive() || this._activeHomeCallSession || this._startingCall) {
      await this._hangupHomeCall();
      return;
    }
    await this._startHomeCallAudio();
  }

  async _startHomeCallAudio() {
    if (this._webrtc.running || this._startingCall) {
      return;
    }
    this._startingCall = true;
    this._activeHomeCallSession = true;
    this._error = "";
    this._notice = "";

    try {
      await this._startTalkback({ homeCall: true });
    } finally {
      this._startingCall = false;
      this._updateState();
    }
  }

  async _ensureDoorbellPreview() {
    if (
      this._webrtc.running
      || this._transitionWebrtc
      || this._previewStarting
      || this._ringPreviewStarted
      || this._answeringDoorbell
      || this._doorbellAnswered
    ) {
      return;
    }
    this._previewStarting = true;
    try {
      await this._startTalkback({ microphone: false, receiveAudio: false });
      if (this._webrtc.remoteStream && !this._error) {
        this._ringPreviewStarted = true;
        this._ringPreviewActive = true;
        this._updateState();
      }
    } finally {
      this._previewStarting = false;
    }
  }

  async _startTalkback({ microphone = true, receiveAudio = true, homeCall = false } = {}) {
    if (this._webrtc.running || this._transitionWebrtc) {
      return;
    }
    this._error = "";
    this._notice = "";

    try {
      if (microphone) {
        await this._prepareMicrophone();
      } else {
        this._micStream = null;
      }

      const mediaElement = homeCall || this._isHomeCallMode() ? this._audioEl : this._videoEl;
      await this._webrtc.start({
        microphoneStream: this._micStream,
        receiveAudio,
        mediaElement,
      });
    } catch (err) {
      if (err?.message === "HA WebRTC offer cancelled") {
        this._closePeer(true);
        return;
      }
      console.error("C300X talkback failed", err);
      this._error = err?.message || `${err}`;
      this._closePeer(false);
    } finally {
      this._updateState();
    }
  }

  async _startAnsweredDoorbellStream() {
    if (this._transitionWebrtc || !this._transitionVideoEl) {
      return;
    }
    this._error = "";
    this._notice = "";
    await this._prepareMicrophone();

    const previous = this._webrtc;
    const next = this._createWebrtcClient({
      onClosed: (reason) => {
        if (this._transitionWebrtc === next) {
          this._transitionWebrtc = null;
          if (this._transitionVideoEl) {
            this._transitionVideoEl.srcObject = null;
          }
          this._error = reason || "closed";
          this._updateState();
          return;
        }
        this._handleWebrtcClosed(reason);
      },
      onTrack: () => this._updateState(),
    });
    this._transitionWebrtc = next;

    let promoted = false;
    const promote = () => {
      if (promoted || this._transitionWebrtc !== next) {
        return;
      }
      promoted = true;
      this._transitionVideoEl.removeEventListener("loadeddata", promote);
      this._transitionVideoEl.removeEventListener("playing", promote);
      this._videoEl.srcObject = next.remoteStream;
      this._transitionVideoEl.srcObject = null;
      this._webrtc = next;
      this._transitionWebrtc = null;
      previous.close();
      this._ringPreviewActive = false;
      this._doorbellAnswered = true;
      this._updateState();
    };

    this._transitionVideoEl.addEventListener("loadeddata", promote);
    this._transitionVideoEl.addEventListener("playing", promote);
    try {
      await next.start({
        microphoneStream: this._micStream,
        receiveAudio: true,
        mediaElement: this._transitionVideoEl,
      });
      if (this._transitionVideoEl.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
        promote();
      }
    } catch (err) {
      this._transitionVideoEl.removeEventListener("loadeddata", promote);
      this._transitionVideoEl.removeEventListener("playing", promote);
      if (this._transitionWebrtc === next) {
        this._transitionWebrtc = null;
      }
      next.close();
      this._transitionVideoEl.srcObject = null;
      throw err;
    }
  }

  async _prepareMicrophone() {
    const mediaDevices = globalThis.navigator?.mediaDevices;
    const getUserMedia = mediaDevices?.getUserMedia;
    if (typeof getUserMedia !== "function") {
      this._notice = this._label("microphone_required");
      return;
    }
    try {
      this._micStream = await getUserMedia.call(mediaDevices, {
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
      this._applyMicMuted();
    } catch (err) {
      console.warn("C300X microphone unavailable; starting receive-only stream", err);
      this._notice = this._label("microphone_stream_only");
    }
  }

  async _hangup() {
    this._startingCall = false;
    let ok = true;
    try {
      if (this._isHomeCallMode()) {
        await this._stopHomeCall();
      } else {
        await this._stopDoorbellVideo();
      }
    } catch (err) {
      console.error("C300X hangup failed", err);
      this._error = err?.message || `${err}`;
      ok = false;
    } finally {
      this._closePeer(ok);
    }
  }

  async _hangupDoorstation() {
    this._startingCall = false;
    let ok = true;
    try {
      await this._hangupDoorbellCall({ closePeer: false });
    } catch (err) {
      console.error("C300X ring-call hangup failed", err);
      ok = false;
    }
    try {
      await this._stopDoorbellVideo();
    } catch (err) {
      console.error("C300X doorbell video stop failed", err);
      this._error = err?.message || `${err}`;
      ok = false;
    } finally {
      this._closePeer(ok);
    }
  }

  _closePeer(clearStatus, options = {}) {
    if (this._transitionWebrtc) {
      this._transitionWebrtc.close();
      this._transitionWebrtc = null;
    }
    this._webrtc.close();

    if (this._micStream) {
      for (const track of this._micStream.getTracks()) {
        track.stop();
      }
    }
    this._micStream = null;
    this._micMuted = false;

    this._ringPreviewActive = false;
    this._activeHomeCallSession = false;
    if (clearStatus) {
      this._ringPreviewStarted = false;
    }
    this._doorbellAnswered = false;
    if (this._videoEl && !options.keepMediaElement) {
      this._videoEl.srcObject = null;
    }
    if (this._audioEl && !options.keepMediaElement) {
      this._audioEl.srcObject = null;
    }
    if (this._transitionVideoEl) {
      this._transitionVideoEl.srcObject = null;
    }
    this._notice = "";
    if (clearStatus) {
      this._error = "";
    }
    this._updateState();
  }

  _hasMicrophoneTrack() {
    return (this._micStream?.getAudioTracks?.() || []).length > 0;
  }

  _applyMicMuted() {
    for (const track of this._micStream?.getAudioTracks?.() || []) {
      track.enabled = !this._micMuted;
    }
  }

  _toggleMicMuted() {
    if (!this._hasMicrophoneTrack()) {
      return;
    }
    this._micMuted = !this._micMuted;
    this._applyMicMuted();
    this._updateState();
  }

  _updateMicButton() {
    if (!this._micButtonEl || !this._micIconEl) {
      return;
    }
    const visible = this._hasMicrophoneTrack()
      && (this._webrtc.running || this._transitionWebrtc || !!this._webrtc.remoteStream);
    const label = this._label(this._micMuted ? "unmute_microphone" : "mute_microphone");
    this._micButtonEl.classList.toggle("hidden", !visible);
    this._micButtonEl.classList.toggle("muted", this._micMuted);
    this._micButtonEl.disabled = !visible;
    this._micButtonEl.title = label;
    this._micButtonEl.setAttribute("aria-label", label);
    this._micIconEl.setAttribute(
      "icon",
      this._micMuted ? "mdi:microphone-off" : "mdi:microphone",
    );
  }

  _handleWebrtcClosed(reason) {
    if (this._transitionWebrtc) {
      return;
    }
    if (!this._webrtc?.pc && !this._webrtc?.remoteStream && !this._webrtc?.running) {
      return;
    }
    this._closePeer(false);
  }

  _isHomeCallMode() {
    return this._config?.mode === "home_call";
  }

  _isAutoMode() {
    return this._config?.mode === "auto";
  }

  _resolvedCameraEntityId() {
    return c300xResolveEntity(this._hass, this._config, "camera", C300X_CAMERA_OBJECT_ID);
  }

  _cameraEntity() {
    return this._hass?.states?.[this._resolvedCameraEntityId()];
  }

  _mediaReadinessEntity() {
    const entityId = c300xRelatedEntity(
      this._hass,
      this._config,
      "sensor",
      C300X_MEDIA_READINESS_OBJECT_ID,
      "media_readiness_entity",
    );
    return entityId ? this._hass?.states?.[entityId] : null;
  }

  _displayName(entity) {
    if (entity && this._hass?.formatEntityName) {
      try {
        if (this._config.name || this._isHomeCallMode()) {
          return this._hass.formatEntityName(
            entity,
            this._config.name || this._defaultName(),
            { separator: " " },
          );
        }
        return this._hass.formatEntityName(entity);
      } catch (err) {
        console.warn("C300X entity name formatting failed", err);
      }
    }
    if (typeof this._config.name === "string") {
      return this._config.name;
    }
    return entity?.attributes?.friendly_name || this._defaultName();
  }

  _entryId() {
    return c300xEntryId(this._hass, this._config, this._resolvedCameraEntityId());
  }

  _serviceData() {
    const entryId = this._entryId();
    return entryId ? { entry_id: entryId } : {};
  }

  _isConfiguredCallActive() {
    return c300xIsHomeCallActive(this._cameraEntity());
  }

  _updateHomeActionButton(homeView, visible, doorstationActive) {
    if (!this._homeActionButtonEl || !this._homeActionIconEl) {
      return;
    }
    const label = this._label(homeView.actionLabelKey);
    const blockedByDoorstation = doorstationActive && homeView.action !== "hang_up";
    this._homeActionButtonEl.classList.toggle("hidden", !visible);
    this._homeActionButtonEl.classList.toggle("active", homeView.actionActive);
    this._homeActionButtonEl.classList.toggle("dialing", homeView.actionDialing);
    this._homeActionButtonEl.classList.toggle("blocked", blockedByDoorstation);
    this._homeActionButtonEl.disabled = !visible || homeView.actionDisabled || blockedByDoorstation;
    this._homeActionButtonEl.title = label;
    this._homeActionButtonEl.setAttribute("aria-label", label);
    this._homeActionIconEl.setAttribute("icon", homeView.actionIcon);
  }

  _updateReadiness() {
    if (!this._readinessEl || !this._readinessTextEl || !this._readinessIconEl) {
      return;
    }
    const entity = this._mediaReadinessEntity();
    const state = entity?.state;
    const visible = !!entity && this._isAutoMode();
    this._readinessEl.classList.toggle("hidden", !visible);
    if (!visible) {
      return;
    }
    const normalized = ["ready", "warning", "blocked", "unavailable"].includes(state)
      ? state
      : "unknown";
    for (const value of ["ready", "warning", "blocked", "unavailable", "unknown"]) {
      this._readinessEl.classList.toggle(value, normalized === value);
    }
    this._readinessTextEl.textContent = this._label(`media_${normalized}`);
    this._readinessEl.title = this._label("open_repairs");
    this._readinessEl.setAttribute("role", "button");
    this._readinessEl.setAttribute("aria-label", this._label("open_repairs"));
    this._readinessIconEl.setAttribute(
      "icon",
      normalized === "ready"
        ? "mdi:check-circle"
        : normalized === "warning"
          ? "mdi:alert"
          : normalized === "blocked" || normalized === "unavailable"
            ? "mdi:alert-circle"
            : "mdi:help-circle",
    );
  }

  _syncRingbackTone(active) {
    if (active) {
      this._ringbackTone?.start();
      return;
    }
    this._stopRingbackTone();
  }

  _stopRingbackTone() {
    this._ringbackTone?.stop();
  }

  _doorstationView() {
    return c300xCardViewModel({
      cameraEntity: this._cameraEntity(),
      homeCallMode: false,
      active: !this._activeHomeCallSession && (this._webrtc.running || !!this._webrtc.remoteStream),
      startingCall: this._startingCall,
      doorbellAnswered: this._doorbellAnswered,
      previewStarting: this._previewStarting,
      ringPreviewActive: this._ringPreviewActive,
    });
  }

  _defaultName() {
    return this._label(this._isHomeCallMode() ? "home_call_name" : "door_station");
  }

  _label(key) {
    return c300xLocalize(this._hass, key);
  }

  _labelOrRaw(key) {
    return C300X_TRANSLATIONS.en[key] ? this._label(key) : key;
  }

  async _stopHomeCall() {
    if (!this._hass) {
      return;
    }
    await this._hass.callService("bticino_c300x", "stop_home_call", this._serviceData());
  }

  async _hangupHomeCall() {
    this._startingCall = false;
    let ok = true;
    try {
      await this._stopHomeCall();
    } catch (err) {
      console.error("C300X home-call hangup failed", err);
      this._error = err?.message || `${err}`;
      ok = false;
    } finally {
      this._closePeer(ok);
    }
  }

  async _stopDoorbellVideo() {
    if (!this._hass) {
      return;
    }
    if (this._config.hangup_script) {
      await this._runScript(this._config.hangup_script);
      return;
    }
    await this._hass.callService("bticino_c300x", "stop_doorbell_video", this._serviceData());
  }

  async _answerDoorbellCall() {
    if (!this._hass) {
      return;
    }
    await this._hass.callService(
      "bticino_c300x",
      "answer_doorbell_call",
      this._serviceData(),
    );
  }

  async _hangupDoorbellCall({ closePeer = true } = {}) {
    if (!this._hass) {
      return;
    }
    let ok = true;
    try {
      await this._hass.callService("bticino_c300x", "hangup_doorbell_call", this._serviceData());
    } catch (err) {
      console.error("C300X ring-call hangup failed", err);
      this._error = err?.message || `${err}`;
      ok = false;
    } finally {
      if (closePeer) {
        this._closePeer(ok);
      }
    }
  }

  async _runScript(entityId) {
    if (!entityId || !this._hass) {
      return;
    }
    await this._hass.callService("script", "turn_on", {}, { entity_id: entityId });
  }

  _openRepairs() {
    globalThis.history?.pushState?.(null, "", "/config/repairs");
    globalThis.dispatchEvent?.(new Event("location-changed"));
  }
}

class C300XDoorbellCallCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = {
      ...C300XDoorbellCallCard.getStubConfig(this._hass),
      ...config,
    };
    this._render();
  }

  set hass(hass) {
    const languageChanged = c300xLanguage(this._hass) !== c300xLanguage(hass);
    this._hass = hass;
    if (!this.shadowRoot || languageChanged) {
      this._render();
      return;
    }
    const form = this.shadowRoot.querySelector("ha-form");
    if (form) {
      form.hass = hass;
    }
  }

  _render() {
    if (!this._config || !this._hass) {
      return;
    }
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    const homeCallMode = this._config.mode === "home_call";
    const doorbellOnlyMode = this._config.mode === "doorbell_call";
    root.innerHTML = `
      <ha-form></ha-form>
    `;

    const form = root.querySelector("ha-form");
    form.hass = this._hass;
    form.data = this._config;
    form.schema = [
      {
        name: "mode",
        required: true,
        selector: {
          select: {
            mode: "dropdown",
            options: [
              { value: "auto", label: this._label("auto_mode") },
              { value: "doorbell_call", label: this._label("doorbell_call") },
              { value: "home_call", label: this._label("home_call") },
            ],
          },
        },
      },
      {
        name: "entity",
        required: false,
        selector: { entity: { domain: "camera" } },
      },
      {
        name: "name",
        selector: { entity_name: {} },
        context: { entity: "entity" },
      },
      ...(homeCallMode ? [] : [{
        name: "hangup_script",
        selector: { entity: { domain: "script" } },
      }]),
      ...(doorbellOnlyMode ? [] : [
        {
          name: "ringback_tone",
          selector: { boolean: {} },
        },
        {
          name: "ringback_volume",
          selector: {
            number: {
              min: 0,
              max: 100,
              step: 1,
              mode: "slider",
              unit_of_measurement: "%",
            },
          },
        },
      ] : []),
    ];
    form.computeLabel = (schema) => this._label(
      {
        hangup_script: "optional_hangup_script",
        ringback_tone: "ringback_tone",
        ringback_volume: "ringback_volume",
      }[schema.name] || schema.name,
    );
    form.addEventListener("value-changed", (event) => {
      this._setConfig(event.detail.value || {});
    });
  }

  _setConfig(config) {
    const nextConfig = { ...config };
    const modeChanged = this._config.mode !== nextConfig.mode;
    for (const [key, value] of Object.entries(nextConfig)) {
      if (value === "") {
        delete nextConfig[key];
      }
    }
    if (nextConfig.mode === "home_call") {
      delete nextConfig.hangup_script;
    }
    if (nextConfig.mode === "doorbell_call") {
      delete nextConfig.ringback_tone;
      delete nextConfig.ringback_volume;
    }
    delete nextConfig.home_call_entity;
    delete nextConfig.doorbell_state_entity;
    if (JSON.stringify(this._config) === JSON.stringify(nextConfig)) {
      return;
    }
    this._config = nextConfig;
    c300xFireConfigChanged(this, nextConfig);
    if (modeChanged) {
      this._render();
    }
  }

  _label(key) {
    return c300xLocalize(this._hass, key);
  }
}

if (!customElements.get("c300x-doorbell-call-card-editor")) {
  customElements.define("c300x-doorbell-call-card-editor", C300XDoorbellCallCardEditor);
}
if (!customElements.get(C300X_CARD_TAG)) {
  customElements.define(C300X_CARD_TAG, C300XDoorbellCallCard);
}

window.customCards = window.customCards || [];
window.customCards = window.customCards.filter((card) => card.type !== C300X_CARD_TAG);
window.customCards.push({
  type: C300X_CARD_TAG,
  name: "C300X Doorbell Call Card",
  preview: true,
  description: C300X_TRANSLATIONS.en.card_description,
  documentationURL: C300X_DOCUMENTATION_URL,
  getEntitySuggestion: (hass, entityId) => C300XDoorbellCallCard.getEntitySuggestion(hass, entityId),
});
