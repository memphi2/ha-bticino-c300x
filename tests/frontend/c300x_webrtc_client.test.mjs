import assert from "node:assert/strict";
import test from "node:test";

import { C300XWebrtcDebugCollector } from "../../custom_components/bticino_c300x/frontend/c300x-webrtc-debug.js";
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

test("WebRTC stats debug stays inactive unless backend debug mode is enabled", async () => {
  const calls = [];
  const intervals = [];
  globalThis.window = {
    clearInterval() {},
    console: {
      debug(...args) {
        calls.push(["debug", ...args]);
      },
    },
    setInterval(...args) {
      intervals.push(args);
      return 1;
    },
  };
  const client = new C300XWebrtcClient({
    getEntityId: () => "camera.bticino_c300x_doorbell_camera",
    getHass: () => ({
      callWS(message) {
        calls.push(["ws", message]);
        return Promise.resolve({ enabled: false, webrtc_stats: false });
      },
    }),
    isHomeCallMode: () => false,
  });
  client._pc = {
    getStats() {
      throw new Error("stats must not be read while debug is disabled");
    },
  };

  await client._maybeStartStatsDebug({ currentTime: 0 });

  assert.deepEqual(calls, [["ws", { type: "bticino_c300x/debug/status" }]]);
  assert.equal(intervals.length, 0);
  assert.equal(globalThis.window.__c300xWebrtcStats, undefined);
});

test("WebRTC stats debug ignores stale backend replies after peer replacement", async () => {
  let resolveDebugStatus;
  const intervals = [];
  globalThis.window = {
    clearInterval() {},
    console: {
      debug() {},
    },
    setInterval(...args) {
      intervals.push(args);
      return 1;
    },
  };
  const client = new C300XWebrtcClient({
    getEntityId: () => "camera.bticino_c300x_doorbell_camera",
    getHass: () => ({
      callWS() {
        return new Promise((resolve) => {
          resolveDebugStatus = resolve;
        });
      },
    }),
    isHomeCallMode: () => false,
  });
  const oldPeer = {
    getStats() {
      throw new Error("old peer stats must not be sampled");
    },
  };
  const newPeer = {
    getStats() {
      throw new Error("new peer stats must not be sampled by stale reply");
    },
  };
  client._pc = oldPeer;
  const pending = client._maybeStartStatsDebug({ currentTime: 0 });
  client._pc = newPeer;

  resolveDebugStatus({ enabled: true, webrtc_stats: true });
  await pending;

  assert.equal(intervals.length, 0);
  assert.equal(globalThis.window.__c300xWebrtcStats, undefined);
});

test("WebRTC stats debug samples browser media stats in backend debug mode", async () => {
  const calls = [];
  const intervals = [];
  const clearedIntervals = [];
  const peerListeners = new Map();
  const mediaListeners = new Map();
  const tracks = [
    {
      enabled: true,
      id: "track-video",
      kind: "video",
      muted: false,
      readyState: "live",
      stop() {
        calls.push(["stop-track", "video"]);
      },
    },
  ];
  let statsCall = 0;
  globalThis.window = {
    clearInterval(timer) {
      clearedIntervals.push(timer);
    },
    console: {
      debug(...args) {
        calls.push(["debug", ...args]);
      },
    },
    setInterval(callback, intervalMs) {
      intervals.push([callback, intervalMs]);
      return 42;
    },
  };
  const client = new C300XWebrtcClient({
    getEntityId: () => "camera.bticino_c300x_doorbell_camera",
    getHass: () => ({
      callWS(message) {
        calls.push(["ws", message]);
        return Promise.resolve({ enabled: true, webrtc_stats: true });
      },
    }),
    isHomeCallMode: () => false,
  });
  client._pc = {
    addEventListener(eventName, handler) {
      peerListeners.set(eventName, handler);
    },
    close() {
      calls.push(["close-peer"]);
    },
    connectionState: "connected",
    getTransceivers() {
      return [
        {
          currentDirection: "recvonly",
          direction: "recvonly",
          mid: "0",
          receiver: { track: tracks[0] },
          sender: { track: null },
        },
      ];
    },
    getStats() {
      statsCall += 1;
      const timestamp = statsCall === 1 ? 1000 : 2000;
      const framesDecoded = statsCall === 1 ? 10 : 30;
      const bytesReceived = statsCall === 1 ? 1000 : 3000;
      return Promise.resolve(
        new Map([
          [
            "inbound-video",
            {
              bytesReceived,
              framesDecoded,
              id: "inbound-video",
              kind: "video",
              packetsReceived: statsCall === 1 ? 20 : 50,
              timestamp,
              type: "inbound-rtp",
            },
          ],
          [
            "candidate-pair",
            {
              currentRoundTripTime: 0.05,
              id: "candidate-pair",
              localCandidateId: "local-candidate",
              remoteCandidateId: "remote-candidate",
              selected: true,
              state: "succeeded",
              timestamp,
              type: "candidate-pair",
            },
          ],
          [
            "local-candidate",
            {
              candidateType: "relay",
              id: "local-candidate",
              networkType: "wifi",
              protocol: "udp",
              relayProtocol: "udp",
              type: "local-candidate",
            },
          ],
          [
            "remote-candidate",
            {
              candidateType: "host",
              id: "remote-candidate",
              protocol: "udp",
              type: "remote-candidate",
            },
          ],
        ]),
      );
    },
    iceConnectionState: "connected",
    iceGatheringState: "complete",
    removeEventListener(eventName, handler) {
      if (peerListeners.get(eventName) === handler) {
        peerListeners.delete(eventName);
      }
    },
    signalingState: "stable",
  };
  client._remoteStream = {
    getTracks() {
      return tracks;
    },
  };
  client._running = true;
  client._sessionId = "session-1";
  const mediaElement = {
    addEventListener(eventName, handler) {
      mediaListeners.set(eventName, handler);
    },
    currentTime: 1,
    ended: false,
    getVideoPlaybackQuality() {
      return {
        droppedVideoFrames: 1,
        totalVideoFrames: statsCall === 1 ? 10 : 31,
      };
    },
    networkState: 2,
    paused: false,
    readyState: 4,
    removeEventListener(eventName, handler) {
      if (mediaListeners.get(eventName) === handler) {
        mediaListeners.delete(eventName);
      }
    },
    videoHeight: 720,
    videoWidth: 1280,
    webkitDecodedFrameCount: 12,
    webkitDroppedFrameCount: 1,
  };

  await client._maybeStartStatsDebug(mediaElement);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(intervals.length, 1);
  assert.equal(intervals[0][1], 1000);
  assert.equal(peerListeners.has("iceconnectionstatechange"), true);
  assert.equal(mediaListeners.has("waiting"), true);

  mediaElement.currentTime = 2;
  await intervals[0][0]();
  mediaListeners.get("waiting")({ type: "waiting" });
  peerListeners.get("iceconnectionstatechange")();

  const snapshots = globalThis.window.__c300xWebrtcStats;
  assert.equal(snapshots.length, 4);
  assert.equal(snapshots[0].event, "start");
  assert.equal(snapshots[0].media.videoWidth, 1280);
  assert.equal(snapshots[0].media.playbackQuality.totalVideoFrames, 10);
  assert.equal(snapshots[0].media.playbackQuality.webkitDecodedFrameCount, 12);
  assert.deepEqual(snapshots[0].media.tracks, [
    {
      enabled: true,
      id: "track-video",
      kind: "video",
      muted: false,
      readyState: "live",
    },
  ]);
  assert.deepEqual(snapshots[0].transceivers, [
    {
      currentDirection: "recvonly",
      direction: "recvonly",
      mid: "0",
      receiverTrack: {
        enabled: true,
        id: "track-video",
        kind: "video",
        muted: false,
        readyState: "live",
      },
      senderTrack: null,
      stopped: false,
    },
  ]);
  assert.equal(snapshots[1].inbound.video.framesDecoded, 30);
  assert.equal(snapshots[1].inbound.video.framesDecodedPerSecond, 20);
  assert.equal(snapshots[1].inbound.video.bytesReceivedPerSecond, 2000);
  assert.equal(snapshots[1].candidate_pair.currentRoundTripTime, 0.05);
  assert.equal(snapshots[1].candidates.local.candidateType, "relay");
  assert.equal(snapshots[1].candidates.remote.candidateType, "host");
  assert.equal(snapshots[1].observation.likelyLayer, "warming_up_or_unknown");
  assert.equal(snapshots[2].event, "media_event");
  assert.equal(snapshots[2].media_event, "waiting");
  assert.equal(snapshots[3].event, "peer_event");
  assert.equal(snapshots[3].peer_event, "iceconnectionstatechange");

  client.close();

  assert.deepEqual(clearedIntervals, [42]);
  assert.equal(peerListeners.size, 0);
  assert.equal(mediaListeners.size, 0);
  assert.equal(globalThis.window.__c300xWebrtcStats.at(-1).event, "stop");
  const websocketCalls = calls.filter((call) => call[0] === "ws");
  assert.deepEqual(
    websocketCalls.slice(0, 1),
    [["ws", { type: "bticino_c300x/debug/status" }]],
  );
  assert.equal(
    websocketCalls.filter(
      (call) => call[1].type === "bticino_c300x/debug/webrtc_stats",
    ).length,
    6,
  );
  assert.equal(websocketCalls[1][1].snapshot.event, "debug_setup");
  assert.equal(websocketCalls[1][1].snapshot.debug_state, "enabled");
  assert.equal(websocketCalls[2][1].snapshot.event, "start");
  assert.equal(websocketCalls.at(-1)[1].snapshot.event, "stop");
  assert.deepEqual(
    calls.filter((call) => call[0] === "stop-track"),
    [["stop-track", "video"]],
  );
});

test("WebRTC stats debug classifies the likely frozen layer", () => {
  const collector = new C300XWebrtcDebugCollector({
    getEntityId: () => "camera.bticino_c300x_doorbell_camera",
    isHomeCallMode: () => false,
  });

  assert.equal(
    collector.classifySnapshot({
      connection_state: "disconnected",
      ice_connection_state: "disconnected",
      inbound: {},
      media: { currentTimePerSecond: 0 },
    }).likelyLayer,
    "webrtc_transport",
  );
  assert.equal(
    collector.classifySnapshot({
      connection_state: "connected",
      ice_connection_state: "connected",
      inbound: {
        video: {
          bytesReceivedPerSecond: 2000,
          framesDecodedPerSecond: 15,
        },
      },
      media: { currentTimePerSecond: 0 },
    }).likelyLayer,
    "browser_media_element",
  );
  assert.equal(
    collector.classifySnapshot({
      connection_state: "connected",
      ice_connection_state: "connected",
      inbound: {
        video: {
          bytesReceivedPerSecond: 2000,
          framesPerSecond: 25,
        },
      },
      media: { currentTimePerSecond: 0 },
    }).likelyLayer,
    "browser_media_element",
  );
  assert.equal(
    collector.classifySnapshot({
      connection_state: "connected",
      ice_connection_state: "connected",
      inbound: {
        video: {
          bytesReceivedPerSecond: 2000,
          framesDecodedPerSecond: 0,
        },
      },
      media: { currentTimePerSecond: 0 },
    }).likelyLayer,
    "browser_decoder",
  );
  assert.equal(
    collector.classifySnapshot({
      connection_state: "connected",
      ice_connection_state: "connected",
      inbound: {
        video: {
          bytesReceivedPerSecond: 0,
          framesDecodedPerSecond: 0,
        },
      },
      media: { currentTimePerSecond: 0 },
    }).likelyLayer,
    "go2rtc_cloud_or_sender",
  );
});
