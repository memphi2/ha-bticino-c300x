import {
  C300X_TRANSLATIONS,
  c300xLocalize,
} from "./c300x-translations.js?v=778ae104bdd8a73d";
import {
  C300X_AUDIO_CODEC_OBJECT_ID,
  C300X_CAMERA_OBJECT_ID,
  C300X_CARD_TAG,
  C300X_CARD_TYPE,
  C300X_DEFAULT_CONFIG,
  C300X_DOCUMENTATION_URL,
  C300X_MEDIA_READINESS_OBJECT_ID,
  c300xEntryId,
  c300xObjectSuffix,
  c300xRelatedEntity,
  c300xResolveEntity,
} from "./c300x-entity-resolver.js?v=778ae104bdd8a73d";
import {
  C300X_CARD_EDITOR_TAG,
  c300xDoorbellCardStubConfig,
} from "./c300x-card-editor.js?v=778ae104bdd8a73d";
import { C300XCardActions } from "./c300x-card-actions.js?v=778ae104bdd8a73d";
import { C300XCardLifecycleState } from "./c300x-card-lifecycle.js?v=778ae104bdd8a73d";
import { C300X_DOORBELL_CARD_TEMPLATE } from "./c300x-card-template.js?v=778ae104bdd8a73d";
import {
  c300xCardViewModel,
  c300xIsHomeCallActive,
  c300xMediaState,
} from "./c300x-state-model.js?v=778ae104bdd8a73d";
import { C300XRingbackTone } from "./c300x-ringback-tone.js?v=778ae104bdd8a73d";
import { C300XWebrtcClient } from "./c300x-webrtc-client.js?v=778ae104bdd8a73d";

const C300X_NOTICE_TIMEOUT_MS = 2000;

class C300XDoorbellCallCard extends HTMLElement {
  static getStubConfig(hass, entityId) {
    return c300xDoorbellCardStubConfig(hass, entityId);
  }

  static getConfigElement() {
    return document.createElement(C300X_CARD_EDITOR_TAG);
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
      columns: 12,
      min_rows: 3,
      max_rows: 10,
      min_columns: 6,
    };
  }

  setConfig(config) {
    this._cancelScheduledUpdate();
    this._config = {
      ...C300X_DEFAULT_CONFIG,
      ...config,
    };
    this._micStream = null;
    this._micMuted = false;
    this._lifecycle = new C300XCardLifecycleState();
    this._actions = new C300XCardActions(this);
    this._webrtc = this._createWebrtcClient();
    this._transitionWebrtc = null;
    this._lastCardGainDb = 0;
    this._audioCodecEntityId = "";
    this._cameraEntityState = null;
    this._stateSubscriptionConnection = null;
    this._stateSubscriptionEntityId = "";
    this._stateSubscriptionToken = 0;
    this._unsubscribeStateEvents = null;
    this._updateFrame = null;
    this._lastRenderSignature = null;
    this._error = "";
    this._notice = "";
    this._noticeTimer = null;
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
      isHomeCallMode: () => this._lifecycle.activeHomeCallSession || this._isHomeCallMode(),
      onClosed: onClosed || ((reason) => this._handleWebrtcClosed(reason)),
      onTrack: onTrack || (() => this._scheduleUpdate()),
      getCardGainDb: () => this._cardGainDb(),
    });
  }

  // The doorstation gain is applied agent-side for speex; in PCMU mode the
  // agent runs passthrough, so the card applies the configured gain in the
  // browser instead. All state is read from HA (the codec select entity and
  // the camera's gain attribute), never fetched from the agent.
  _cardGainDb() {
    if (this._audioCodecMode() !== "pcmu") {
      return 0;
    }
    const cameraEntityId = this._resolvedCameraEntityId();
    const gainDb = this._hass?.states?.[cameraEntityId]?.attributes?.doorstation_audio_gain_db;
    const value = Number(gainDb);
    return Number.isFinite(value) ? value : 0;
  }

  _audioCodecMode() {
    // Cache the resolved select entity id so the common path is an O(1) state
    // lookup instead of scanning hass.entities on every hass update; re-resolve
    // only when the cached id is gone.
    let entityId = this._audioCodecEntityId;
    if (!entityId || !this._hass?.states?.[entityId]) {
      entityId = c300xRelatedEntity(
        this._hass,
        this._config,
        "select",
        C300X_AUDIO_CODEC_OBJECT_ID,
        "audio_codec_entity",
      );
      this._audioCodecEntityId = entityId;
    }
    return entityId ? this._hass?.states?.[entityId]?.state : null;
  }

  _maybeRefreshCardGain() {
    // Ignore transient indeterminate states (the select entity blips to
    // unavailable/unknown on a reload): keep the current gain instead of
    // disengaging it mid-call, which would abruptly change the audio level.
    const mode = this._audioCodecMode();
    if (mode !== "pcmu" && mode !== "speex") {
      return;
    }
    const gainDb = this._cardGainDb();
    if (gainDb === this._lastCardGainDb) {
      return;
    }
    this._lastCardGainDb = gainDb;
    this._webrtc?.refreshGain();
    this._transitionWebrtc?.refreshGain();
  }

  set hass(hass) {
    this._hass = hass;
    this._syncCameraEntityFromHass();
    this._ensureStateSubscription();
    this._maybeRefreshCardGain();
    this._ensureRendered();
    this._scheduleUpdate();
  }

  disconnectedCallback() {
    this._cancelScheduledUpdate();
    this._clearStateSubscription();
    this._clearNoticeTimer();
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
    root.innerHTML = C300X_DOORBELL_CARD_TEMPLATE;

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

    this._actionButtonEl.addEventListener("click", () => this._actions.handlePrimaryAction());
    this._homeActionButtonEl.addEventListener("click", () => this._actions.handleHomeCallAction());
    this._readinessEl.addEventListener("click", () => this._openRepairs());
    this._micButtonEl.addEventListener("click", (event) => {
      event.stopPropagation();
      this._toggleMicMuted();
    });
    this._updateState();
  }

  _renderSignature() {
    const entity = this._cameraEntity();
    const attributes = entity?.attributes || {};
    const readiness = this._mediaReadinessEntity();
    const readinessAttributes = readiness?.attributes || {};
    return JSON.stringify({
      cameraEntityId: this._resolvedCameraEntityId(),
      cameraState: entity?.state || "",
      error: this._error || "",
      externalMediaActive: attributes.external_media_active === true,
      externalOwner: attributes.external_owner || "",
      friendlyName: attributes.friendly_name || "",
      hasMicrophone: this._hasMicrophoneTrack(),
      hasRemoteStream: !!this._webrtc?.remoteStream,
      isStreaming: attributes.is_streaming === true,
      lifecycle: {
        activeHomeCallSession: this._lifecycle.activeHomeCallSession,
        answeringDoorbell: this._lifecycle.answeringDoorbell,
        doorbellAnswered: this._lifecycle.doorbellAnswered,
        hangupInProgress: this._lifecycle.hangupInProgress,
        lastMediaState: this._lifecycle.lastMediaState,
        passiveAnsweredPreviewStarted: this._lifecycle.passiveAnsweredPreviewStarted,
        previewStarting: this._lifecycle.previewStarting,
        ringPreviewActive: this._lifecycle.ringPreviewActive,
        ringPreviewStarted: this._lifecycle.ringPreviewStarted,
        ringPreviewSuppressed: this._lifecycle.ringPreviewSuppressed,
        startingCall: this._lifecycle.startingCall,
      },
      mediaPrimaryAction: attributes.media_primary_action || "",
      mediaState: attributes.media_state || "",
      micMuted: this._micMuted,
      mode: this._config?.mode || "",
      name: this._config?.name || "",
      notice: this._notice || "",
      readinessFailedChecks: readinessAttributes.failed_checks || [],
      readinessForwardingHomeassistant: readinessAttributes.forwarding_homeassistant,
      readinessReason: readinessAttributes.reason || "",
      readinessState: readiness?.state || "",
      ringbackTone: this._config?.ringback_tone !== false,
      ringbackVolume: this._config?.ringback_volume,
      showMediaReadiness: this._config?.show_media_readiness !== false,
      transitionActive: !!this._transitionWebrtc,
      transitionHasRemoteStream: !!this._transitionWebrtc?.remoteStream,
      transitionRunning: !!this._transitionWebrtc?.running,
      videoOwner: attributes.video_owner || "",
      webrtcRunning: !!this._webrtc?.running,
    });
  }

  _scheduleUpdate() {
    if (this._updateFrame !== null && this._updateFrame !== undefined) {
      return;
    }

    const runUpdate = () => {
      this._updateFrame = null;
      const signature = this._renderSignature();
      if (signature === this._lastRenderSignature) {
        return;
      }
      this._lastRenderSignature = signature;
      this._updateState();
    };
    const requestFrame = globalThis.requestAnimationFrame;
    if (typeof requestFrame === "function") {
      this._updateFrame = requestFrame.call(globalThis, runUpdate);
      return;
    }
    this._updateFrame = -1;
    runUpdate();
  }

  _cancelScheduledUpdate() {
    if (this._updateFrame === null || this._updateFrame === undefined) {
      return;
    }
    const cancelFrame = globalThis.cancelAnimationFrame;
    if (typeof cancelFrame === "function" && this._updateFrame !== -1) {
      cancelFrame.call(globalThis, this._updateFrame);
    }
    this._updateFrame = null;
  }

  _updateState() {
    if (!this.shadowRoot || !this._config) {
      return;
    }

    const homeCallMode = this._isHomeCallMode();
    const autoMode = this._isAutoMode();
    const entity = this._cameraEntity();
    const mediaState = c300xMediaState(entity);
    const mediaUpdate = this._lifecycle.evaluateMediaState(mediaState);
    if (!mediaUpdate.ringLifecycleActive) {
      if (
        mediaUpdate.shouldCloseLocalRingPeer
        && (this._webrtc.running || !!this._webrtc.remoteStream || this._transitionWebrtc)
      ) {
        this._closePeer(true);
        return;
      }
    }
    this._lifecycle.commitMediaState(mediaState);
    const name = this._displayName(entity);
    const hasLocalMedia = this._webrtc.running || !!this._webrtc.remoteStream;
    const homeSessionActive = this._lifecycle.homeSessionActive(hasLocalMedia);
    const doorstationActive = this._lifecycle.doorstationActive({
      homeCallMode,
      hasLocalMedia,
    });
    const view = c300xCardViewModel({
      cameraEntity: entity,
      homeCallMode,
      active: doorstationActive,
      startingCall: this._lifecycle.startingCall,
      doorbellAnswered: this._lifecycle.doorbellAnswered,
      previewStarting: this._lifecycle.previewStarting,
      ringPreviewActive: this._lifecycle.ringPreviewActive,
    });
    const homeView = c300xCardViewModel({
      cameraEntity: entity,
      homeCallMode: true,
      active: homeSessionActive,
      startingCall: this._lifecycle.startingCall && (homeCallMode || this._lifecycle.activeHomeCallSession),
      doorbellAnswered: false,
      previewStarting: false,
      ringPreviewActive: false,
    });
    const actionLabel = this._label(view.actionLabelKey);

    this._titleEl.textContent = name;
    this._emptyEl.textContent = this._label(homeCallMode ? "no_active_home_call" : "no_active_door_call");
    this._bodyEl.classList.toggle("home-call", homeCallMode);
    this._bodyEl.classList.toggle("doorstation", !homeCallMode);
    this._actionIconEl.setAttribute("icon", view.actionIcon);
    this._actionButtonEl.title = actionLabel;
    this._actionButtonEl.setAttribute("aria-label", actionLabel);
    this._actionButtonEl.disabled = view.actionDisabled;
    this._actionButtonEl.classList.toggle("active", view.actionActive);
    this._actionButtonEl.classList.toggle("dialing", view.actionDialing);
    this._actionButtonEl.classList.toggle("answerable", view.actionAnswerable);
    this._actionButtonEl.classList.toggle("blocked", view.actionBlocked);
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
    if (this._lifecycle.shouldStartPassiveAnsweredPreview({
      mediaState,
      webrtcRunning: this._webrtc.running,
      transitionActive: !!this._transitionWebrtc,
    })) {
      this._startPassiveAnsweredDoorbellPreview();
    }
    this._lastRenderSignature = this._renderSignature();
  }

  async _ensureDoorbellPreview() {
    if (!this._lifecycle.canStartDoorbellPreview({
      webrtcRunning: this._webrtc.running,
      transitionActive: !!this._transitionWebrtc,
    })) {
      return;
    }
    this._lifecycle.previewStarting = true;
    try {
      await this._startTalkback({ microphone: false, receiveAudio: false });
      if (this._webrtc.remoteStream && !this._error) {
        this._lifecycle.ringPreviewStarted = true;
        this._lifecycle.ringPreviewActive = true;
        this._updateState();
      }
    } finally {
      this._lifecycle.previewStarting = false;
    }
  }

  async _startTalkback({ microphone = true, receiveAudio = true, homeCall = false } = {}) {
    if (this._webrtc.running || this._transitionWebrtc) {
      return;
    }
    this._error = "";
    this._clearNotice();

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
    await this._prepareMicrophone();
    await this._replaceDoorbellWebrtcStream({
      microphoneStream: this._micStream,
      receiveAudio: true,
      onPromoted: () => {
        this._lifecycle.ringPreviewActive = false;
        this._lifecycle.doorbellAnswered = true;
      },
    });
  }

  async _startPassiveAnsweredDoorbellPreview() {
    if (this._transitionWebrtc || !this._transitionVideoEl) {
      return;
    }
    this._lifecycle.passiveAnsweredPreviewStarted = true;
    try {
      await this._replaceDoorbellWebrtcStream({
        microphoneStream: null,
        receiveAudio: false,
        onPromoted: () => {
          this._lifecycle.ringPreviewActive = true;
          this._lifecycle.doorbellAnswered = false;
        },
      });
    } catch (err) {
      this._lifecycle.passiveAnsweredPreviewStarted = false;
      console.error("C300X passive ring preview transition failed", err);
      this._error = err?.message || `${err}`;
      this._updateState();
    }
  }

  async _replaceDoorbellWebrtcStream({
    microphoneStream,
    receiveAudio,
    onPromoted,
  }) {
    if (this._transitionWebrtc || !this._transitionVideoEl) {
      return;
    }
    this._error = "";
    this._clearNotice();
    const previous = this._webrtc;
    let next = null;
    let promoted = false;
    const transitionHasVideo = () =>
      (next?.remoteStream?.getVideoTracks?.() || []).length > 0;
    const promote = () => {
      if (promoted || this._transitionWebrtc !== next || !transitionHasVideo()) {
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
      // After previous.close() has released the main element, move next's
      // client-side gain/muting onto it, so PCMU gain plays once (via Web
      // Audio) instead of doubling with the element's direct output.
      next.retargetMedia(this._videoEl);
      onPromoted();
      this._updateState();
    };

    next = this._createWebrtcClient({
      onClosed: (reason) => {
        if (this._transitionWebrtc === next) {
          this._transitionWebrtc = null;
          if (this._transitionVideoEl) {
            this._transitionVideoEl.removeEventListener("loadeddata", promote);
            this._transitionVideoEl.removeEventListener("playing", promote);
            this._transitionVideoEl.srcObject = null;
          }
          this._error = reason || "closed";
          this._scheduleUpdate();
          return;
        }
        this._handleWebrtcClosed(reason);
      },
      onTrack: () => {
        promote();
        this._scheduleUpdate();
      },
    });
    this._transitionWebrtc = next;

    this._transitionVideoEl.addEventListener("loadeddata", promote);
    this._transitionVideoEl.addEventListener("playing", promote);
    try {
      await next.start({
        microphoneStream,
        receiveAudio,
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
      this._showTemporaryNotice(this._label("microphone_required"));
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
      this._showTemporaryNotice(this._label("microphone_stream_only"));
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

    this._lifecycle.clearPeer(clearStatus);
    if (this._videoEl && !options.keepMediaElement) {
      this._videoEl.srcObject = null;
    }
    if (this._audioEl && !options.keepMediaElement) {
      this._audioEl.srcObject = null;
    }
    if (this._transitionVideoEl) {
      this._transitionVideoEl.srcObject = null;
    }
    this._clearNotice();
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
    if (this._lifecycle.shouldSuppressPreviewOnClose(reason)) {
      this._lifecycle.ringPreviewSuppressed = true;
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
    const entityId = this._resolvedCameraEntityId();
    return this._cameraEntityState || this._hass?.states?.[entityId];
  }

  _syncCameraEntityFromHass() {
    const entityId = this._resolvedCameraEntityId();
    const entity = this._hass?.states?.[entityId];
    if (entity) {
      this._cameraEntityState = entity;
    }
  }

  _ensureStateSubscription() {
    const entityId = this._resolvedCameraEntityId();
    const connection = this._hass?.connection;
    const subscribeEvents = connection?.subscribeEvents;
    if (
      this._stateSubscriptionConnection === connection
      && this._stateSubscriptionEntityId === entityId
    ) {
      return;
    }
    this._clearStateSubscription();
    this._stateSubscriptionConnection = connection || null;
    this._stateSubscriptionEntityId = entityId || "";
    if (!entityId || typeof subscribeEvents !== "function") {
      return;
    }

    const token = ++this._stateSubscriptionToken;
    let unsubscribePromise;
    try {
      unsubscribePromise = Promise.resolve(subscribeEvents.call(
        connection,
        (event) => this._handleStateChanged(event),
        "state_changed",
      ));
    } catch (err) {
      console.warn("C300X state subscription failed", err);
      return;
    }
    unsubscribePromise.then((unsubscribe) => {
      if (
        token !== this._stateSubscriptionToken
        || this._stateSubscriptionConnection !== connection
        || this._stateSubscriptionEntityId !== entityId
      ) {
        if (typeof unsubscribe === "function") {
          unsubscribe();
        }
        return;
      }
      this._unsubscribeStateEvents = unsubscribe;
    }).catch((err) => {
      console.warn("C300X state subscription failed", err);
    });
  }

  _clearStateSubscription() {
    const unsubscribe = this._unsubscribeStateEvents;
    this._unsubscribeStateEvents = null;
    this._stateSubscriptionConnection = null;
    this._stateSubscriptionEntityId = "";
    this._stateSubscriptionToken += 1;
    if (typeof unsubscribe === "function") {
      unsubscribe();
    }
  }

  _handleStateChanged(event) {
    const data = event?.data || {};
    if (data.entity_id !== this._stateSubscriptionEntityId) {
      return;
    }
    this._cameraEntityState = data.new_state || null;
    this._scheduleUpdate();
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
    const visible = !!entity && this._config?.show_media_readiness !== false;
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
    this._readinessTextEl.textContent = this._readinessLabel(entity, normalized);
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

  _showTemporaryNotice(notice) {
    this._clearNoticeTimer();
    this._notice = notice;
    // notice is part of the render signature, so the coalesced path renders it.
    this._scheduleUpdate();
    this._noticeTimer = window.setTimeout(() => {
      if (this._notice === notice) {
        this._notice = "";
        this._scheduleUpdate();
      }
      this._noticeTimer = null;
    }, C300X_NOTICE_TIMEOUT_MS);
  }

  _clearNotice() {
    this._clearNoticeTimer();
    this._notice = "";
  }

  _clearNoticeTimer() {
    if (!this._noticeTimer) {
      return;
    }
    window.clearTimeout(this._noticeTimer);
    this._noticeTimer = null;
  }

  _doorstationView() {
    return c300xCardViewModel({
      cameraEntity: this._cameraEntity(),
      homeCallMode: false,
      active: this._lifecycle.doorstationActive({
        homeCallMode: false,
        hasLocalMedia: this._webrtc.running || !!this._webrtc.remoteStream,
      }),
      startingCall: this._lifecycle.startingCall,
      doorbellAnswered: this._lifecycle.doorbellAnswered,
      previewStarting: this._lifecycle.previewStarting,
      ringPreviewActive: this._lifecycle.ringPreviewActive,
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

  _readinessLabel(entity, normalized) {
    const attributes = entity?.attributes || {};
    const failedChecks = Array.isArray(attributes.failed_checks)
      ? attributes.failed_checks
      : [];
    if (
      normalized === "blocked"
      && attributes.forwarding_homeassistant === false
      && failedChecks.includes("forwarding_homeassistant")
    ) {
      return this._label("media_forwarding_required");
    }
    return this._label(`media_${normalized}`);
  }

  _openRepairs() {
    globalThis.history?.pushState?.(null, "", "/config/repairs");
    globalThis.dispatchEvent?.(new Event("location-changed"));
  }
}

if (!customElements.get(C300X_CARD_TAG)) {
  customElements.define(C300X_CARD_TAG, C300XDoorbellCallCard);
}

window.customCards = window.customCards || [];
window.customCards = window.customCards.filter((card) => card.type !== C300X_CARD_TAG);
window.customCards.push({
  type: C300X_CARD_TAG,
  name: "C300X Doorbell Call Card",
  preview: false,
  description: C300X_TRANSLATIONS.en.card_description,
  documentationURL: C300X_DOCUMENTATION_URL,
  getEntitySuggestion: (hass, entityId) => C300XDoorbellCallCard.getEntitySuggestion(hass, entityId),
});
