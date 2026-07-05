const C300X_RING_LIFECYCLE_STATES = new Set([
  "ring_pending",
  "ring_preview_active",
  "ring_answering",
  "ring_active",
  "ring_hanging_up",
]);

export function c300xRingLifecycleActive(mediaState) {
  return C300X_RING_LIFECYCLE_STATES.has(mediaState);
}

export function c300xShouldResetRingPreviewSuppression(mediaState, previousMediaState) {
  return (
    c300xRingLifecycleActive(mediaState)
    && !!previousMediaState
    && !c300xRingLifecycleActive(previousMediaState)
  );
}
