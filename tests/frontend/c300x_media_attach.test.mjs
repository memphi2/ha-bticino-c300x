import assert from "node:assert/strict";
import test from "node:test";

import { C300XMediaAttachment } from "../../custom_components/bticino_c300x/frontend/c300x-media-attach.js";

test("media attachment assigns a stream only once", () => {
  const stream = { id: "remote-stream" };
  const mediaElement = {
    srcObject: null,
    playCalls: 0,
    play() {
      this.playCalls += 1;
      return Promise.resolve();
    },
  };
  const attachment = new C300XMediaAttachment(mediaElement, stream);

  attachment.attach();
  attachment.attach();

  assert.equal(attachment.attached, true);
  assert.equal(mediaElement.srcObject, stream);
  assert.equal(mediaElement.playCalls, 0);
});

test("media attachment prepares playback without throwing on autoplay rejection", () => {
  const stream = { id: "remote-stream" };
  const mediaElement = {
    srcObject: null,
    playCalls: 0,
    play() {
      this.playCalls += 1;
      return Promise.reject(new Error("autoplay blocked"));
    },
  };
  const attachment = new C300XMediaAttachment(mediaElement, stream);

  attachment.play();

  assert.equal(mediaElement.srcObject, stream);
  assert.equal(mediaElement.autoplay, true);
  assert.equal(mediaElement.muted, false);
  assert.equal(mediaElement.volume, 1);
  assert.equal(mediaElement.playCalls, 1);
});

function fakeMediaElement() {
  return {
    srcObject: null,
    muted: false,
    play() {
      return Promise.resolve();
    },
  };
}

test("listening volume and mute follow playback and retargeting, without Web Audio", async () => {
  const previousWindow = global.window;
  let contexts = 0;
  global.window = { AudioContext: class { constructor() { contexts += 1; } } };
  try {
    const playback = { volume: 0.35, muted: true };
    const element = fakeMediaElement();
    const attachment = new C300XMediaAttachment(
      element,
      { id: "remote-stream", getAudioTracks: () => [{ kind: "audio" }] },
      { getPlayback: () => playback },
    );
    attachment.play();
    assert.equal(element.volume, 0.35);
    assert.equal(element.muted, true);
    playback.muted = false;
    attachment.refreshPlayback();
    assert.equal(element.muted, false, "the element plays the stream itself");
    const target = fakeMediaElement();
    playback.muted = true;
    attachment.retarget(target);
    assert.equal(target.volume, 0.35);
    assert.equal(target.muted, true);
    assert.equal(element.muted, false, "the old element is released");
    attachment.detach();
    assert.equal(contexts, 0, "the agent applies the level; the card adds no gain stage");
  } finally {
    global.window = previousWindow;
  }
});

test("listening volume is bounded", () => {
  const playback = { volume: -5, muted: false };
  const element = fakeMediaElement();
  const attachment = new C300XMediaAttachment(element, { getAudioTracks: () => [] }, {
    getPlayback: () => playback,
  });
  attachment.play();
  assert.equal(element.volume, 0);
  playback.volume = 5;
  attachment.refreshPlayback();
  assert.equal(element.volume, 1);
  playback.volume = Number.NaN;
  attachment.refreshPlayback();
  assert.equal(element.volume, 1);
});

function autoplayElement(refusals) {
  return {
    srcObject: null,
    muted: false,
    plays: [],
    play() {
      this.plays.push(this.muted);
      const refusal = refusals.shift();
      return refusal ? Promise.reject(refusal) : Promise.resolve();
    },
  };
}

const settle = () => new Promise((done) => setTimeout(done, 0));

test("sound refused at autoplay plays muted until a gesture resumes it", async () => {
  const element = autoplayElement([new DOMException("no gesture", "NotAllowedError")]);
  const blocked = [];
  const attachment = new C300XMediaAttachment(element, { getAudioTracks: () => [] }, {
    onPlaybackBlocked: (value) => blocked.push(value),
  });
  attachment.play();
  await settle();
  assert.deepEqual(element.plays, [false, true], "no muted retry");
  assert.equal(element.muted, true);
  assert.equal(attachment.playbackBlocked, true);
  assert.deepEqual(blocked, [true]);
  attachment.refreshPlayback();
  assert.equal(element.muted, true, "a volume refresh unmuted a refused element");

  attachment.resumePlayback();
  await settle();
  assert.equal(element.muted, false);
  assert.deepEqual(element.plays, [false, true, false]);
  assert.equal(attachment.playbackBlocked, false);
  assert.deepEqual(blocked, [true, false]);
  attachment.resumePlayback();
  assert.equal(element.plays.length, 3, "resume without a refusal played again");
});

test("other play failures do not ask for a tap", async () => {
  const element = autoplayElement([new DOMException("aborted", "AbortError")]);
  const attachment = new C300XMediaAttachment(element, { getAudioTracks: () => [] });
  attachment.play();
  await settle();
  assert.equal(attachment.playbackBlocked, false);
  assert.equal(element.muted, false);
  assert.deepEqual(element.plays, [false]);
});

test("a refused stream stays muted on the element it is moved to", async () => {
  const first = autoplayElement([new DOMException("no gesture", "NotAllowedError")]);
  const second = autoplayElement([new DOMException("no gesture", "NotAllowedError")]);
  const attachment = new C300XMediaAttachment(first, { getAudioTracks: () => [] });
  attachment.play();
  await settle();
  attachment.retarget(second);
  await settle();
  assert.equal(first.muted, false);
  assert.equal(second.muted, true);
  assert.deepEqual(second.plays, [true, true]);
  assert.equal(attachment.playbackBlocked, true);
});
