import {
  c300xRingLifecycleActive,
  c300xShouldResetRingPreviewSuppression,
} from "./c300x-ring-preview-state.js?v=42fb1c2a81e69f09";

const C300X_EXPLICIT_RING_PREVIEW_STOP_REASONS = new Set([
  "agent_cpu_watchdog",
  "doorbell_media_closed",
  "doorbell_video_stopped",
]);

export class C300XCardLifecycleState {
  constructor() {
    this.startingCall = false;
    this.previewStarting = false;
    this.ringPreviewStarted = false;
    this.ringPreviewSuppressed = false;
    this.passiveAnsweredPreviewStarted = false;
    this.lastMediaState = "";
    this.answeringDoorbell = false;
    this.hangupInProgress = false;
    this.ringPreviewActive = false;
    this.doorbellAnswered = false;
    this.activeHomeCallSession = false;
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

  shouldStartPassiveAnsweredPreview({ mediaState, webrtcRunning, transitionActive, answerLaunch }) {
    const hadPreview = this.ringPreviewActive || this.ringPreviewStarted;
    // A card that is answering itself gets the stream with its microphone;
    // the receive-only preview is for a call another client answered.
    return (
      mediaState === "ring_active"
      && hadPreview
      && !this.doorbellAnswered
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
    this.doorbellAnswered = false;
  }

  shouldSuppressPreviewOnClose(reason) {
    return C300X_EXPLICIT_RING_PREVIEW_STOP_REASONS.has(reason);
  }
}
