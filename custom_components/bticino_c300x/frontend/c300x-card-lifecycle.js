import {
  c300xRingLifecycleActive,
  c300xShouldResetRingPreviewSuppression,
} from "./c300x-ring-preview-state.js?v=edc306f6c037576f";

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

  shouldStartPassiveAnsweredPreview({ mediaState, webrtcRunning, transitionActive }) {
    return (
      mediaState === "ring_active"
      && this.ringPreviewActive
      && !this.doorbellAnswered
      && !this.passiveAnsweredPreviewStarted
      && webrtcRunning
      && !transitionActive
    );
  }

  clearPeer(clearStatus) {
    this.ringPreviewActive = false;
    this.activeHomeCallSession = false;
    this.passiveAnsweredPreviewStarted = false;
    if (clearStatus) {
      this.ringPreviewStarted = false;
    }
    this.doorbellAnswered = false;
  }

  shouldSuppressPreviewOnClose(reason) {
    return reason === "ring_call_answered"
      || (this.ringPreviewActive && !this.doorbellAnswered);
  }
}
