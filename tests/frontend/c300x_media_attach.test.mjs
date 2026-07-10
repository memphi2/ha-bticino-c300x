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

function installAudioContextMock({ resumeState = "running", compressor = true } = {}) {
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
      this.stream = stream;
      return this.source;
    }

    createGain() {
      const gain = this.gain;
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
    assert.equal(ctx.limiter.connectedTo, ctx.destination);
    assert.ok(ctx.limiter.ratio.value > 1);
    assert.ok(Math.abs(ctx.gain.gain.value - Math.pow(10, 6 / 20)) < 1e-9);
    assert.equal(mediaElement.muted, true);
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
    assert.equal(ctx.gain.connectedTo, ctx.destination);
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
