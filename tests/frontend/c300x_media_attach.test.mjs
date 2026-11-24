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

function installAudioContextMock({ resumeState = "running", compressor = true, failSource = false } = {}) {
  const created = [];

  class MockSourceNode {
    constructor() {
      this.connections = [];
      this.disconnects = 0;
    }

    connect(node) {
      this.connections.push(node);
    }

    disconnect() {
      this.disconnects += 1;
    }
  }

  class MockAudioContext {
    constructor() {
      created.push(this);
      this.destination = { id: "destination" };
      this.resumes = 0;
      this.closes = 0;
      this.state = "suspended";
      this.source = new MockSourceNode();
      this.gain = { gain: { value: 1 }, connectedTo: null };
      this.output = { gain: { value: 1 }, connectedTo: null };
      this.gainCount = 0;
      this.limiter = {
        threshold: { value: 0 },
        knee: { value: 0 },
        ratio: { value: 1 },
        attack: { value: 0 },
        release: { value: 0 },
        connectedTo: null,
      };
      if (!compressor) {
        // Simulate a browser without DynamicsCompressorNode.
        this.createDynamicsCompressor = undefined;
      }
    }

    createMediaStreamSource(stream) {
      if (failSource) throw new Error("Audio source unavailable");
      this.stream = stream;
      return this.source;
    }

    createGain() {
      const gain = this.gainCount++ === 0 ? this.gain : this.output;
      gain.connect = (node) => {
        gain.connectedTo = node;
      };
      return gain;
    }

    createDynamicsCompressor() {
      const limiter = this.limiter;
      limiter.connect = (node) => {
        limiter.connectedTo = node;
      };
      return limiter;
    }

    resume() {
      this.resumes += 1;
      this.state = resumeState;
      return Promise.resolve();
    }

    close() {
      this.closes += 1;
      return Promise.resolve();
    }
  }

  const previousWindow = global.window;
  global.window = { AudioContext: MockAudioContext };
  return {
    created,
    restore() {
      global.window = previousWindow;
    },
  };
}

function fakeMediaElement() {
  return {
    srcObject: null,
    muted: false,
    play() {
      return Promise.resolve();
    },
  };
}

function streamWithAudio() {
  return { id: "remote-stream", getAudioTracks: () => [{ kind: "audio" }] };
}

test("listening volume and mute survive play, gain changes and retargeting", async () => {
  const audio = installAudioContextMock();
  try {
    let gain = 0;
    const playback = { volume: 0.35, muted: true };
    const element = fakeMediaElement();
    const attachment = new C300XMediaAttachment(element, streamWithAudio(), {
      getGainDb: () => gain, getPlayback: () => playback,
    });
    await attachment.play();
    assert.equal(element.volume, 0.35);
    assert.equal(element.muted, true);
    assert.equal(audio.created.length, 0);
    gain = 12;
    await attachment.refreshGain();
    const ctx = audio.created[0];
    assert.equal(ctx.output.gain.value, 0);
    playback.muted = false;
    attachment.refreshPlayback();
    assert.equal(ctx.output.gain.value, 0.35);
    assert.equal(element.muted, true, "Web Audio must not double the direct sound");
    assert.equal(ctx.gain.gain.value, Math.pow(10, 12 / 20));
    const target = fakeMediaElement();
    await attachment.retarget(target);
    assert.equal(target.volume, 0.35);
    assert.equal(target.muted, true);
    playback.muted = true;
    gain = 0;
    await attachment.refreshGain();
    assert.equal(target.muted, true, "Fallback must preserve intentional silence");
    await attachment.play();
    assert.equal(target.muted, true);
    attachment.detach();
  } finally { audio.restore(); }
});

test("autoplay gain fallback respects mute and bounded listening volume", async () => {
  const audio = installAudioContextMock({ resumeState: "suspended" });
  try {
    const playback = { volume: -5, muted: true };
    const element = fakeMediaElement();
    const attachment = new C300XMediaAttachment(element, streamWithAudio(), {
      getGainDb: () => 6, getPlayback: () => playback,
    });
    await attachment.play();
    assert.equal(element.volume, 0);
    assert.equal(element.muted, true);
    playback.volume = 5;
    attachment.refreshPlayback();
    assert.equal(element.volume, 1);
    attachment.detach();
  } finally { audio.restore(); }
});

test("gain of 0 dB stays passthrough: no Web Audio graph, element audible", () => {
  const audio = installAudioContextMock();
  try {
    const stream = { id: "remote-stream" };
    const mediaElement = fakeMediaElement();
    const attachment = new C300XMediaAttachment(mediaElement, stream, {
      getGainDb: () => 0,
    });

    attachment.play();

    assert.equal(audio.created.length, 0);
    assert.equal(mediaElement.muted, false);
  } finally {
    audio.restore();
  }
});

test("failed audio graph creation closes each partial context and keeps passthrough", async () => {
  const audio = installAudioContextMock({ failSource: true });
  try {
    const mediaElement = fakeMediaElement();
    const attachment = new C300XMediaAttachment(mediaElement, streamWithAudio(), {
      getGainDb: () => 6,
    });
    await attachment.play();
    await attachment.refreshGain();
    attachment.detach();

    assert.equal(audio.created.length, 2);
    assert.deepEqual(audio.created.map((context) => context.closes), [1, 1]);
    assert.equal(mediaElement.muted, false);
  } finally {
    audio.restore();
  }
});

test("non-zero gain routes through a GainNode and mutes the element", async () => {
  const audio = installAudioContextMock();
  try {
    const stream = streamWithAudio();
    const mediaElement = fakeMediaElement();
    const attachment = new C300XMediaAttachment(mediaElement, stream, {
      getGainDb: () => 6,
    });

    await attachment.play();

    assert.equal(audio.created.length, 1);
    const ctx = audio.created[0];
    assert.equal(ctx.stream, stream);
    assert.equal(ctx.source.connections[0], ctx.gain);
    // gain -> soft limiter -> destination
    assert.equal(ctx.gain.connectedTo, ctx.limiter);
    assert.equal(ctx.limiter.connectedTo, ctx.output);
    assert.equal(ctx.output.connectedTo, ctx.destination);
    assert.ok(ctx.limiter.ratio.value > 1);
    assert.ok(Math.abs(ctx.gain.gain.value - Math.pow(10, 6 / 20)) < 1e-9);
    assert.equal(mediaElement.muted, true);
  } finally {
    audio.restore();
  }
});

test("detaching while the AudioContext resumes leaves nothing to engage and does not throw", async () => {
  const audio = installAudioContextMock();
  try {
    const mediaElement = fakeMediaElement();
    const attachment = new C300XMediaAttachment(mediaElement, streamWithAudio(), {
      getGainDb: () => 6,
    });
    const playing = attachment.play();
    attachment.detach();

    await playing;

    assert.equal(mediaElement.muted, false);
  } finally {
    audio.restore();
  }
});

test("the owner hears when the gain stage engages and when it falls back", async () => {
  const audio = installAudioContextMock();
  try {
    let gainDb = 6, changes = 0;
    const attachment = new C300XMediaAttachment(fakeMediaElement(), streamWithAudio(), {
      getGainDb: () => gainDb,
      onGainChanged: () => { changes += 1; },
    });
    await attachment.play();
    assert.equal(attachment.gainEngaged, true);
    assert.equal(changes, 1, "engaging after the asynchronous resume is reported");
    await attachment.refreshGain();
    assert.equal(changes, 1, "an unchanged state is not reported again");
    gainDb = 0;
    await attachment.refreshGain();
    assert.equal(attachment.gainEngaged, false);
    assert.equal(changes, 2, "falling back to passthrough is reported");
  } finally {
    audio.restore();
  }
});

test("without a DynamicsCompressor the gain connects straight to destination", async () => {
  // Graceful fallback: the makeup gain must still work on browsers that lack
  // DynamicsCompressorNode; only the anti-clip limiter is skipped.
  const audio = installAudioContextMock({ compressor: false });
  try {
    const stream = streamWithAudio();
    const mediaElement = fakeMediaElement();
    const attachment = new C300XMediaAttachment(mediaElement, stream, {
      getGainDb: () => 6,
    });

    await attachment.play();

    const ctx = audio.created[0];
    assert.equal(ctx.source.connections[0], ctx.gain);
    assert.equal(ctx.gain.connectedTo, ctx.output);
    assert.equal(ctx.output.connectedTo, ctx.destination);
    assert.equal(ctx.limiter.connectedTo, null);
    assert.equal(mediaElement.muted, true);
  } finally {
    audio.restore();
  }
});

test("a suspended AudioContext falls back to passthrough (audible, not muted)", async () => {
  // No user gesture: resume() cannot reach 'running'. The element must stay
  // unmuted so audio is audible, instead of muting to a silent graph.
  const audio = installAudioContextMock({ resumeState: "suspended" });
  try {
    const stream = streamWithAudio();
    const mediaElement = fakeMediaElement();
    const attachment = new C300XMediaAttachment(mediaElement, stream, {
      getGainDb: () => 6,
    });

    await attachment.play();

    assert.equal(audio.created.length, 1);
    assert.equal(mediaElement.muted, false);
  } finally {
    audio.restore();
  }
});

test("returning to 0 dB disengages the gain and unmutes the element", async () => {
  const audio = installAudioContextMock();
  try {
    const stream = streamWithAudio();
    const mediaElement = fakeMediaElement();
    let gainDb = 6;
    const attachment = new C300XMediaAttachment(mediaElement, stream, {
      getGainDb: () => gainDb,
    });

    await attachment.play();
    assert.equal(mediaElement.muted, true);

    gainDb = 0;
    await attachment.refreshGain();

    assert.equal(mediaElement.muted, false);
    assert.equal(audio.created[0].source.disconnects >= 1, true);
  } finally {
    audio.restore();
  }
});

test("no Web Audio graph is built before the stream carries an audio track", async () => {
  const audio = installAudioContextMock();
  try {
    const stream = { id: "remote-stream", getAudioTracks: () => [] };
    const mediaElement = fakeMediaElement();
    const attachment = new C300XMediaAttachment(mediaElement, stream, {
      getGainDb: () => 6,
    });

    await attachment.play();

    // gain wanted, but no track yet -> stay passthrough instead of binding a
    // permanently silent MediaStreamAudioSourceNode.
    assert.equal(audio.created.length, 0);
    assert.equal(mediaElement.muted, false);
  } finally {
    audio.restore();
  }
});

test("retarget moves the gain to the new element and releases the old one", async () => {
  const audio = installAudioContextMock();
  try {
    const stream = streamWithAudio();
    const firstElement = fakeMediaElement();
    const attachment = new C300XMediaAttachment(firstElement, stream, {
      getGainDb: () => 6,
    });

    await attachment.play();
    assert.equal(firstElement.muted, true);

    const secondElement = fakeMediaElement();
    await attachment.retarget(secondElement);

    // the graph is reused (not rebuilt); muting follows the rendering element
    assert.equal(audio.created.length, 1);
    assert.equal(firstElement.muted, false);
    assert.equal(secondElement.muted, true);
  } finally {
    audio.restore();
  }
});

test("retarget mutes the new element synchronously (no double-audio window)", async () => {
  const audio = installAudioContextMock();
  try {
    const stream = streamWithAudio();
    const firstElement = fakeMediaElement();
    const attachment = new C300XMediaAttachment(firstElement, stream, {
      getGainDb: () => 6,
    });
    await attachment.play();

    const secondElement = fakeMediaElement();
    const pending = attachment.retarget(secondElement); // deliberately not awaited

    // The new element must be muted before the async resume resolves, so it
    // never renders the stream directly while the graph also outputs it.
    assert.equal(secondElement.muted, true);
    assert.equal(firstElement.muted, false);
    await pending;
  } finally {
    audio.restore();
  }
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
