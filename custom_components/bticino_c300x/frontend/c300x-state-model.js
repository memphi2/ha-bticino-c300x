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

export function c300xDoorstationAction({
  cameraEntity,
  active,
  doorbellAnswered,
  previewStarting,
  ringPreviewActive,
}) {
  if (c300xIsExternalDoorstationMedia(cameraEntity)) {
    return "external_call";
  }
  const stateMachineAction = c300xStateMachineDoorstationAction(cameraEntity, active);
  if (doorbellAnswered && (!stateMachineAction || stateMachineAction === "answer")) {
    return "hang_up";
  }
  if (stateMachineAction) {
    return stateMachineAction;
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
    return "hang_up";
  }
  if (c300xIsRingCallAvailable(cameraEntity)) {
    return "hang_up";
  }
  return "stream";
}

export function c300xStateMachineDoorstationAction(cameraEntity, active) {
  if (!c300xHasMediaPrimaryAction(cameraEntity)) {
    return "";
  }
  const action = c300xMediaPrimaryAction(cameraEntity);
  if (action === "answer_ring") {
    return "answer";
  }
  if (action === "hangup" || action === "stop_stream") {
    return "hang_up";
  }
  if (action === "start_stream") {
    return active ? "hang_up" : "stream";
  }
  if (action === "wait") {
    const mediaState = c300xMediaState(cameraEntity);
    if (active) {
      return "hang_up";
    }
    if (
      mediaState === "ring_answering"
      || mediaState === "ring_active"
      || mediaState === "ring_hanging_up"
    ) {
      return "hang_up";
    }
    return "busy";
  }
  return active ? "hang_up" : "unavailable";
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
  return attributes.external_media_active === true
    || attributes.video_owner === "external_media"
    || attributes.external_owner === "external_media";
}
