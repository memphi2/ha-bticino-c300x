import {
  c300xRingLifecycleActive,
  c300xShouldResetRingPreviewSuppression,
} from "./c300x-ring-preview-state.js?v=512334210b48e785";

const C300X_EXPLICIT_RING_PREVIEW_STOP_REASONS = new Set([
  "agent_cpu_watchdog",
  "doorbell_media_closed",
  "doorbell_video_stopped",
]);

// The ring a browser answered, so it keeps the hang-up after its peer is gone.
// Seconds only: HA sends the same instant with other precision in states and events.
export function c300xAnsweredRingKey(entityId, entity) {
  if (!entityId || !c300xRingLifecycleActive(entity?.attributes?.media_state)) return "";
  const since = Date.parse(String(entity?.last_changed || "").replace(/\.\d+/, ""));
  return `${entityId}@${Number.isFinite(since) ? Math.floor(since / 1000) : ""}`;
}

export class C300XCardLifecycleState {
  constructor() {
    this.startingCall = false;
    this.previewStarting = false;
    this.ringPreviewStarted = false;
    this.ringPreviewSuppressed = false;
    this.passiveAnsweredPreviewStarted = false;
    this.lastMediaState = "";
    this.lastObservedMediaState = "";
    this.answeringDoorbell = false;
    this.hangupInProgress = false;
    this.ringPreviewActive = false;
    this.doorbellAnswered = false;
    this.activeHomeCallSession = false;
    this.answeredRingKey = "";
    this.answeredRingWatched = false;
    this.answeredRingHangup = false;
    this.answeredRingReconnected = false;
  }

  rememberAnsweredRing(key) {
    if (!key) return false;
    if (key !== this.answeredRingKey) {
      this.answeredRingHangup = false;
      this.answeredRingReconnected = false;
    }
    this.answeredRingKey = key;
    this.answeredRingWatched = true;
    return true;
  }

  followAnsweredRing(key) {
    if (!key || !this.answeredRingKey) return false;
    if (key !== this.answeredRingKey) {
      // A changed camera state is the same ring only if the card saw no end
      // in between; after a detach it may be the next ring.
      if (!this.answeredRingWatched) return false;
      this.answeredRingKey = key;
    }
    this.answeredRingWatched = true;
    return true;
  }

  forgetAnsweredRing() {
    this.answeredRingKey = "";
    this.answeredRingWatched = false;
    this.answeredRingHangup = false;
    this.answeredRingReconnected = false;
  }

  canReconnectAnsweredRing() {
    return !!this.answeredRingKey
      && !this.answeredRingHangup
      && !this.answeredRingReconnected
      && !this.doorbellAnswered
      && !this.answeringDoorbell
      && !this.hangupInProgress
      && !this.previewStarting
      && !this.ringPreviewSuppressed;
  }

  evaluateMediaState(mediaState) {
    const previousMediaState = this.lastMediaState;
    const ringLifecycleActive = c300xRingLifecycleActive(mediaState);
    if (c300xShouldResetRingPreviewSuppression(mediaState, previousMediaState)) {
      this.ringPreviewSuppressed = false;
    }
    if (!ringLifecycleActive) {
      this.ringPreviewStarted = false;
      this.passiveAnsweredPreviewStarted = false;
    }
    return {
      ringLifecycleActive,
      shouldCloseLocalRingPeer: !ringLifecycleActive
        && (this.ringPreviewActive || this.doorbellAnswered),
    };
  }

  commitMediaState(mediaState) {
    this.lastMediaState = mediaState;
  }

  observeRingEnd(mediaState, notificationAnswerStarting) {
    const wasRing = c300xRingLifecycleActive(this.lastObservedMediaState);
    if (mediaState) this.lastObservedMediaState = mediaState;
    return wasRing && !!mediaState && !c300xRingLifecycleActive(mediaState)
      && (this.answeringDoorbell || this.previewStarting || notificationAnswerStarting);
  }

  homeSessionActive(hasLocalMedia) {
    return this.activeHomeCallSession && (hasLocalMedia || this.startingCall);
  }

  doorstationActive({ homeCallMode, hasLocalMedia }) {
    return !homeCallMode && !this.activeHomeCallSession && hasLocalMedia;
  }

  canStartDoorbellPreview({ webrtcRunning, transitionActive }) {
    return !(
      webrtcRunning
      || transitionActive
      || this.previewStarting
      || this.ringPreviewStarted
      || this.ringPreviewSuppressed
      || this.answeringDoorbell
      || this.doorbellAnswered
    );
  }

  shouldStartPassiveAnsweredPreview({
    mediaState, webrtcRunning, transitionActive, answerLaunch, answeredHere = false,
  }) {
    const hadPreview = this.ringPreviewActive || this.ringPreviewStarted;
    // A card that is answering itself gets the stream with its microphone;
    // the receive-only preview is for a call another client answered.
    return (
      mediaState === "ring_active"
      && hadPreview
      && !this.doorbellAnswered
      && !answeredHere
      && !this.answeringDoorbell
      && !answerLaunch
      && !this.passiveAnsweredPreviewStarted
      && !this.ringPreviewSuppressed
      && !transitionActive
    );
  }

  clearPeer(clearStatus) {
    this.startingCall = false;
    this.previewStarting = false;
    this.answeringDoorbell = false;
    this.hangupInProgress = false;
    this.ringPreviewActive = false;
    this.activeHomeCallSession = false;
    this.passiveAnsweredPreviewStarted = false;
    if (clearStatus) {
      this.ringPreviewStarted = false;
    }
    // The peer is gone, the answered call is not: answeredRingKey stays.
    this.doorbellAnswered = false;
  }

  shouldSuppressPreviewOnClose(reason) {
    return C300X_EXPLICIT_RING_PREVIEW_STOP_REASONS.has(reason);
  }
}
