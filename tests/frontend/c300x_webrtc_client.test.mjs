import assert from "node:assert/strict";
import test from "node:test";

import { C300XWebrtcClient } from "../../custom_components/bticino_c300x/frontend/c300x-webrtc-client.js";

test("WebRTC client hard-closes the peer when the backend closes a session", async () => {
  const calls = [];
  globalThis.window = {
    clearTimeout,
    setTimeout,
  };
  const client = new C300XWebrtcClient({
    getEntityId: () => "camera.bticino_c300x_doorbell_camera",
    getHass: () => ({
      connection: {
        subscribeMessage(callback) {
          callback({ type: "closed", reason: "doorbell_video_stopped" });
          return Promise.resolve(() => calls.push(["unsubscribe"]));
        },
      },
    }),
    isHomeCallMode: () => false,
    onClosed: (reason) => calls.push(["closed", reason]),
  });
  let peerClosed = false;
  const stoppedTracks = [];
  client._pc = {
    close() {
      peerClosed = true;
    },
  };
  client._remoteStream = {
    getTracks() {
      return [
        {
          stop() {
            stoppedTracks.push("video");
          },
        },
      ];
    },
  };
  client._running = true;

  await assert.rejects(
    client._subscribeWebrtcOffer("v=0"),
    /HA WebRTC offer cancelled/,
  );

  assert.equal(peerClosed, true);
  assert.deepEqual(stoppedTracks, ["video"]);
  assert.equal(client.running, false);
  assert.equal(client.pc, null);
  assert.equal(client.remoteStream, null);
  assert.deepEqual(calls, [
    ["closed", "doorbell_video_stopped"],
    ["unsubscribe"],
  ]);
});
