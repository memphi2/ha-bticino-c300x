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
