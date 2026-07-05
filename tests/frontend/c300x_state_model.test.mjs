import assert from "node:assert/strict";
import test from "node:test";

import {
  c300xCardViewModel,
  c300xDoorstationAction,
  c300xDoorstationStatusKey,
  c300xHomeCallStatusKey,
  c300xIsExternalDoorstationMedia,
} from "../../custom_components/bticino_c300x/frontend/c300x-state-model.js";
import {
  c300xRingLifecycleActive,
  c300xShouldResetRingPreviewSuppression,
} from "../../custom_components/bticino_c300x/frontend/c300x-ring-preview-state.js";

function entity({
  state = "idle",
  mediaState = "idle",
  primaryAction = "start_stream",
  attributes = {},
} = {}) {
  return {
    state,
    attributes: {
      media_state: mediaState,
      media_primary_action: primaryAction,
      ...attributes,
    },
  };
}

test("doorstation starts an idle stream", () => {
  assert.equal(
    c300xDoorstationAction({
      cameraEntity: entity(),
      active: false,
      doorbellAnswered: false,
      previewStarting: false,
      ringPreviewActive: false,
    }),
    "stream",
  );
  assert.equal(c300xDoorstationStatusKey(entity(), "stream", false), "idle");
});

test("ring preview is answerable but not stoppable from passive browsers", () => {
  const cameraEntity = entity({
    mediaState: "ring_preview_active",
    primaryAction: "answer_ring",
  });
  assert.equal(
    c300xDoorstationAction({
      cameraEntity,
      active: true,
      doorbellAnswered: false,
      previewStarting: false,
      ringPreviewActive: true,
    }),
    "answer",
  );

  const passiveAfterAnswer = entity({
    mediaState: "ring_active",
    primaryAction: "stop_stream",
  });
  assert.equal(
    c300xDoorstationAction({
      cameraEntity: passiveAfterAnswer,
      active: true,
      doorbellAnswered: false,
      previewStarting: false,
      ringPreviewActive: true,
    }),
    "busy",
  );
});

test("answered ring calls expose hangup only to the answering card", () => {
  const cameraEntity = entity({
    mediaState: "ring_active",
    primaryAction: "wait",
  });
  assert.equal(
    c300xDoorstationAction({
      cameraEntity,
      active: true,
      doorbellAnswered: true,
      previewStarting: false,
      ringPreviewActive: false,
    }),
    "hang_up",
  );
  assert.equal(
    c300xDoorstationAction({
      cameraEntity,
      active: true,
      doorbellAnswered: false,
      previewStarting: false,
      ringPreviewActive: true,
    }),
    "busy",
  );
});

test("external doorstation media is visible but not controllable", () => {
  const cameraEntity = entity({
    mediaState: "streaming",
    primaryAction: "unavailable",
    attributes: { external_media_active: true },
  });
  assert.equal(c300xIsExternalDoorstationMedia(cameraEntity), true);

  const view = c300xCardViewModel({
    cameraEntity,
    homeCallMode: false,
    active: false,
    startingCall: false,
    doorbellAnswered: false,
    previewStarting: false,
    ringPreviewActive: false,
  });
  assert.equal(view.action, "external_call");
  assert.equal(view.actionDisabled, true);
  assert.equal(view.actionBlocked, true);
});

test("home call model maps ringing and active states", () => {
  const ringing = entity({
    mediaState: "home_call_ringing",
    primaryAction: "wait",
  });
  const active = entity({
    mediaState: "home_call_active",
    primaryAction: "hangup",
  });

  assert.equal(c300xHomeCallStatusKey(ringing), "calling");
  assert.equal(c300xHomeCallStatusKey(active), "connected");

  const view = c300xCardViewModel({
    cameraEntity: ringing,
    homeCallMode: true,
    active: true,
    startingCall: false,
    doorbellAnswered: false,
    previewStarting: false,
    ringPreviewActive: false,
  });
  assert.equal(view.action, "hang_up");
  assert.equal(view.ringbackActive, true);
  assert.equal(view.showMedia, false);
});

test("ring preview suppression only resets at a new ring lifecycle", () => {
  assert.equal(c300xRingLifecycleActive("ring_pending"), true);
  assert.equal(c300xRingLifecycleActive("ring_hanging_up"), true);
  assert.equal(c300xRingLifecycleActive("idle"), false);
  assert.equal(c300xShouldResetRingPreviewSuppression("ring_pending", "idle"), true);
  assert.equal(
    c300xShouldResetRingPreviewSuppression("ring_preview_active", "ring_pending"),
    false,
  );
  assert.equal(c300xShouldResetRingPreviewSuppression("idle", "ring_hanging_up"), false);
});
