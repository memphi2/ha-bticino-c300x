import assert from "node:assert/strict";
import test from "node:test";

import { C300XCardLifecycleState } from "../../custom_components/bticino_c300x/frontend/c300x-card-lifecycle.js";

test("lifecycle resets preview suppression only for a new ring", () => {
  const lifecycle = new C300XCardLifecycleState();
  lifecycle.ringPreviewSuppressed = true;
  lifecycle.commitMediaState("idle");

  assert.deepEqual(lifecycle.evaluateMediaState("ring_pending"), {
    ringLifecycleActive: true,
    shouldCloseLocalRingPeer: false,
  });
  assert.equal(lifecycle.ringPreviewSuppressed, false);
});

test("lifecycle asks the card to close stale local ring media after ring end", () => {
  const lifecycle = new C300XCardLifecycleState();
  lifecycle.ringPreviewActive = true;
  lifecycle.ringPreviewStarted = true;
  lifecycle.passiveAnsweredPreviewStarted = true;
  lifecycle.commitMediaState("ring_active");

  assert.deepEqual(lifecycle.evaluateMediaState("idle"), {
    ringLifecycleActive: false,
    shouldCloseLocalRingPeer: true,
  });
  assert.equal(lifecycle.ringPreviewStarted, false);
  assert.equal(lifecycle.passiveAnsweredPreviewStarted, false);
});

test("lifecycle blocks duplicate preview starts", () => {
  const lifecycle = new C300XCardLifecycleState();
  assert.equal(
    lifecycle.canStartDoorbellPreview({
      webrtcRunning: false,
      transitionActive: false,
    }),
    true,
  );

  lifecycle.ringPreviewStarted = true;
  assert.equal(
    lifecycle.canStartDoorbellPreview({
      webrtcRunning: false,
      transitionActive: false,
    }),
    false,
  );
});

test("lifecycle allows passive preview transition only after a remote answer", () => {
  const lifecycle = new C300XCardLifecycleState();
  lifecycle.ringPreviewActive = true;

  assert.equal(
    lifecycle.shouldStartPassiveAnsweredPreview({
      mediaState: "ring_active",
      webrtcRunning: true,
      transitionActive: false,
    }),
    true,
  );

  lifecycle.passiveAnsweredPreviewStarted = true;
  assert.equal(
    lifecycle.shouldStartPassiveAnsweredPreview({
      mediaState: "ring_active",
      webrtcRunning: true,
      transitionActive: false,
    }),
    false,
  );
});

test("lifecycle continues passive preview after source switch closed the old preview", () => {
  const lifecycle = new C300XCardLifecycleState();
  lifecycle.ringPreviewStarted = true;

  assert.equal(lifecycle.shouldSuppressPreviewOnClose("closed"), false);
  assert.equal(
    lifecycle.shouldStartPassiveAnsweredPreview({
      mediaState: "ring_active",
      webrtcRunning: false,
      transitionActive: false,
    }),
    true,
  );
});

test("lifecycle suppresses passive preview after explicit backend stop", () => {
  const lifecycle = new C300XCardLifecycleState();
  lifecycle.ringPreviewStarted = true;

  assert.equal(lifecycle.shouldSuppressPreviewOnClose("doorbell_video_stopped"), true);
  lifecycle.ringPreviewSuppressed = true;
  assert.equal(
    lifecycle.shouldStartPassiveAnsweredPreview({
      mediaState: "ring_active",
      webrtcRunning: false,
      transitionActive: false,
    }),
    false,
  );
});

test("lifecycle clearPeer keeps suppression but clears local session state", () => {
  const lifecycle = new C300XCardLifecycleState();
  lifecycle.ringPreviewSuppressed = true;
  lifecycle.ringPreviewStarted = true;
  lifecycle.ringPreviewActive = true;
  lifecycle.activeHomeCallSession = true;
  lifecycle.passiveAnsweredPreviewStarted = true;
  lifecycle.doorbellAnswered = true;

  lifecycle.clearPeer(true);

  assert.equal(lifecycle.ringPreviewSuppressed, true);
  assert.equal(lifecycle.ringPreviewStarted, false);
  assert.equal(lifecycle.ringPreviewActive, false);
  assert.equal(lifecycle.activeHomeCallSession, false);
  assert.equal(lifecycle.passiveAnsweredPreviewStarted, false);
  assert.equal(lifecycle.doorbellAnswered, false);
});
