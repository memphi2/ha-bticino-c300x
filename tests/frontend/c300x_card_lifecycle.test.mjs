import assert from "node:assert/strict";
import test from "node:test";

import {
  C300XCardLifecycleState,
  c300xAnsweredRingKey,
} from "../../custom_components/bticino_c300x/frontend/c300x-card-lifecycle.js";

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

test("lifecycle keeps the passive preview away from a card that is answering", () => {
  const args = { mediaState: "ring_active", webrtcRunning: true, transitionActive: false };
  const lifecycle = new C300XCardLifecycleState();
  lifecycle.ringPreviewActive = true;

  lifecycle.answeringDoorbell = true;
  assert.equal(lifecycle.shouldStartPassiveAnsweredPreview(args), false);
  lifecycle.answeringDoorbell = false;
  assert.equal(lifecycle.shouldStartPassiveAnsweredPreview({ ...args, answerLaunch: true }), false);
  assert.equal(lifecycle.shouldStartPassiveAnsweredPreview(args), true);
});

const ring = (media_state, last_changed) => ({ last_changed, attributes: { media_state } });

test("the answered ring key is the same for state objects and state events", () => {
  const event = c300xAnsweredRingKey("camera.door", ring("ring_active", "2026-11-24T10:00:00.123456+00:00"));
  const state = c300xAnsweredRingKey("camera.door", ring("ring_active", "2026-11-24T10:00:00.123Z"));
  assert.equal(event, state);
  assert.notEqual(event, c300xAnsweredRingKey("camera.door", ring("ring_active", "2026-11-24T10:05:00Z")));
  assert.equal(c300xAnsweredRingKey("camera.door", ring("idle", "2026-11-24T10:00:00Z")), "");
  assert.equal(c300xAnsweredRingKey("", ring("ring_active", "2026-11-24T10:00:00Z")), "");
});

test("an answered ring outlives its peer until the ring ends", () => {
  const lifecycle = new C300XCardLifecycleState();
  assert.equal(lifecycle.rememberAnsweredRing("camera.door@1"), true);
  lifecycle.doorbellAnswered = true;
  lifecycle.clearPeer(false);
  lifecycle.clearPeer(true);
  assert.equal(lifecycle.doorbellAnswered, false);
  assert.equal(lifecycle.followAnsweredRing("camera.door@1"), true);
  assert.equal(lifecycle.canReconnectAnsweredRing(), true);
  lifecycle.answeredRingReconnected = true;
  assert.equal(lifecycle.canReconnectAnsweredRing(), false);
  lifecycle.answeredRingReconnected = false;
  lifecycle.answeredRingHangup = true;
  assert.equal(lifecycle.canReconnectAnsweredRing(), false);
  lifecycle.forgetAnsweredRing();
  assert.equal(lifecycle.followAnsweredRing("camera.door@1"), false);
});

test("a changed ring key is followed only while the card watched the ring", () => {
  const lifecycle = new C300XCardLifecycleState();
  lifecycle.rememberAnsweredRing("camera.door@1");
  assert.equal(lifecycle.followAnsweredRing("camera.door@2"), true);
  assert.equal(lifecycle.answeredRingKey, "camera.door@2");
  lifecycle.answeredRingWatched = false;
  assert.equal(lifecycle.followAnsweredRing("camera.door@3"), false);
  assert.equal(lifecycle.followAnsweredRing("camera.door@2"), true);
  assert.equal(lifecycle.answeredRingWatched, true);
});

test("the receive-only preview is not started for a ring this browser answered", () => {
  const lifecycle = new C300XCardLifecycleState();
  lifecycle.ringPreviewStarted = true;
  const request = { mediaState: "ring_active", webrtcRunning: false, transitionActive: false, answerLaunch: false };
  assert.equal(lifecycle.shouldStartPassiveAnsweredPreview(request), true);
  assert.equal(lifecycle.shouldStartPassiveAnsweredPreview({ ...request, answeredHere: true }), false);
});
