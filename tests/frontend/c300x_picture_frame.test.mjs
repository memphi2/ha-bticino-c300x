import assert from "node:assert/strict";
import test from "node:test";

import {
  c300xFollowPictureSize,
  c300xPictureRatio,
} from "../../custom_components/bticino_c300x/frontend/c300x-picture-frame.js";

const PROPERTY = "--c300x-picture-ratio";

function card() {
  const properties = new Map();
  const listeners = new Map();
  return {
    host: {
      style: {
        setProperty: (name, value) => properties.set(name, value),
        removeProperty: (name) => properties.delete(name),
      },
    },
    video: {
      videoWidth: 0,
      videoHeight: 0,
      addEventListener: (type, listener) => listeners.set(type, listener),
    },
    properties,
    plays(width, height, event = "loadedmetadata") {
      this.video.videoWidth = width;
      this.video.videoHeight = height;
      listeners.get(event)();
    },
  };
}

function browserStorage() {
  const items = new Map();
  globalThis.localStorage = {
    getItem: (key) => (items.has(key) ? items.get(key) : null),
    setItem: (key, value) => items.set(key, String(value)),
  };
  return items;
}

test("the frame keeps the factory shape until a stream tells its size", () => {
  browserStorage();
  const first = card();
  c300xFollowPictureSize(first.host, first.video, () => "camera.door");
  assert.equal(first.properties.has(PROPERTY), false);

  first.plays(0, 0);
  assert.equal(first.properties.has(PROPERTY), false);
});

test("the frame takes the shape of the whole camera picture when the stream has it", () => {
  browserStorage();
  const first = card();
  c300xFollowPictureSize(first.host, first.video, () => "camera.door");

  first.plays(720, 576);
  assert.equal(first.properties.get(PROPERTY), "1.25");

  // The device was set back to the cut-out: the size changes while it plays.
  first.plays(688, 480, "resize");
  assert.equal(first.properties.get(PROPERTY), "1.4333");
});

test("the browser remembers the shape per camera, so the card does not jump at the next stream", () => {
  const items = browserStorage();
  const first = card();
  c300xFollowPictureSize(first.host, first.video, () => "camera.door");
  first.plays(720, 576);

  const reopened = card();
  c300xFollowPictureSize(reopened.host, reopened.video, () => "camera.door");
  assert.equal(reopened.properties.get(PROPERTY), "1.25");

  const other = card();
  c300xFollowPictureSize(other.host, other.video, () => "camera.garage");
  assert.equal(other.properties.has(PROPERTY), false);
  assert.deepEqual([...items.keys()], ["c300x-picture-ratio:camera.door"]);
});

test("the shape follows the camera once it is known and when it changes", () => {
  const items = browserStorage();
  items.set("c300x-picture-ratio:camera.door", "1.25");
  items.set("c300x-picture-ratio:camera.garage", "1.4333");
  // A card that finds its camera only through Home Assistant knows none at first.
  let camera = "";
  const first = card();
  const frame = c300xFollowPictureSize(first.host, first.video, () => camera);
  assert.equal(first.properties.has(PROPERTY), false);
  camera = "camera.door";
  frame.sync();
  assert.equal(first.properties.get(PROPERTY), "1.25");
  camera = "camera.garage";
  frame.sync();
  assert.equal(first.properties.get(PROPERTY), "1.4333");
  // A camera without a shape of its own does not keep the one of the last.
  camera = "camera.new";
  frame.sync();
  assert.equal(first.properties.has(PROPERTY), false);
});

test("a browser without storage still follows the stream", () => {
  globalThis.localStorage = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
  };
  const first = card();
  c300xFollowPictureSize(first.host, first.video, () => "camera.door");
  first.plays(720, 576);
  assert.equal(first.properties.get(PROPERTY), "1.25");
});

test("sizes that are no picture are left out", () => {
  assert.equal(c300xPictureRatio(720, 576), 1.25);
  assert.equal(c300xPictureRatio(0, 576), null);
  assert.equal(c300xPictureRatio(720, 0), null);
  assert.equal(c300xPictureRatio(4000, 100), null);
  assert.equal(c300xPictureRatio(100, 4000), null);
  browserStorage().set("c300x-picture-ratio:camera.door", "12");
  const first = card();
  c300xFollowPictureSize(first.host, first.video, () => "camera.door");
  assert.equal(first.properties.has(PROPERTY), false);
});
