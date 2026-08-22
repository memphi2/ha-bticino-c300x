export function c300xHomeCallStatusKey(cameraEntity) {
  const mediaState = c300xMediaState(cameraEntity);
  if (mediaState === "home_call_active") {
    return "connected";
  }
  if (
    mediaState === "home_call_starting"
    || mediaState === "home_call_ringing"
    || mediaState === "home_call_stopping"
  ) {
    return "calling";
  }
  if (!cameraEntity) {
    return "unknown";
  }
  if (cameraEntity.state === "unavailable") {
    return "unavailable";
  }
  if (cameraEntity.state === "unknown") {
    return "unknown";
  }
  if (mediaState === "idle" || cameraEntity.state === "idle") {
    return "idle";
  }
  return mediaState ? "busy" : cameraEntity.state;
}

export function c300xIsHomeCallActive(cameraEntity) {
  const mediaState = c300xMediaState(cameraEntity);
  if (
    mediaState === "home_call_starting"
    || mediaState === "home_call_ringing"
    || mediaState === "home_call_active"
    || mediaState === "home_call_stopping"
  ) {
    return true;
  }
  return false;
}

export function c300xIsHomeCallConnected(cameraEntity) {
  return c300xMediaState(cameraEntity) === "home_call_active";
}

export function c300xIsHomeCallRinging(cameraEntity) {
  const mediaState = c300xMediaState(cameraEntity);
  return (
    mediaState === "home_call_starting"
    || mediaState === "home_call_ringing"
  );
}

export function c300xCardViewModel({
  cameraEntity,
  homeCallMode,
  active,
  startingCall,
  doorbellAnswered,
  previewStarting,
  ringPreviewActive,
}) {
  if (homeCallMode) {
    const callActive = c300xIsHomeCallActive(cameraEntity);
    const connected = c300xIsHomeCallConnected(cameraEntity);
    const ringing = c300xIsHomeCallRinging(cameraEntity);
    const action = callActive || startingCall ? "hang_up" : "call_home";
    return {
      action,
      actionLabelKey: action,
      actionIcon: callActive || startingCall ? "mdi:phone-hangup" : "mdi:phone",
      actionDisabled: false,
      actionActive: callActive || startingCall,
      actionDialing: callActive && !connected,
      actionAnswerable: false,
      actionBlocked: false,
      actionRecording: connected,
      secondaryKey: c300xHomeCallStatusKey(cameraEntity),
      showMedia: false,
      showEmpty: true,
      ringbackActive: ringing,
      shouldAutoPreview: false,
    };
  }

  const action = c300xDoorstationAction({
    cameraEntity,
    active,
    doorbellAnswered,
    previewStarting,
    ringPreviewActive,
  });
  const actionDisabled = (
    action === "external_call"
    || action === "busy"
    || action === "unavailable"
  );
  return {
    action,
    actionLabelKey: action,
    actionIcon: c300xDoorstationActionIcon(action, actionDisabled),
    actionDisabled,
    actionActive: active || action === "answer",
    actionDialing: action === "answer",
    actionAnswerable: action === "answer",
    actionBlocked: actionDisabled,
    actionRecording: active,
    secondaryKey: c300xDoorstationStatusKey(cameraEntity, action, active),
    showMedia: true,
    showEmpty: !active,
    ringbackActive: false,
    shouldAutoPreview: action === "answer" && c300xShouldAutoPreviewRing(cameraEntity),
  };
}

export function c300xDoorstationActionIcon(action, disabled) {
  if (action === "hang_up") {
    return "mdi:phone-hangup";
  }
  if (action === "answer") {
    return "mdi:phone-in-talk";
  }
  if (disabled) {
    return "mdi:phone-off";
  }
  return "mdi:play";
}

export function c300xDoorstationAction({
  cameraEntity,
  active,
  doorbellAnswered,
  previewStarting,
  ringPreviewActive,
}) {
  const stateMachineAction = c300xStateMachineDoorstationAction(
    cameraEntity,
    active,
    doorbellAnswered,
    ringPreviewActive,
  );
  if (doorbellAnswered && (!stateMachineAction || stateMachineAction === "answer")) {
    return "hang_up";
  }
  if (stateMachineAction) {
    if (
      stateMachineAction === "unavailable"
      && c300xIsExternalDoorstationMedia(cameraEntity)
    ) {
      return "external_call";
    }
    return stateMachineAction;
  }
  if (c300xIsExternalDoorstationMedia(cameraEntity)) {
    return "external_call";
  }
  if (c300xIsRingCallPending(cameraEntity)) {
    return "answer";
  }
  if (c300xIsRingPreviewAvailable(cameraEntity)) {
    if (previewStarting || ringPreviewActive) {
      return "answer";
    }
    return active ? "hang_up" : "answer";
  }
  if (active) {
    return !doorbellAnswered && ringPreviewActive ? "busy" : "hang_up";
  }
  if (c300xIsRingCallAvailable(cameraEntity)) {
    return doorbellAnswered ? "hang_up" : "busy";
  }
  return "stream";
}

export function c300xDoorstationStatusKey(cameraEntity, action, active) {
  const mediaState = c300xMediaState(cameraEntity);
  if (
    action === "stream"
    && !active
    && (mediaState === "idle" || cameraEntity?.state === "idle")
  ) {
    return "idle";
  }
  return action;
}

export function c300xStateMachineDoorstationAction(
  cameraEntity,
  active,
  doorbellAnswered = false,
  ringPreviewActive = false,
) {
  if (!c300xHasMediaPrimaryAction(cameraEntity)) {
    return "";
  }
  const action = c300xMediaPrimaryAction(cameraEntity);
  const passiveRingCall = !doorbellAnswered && c300xIsRingCallAvailable(cameraEntity);
  const passiveRingPreview = active && ringPreviewActive && !doorbellAnswered;
  if (action === "answer_ring") {
    return "answer";
  }
  if (action === "hangup") {
    return passiveRingCall || passiveRingPreview ? "busy" : "hang_up";
  }
  if (action === "stop_stream") {
    // On-demand media is agent-owned (the state machine only reports
    // stop_stream for owner "agent"), so any client may stop it. Requiring a
    // local stream here left a session nobody could end: close the page or
    // open the card on a second device and the only control was "busy".
    return passiveRingPreview ? "busy" : "hang_up";
  }
  if (action === "start_stream") {
    return active ? (passiveRingPreview ? "busy" : "hang_up") : "stream";
  }
  if (action === "wait") {
    const mediaState = c300xMediaState(cameraEntity);
    if (
      mediaState === "ring_answering"
      || mediaState === "ring_active"
      || mediaState === "ring_hanging_up"
    ) {
      return doorbellAnswered ? "hang_up" : "busy";
    }
    if (active) {
      return passiveRingPreview ? "busy" : "hang_up";
    }
    return "busy";
  }
  return active && !passiveRingPreview ? "hang_up" : "unavailable";
}

export function c300xHasMediaPrimaryAction(cameraEntity) {
  return typeof cameraEntity?.attributes?.media_primary_action === "string";
}

export function c300xMediaPrimaryAction(cameraEntity) {
  const value = cameraEntity?.attributes?.media_primary_action;
  return typeof value === "string" ? value : "";
}

export function c300xMediaState(cameraEntity) {
  const value = cameraEntity?.attributes?.media_state;
  return typeof value === "string" ? value : "";
}

export function c300xIsRingCallPending(cameraEntity) {
  const mediaState = c300xMediaState(cameraEntity);
  return (
    mediaState === "ring_pending"
    || mediaState === "ring_preview_active"
  ) && !c300xIsExternalDoorstationMedia(cameraEntity);
}

export function c300xShouldAutoPreviewRing(cameraEntity) {
  return c300xIsRingCallPending(cameraEntity);
}

export function c300xIsRingPreviewAvailable(cameraEntity) {
  return c300xMediaState(cameraEntity) === "ring_preview_active"
    && !c300xIsExternalDoorstationMedia(cameraEntity);
}

export function c300xIsRingCallAvailable(cameraEntity) {
  const mediaState = c300xMediaState(cameraEntity);
  return (
    mediaState === "ring_answering"
    || mediaState === "ring_active"
    || mediaState === "ring_hanging_up"
  ) && !c300xIsExternalDoorstationMedia(cameraEntity);
}

export function c300xIsExternalDoorstationMedia(cameraEntity) {
  const attributes = cameraEntity?.attributes || {};
  const mediaState = c300xMediaState(cameraEntity);
  const primaryAction = c300xMediaPrimaryAction(cameraEntity);
  if (mediaState === "idle" || primaryAction === "start_stream") {
    return false;
  }
  return attributes.external_media_active === true
    || attributes.video_owner === "external_media"
    || attributes.external_owner === "external_media";
}
