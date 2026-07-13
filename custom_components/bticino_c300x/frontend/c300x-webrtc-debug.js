const C300X_WEBRTC_STATS_DEBUG_INTERVAL_MS = 1000;
const C300X_WEBRTC_STATS_DEBUG_HISTORY_LIMIT = 180;
const C300X_WEBRTC_MEDIA_DEBUG_EVENTS = [
  "abort",
  "emptied",
  "ended",
  "error",
  "pause",
  "play",
  "playing",
  "stalled",
  "suspend",
  "waiting",
];
const C300X_WEBRTC_PEER_DEBUG_EVENTS = [
  "connectionstatechange",
  "iceconnectionstatechange",
  "icegatheringstatechange",
  "signalingstatechange",
];
const C300X_STATS_FIELDS = [
  "availableIncomingBitrate",
  "availableOutgoingBitrate",
  "bytesReceived",
  "bytesSent",
  "concealedSamples",
  "currentRoundTripTime",
  "framesDecoded",
  "framesDropped",
  "framesPerSecond",
  "framesReceived",
  "freezeCount",
  "jitter",
  "jitterBufferDelay",
  "jitterBufferEmittedCount",
  "keyFramesDecoded",
  "packetsLost",
  "packetsReceived",
  "packetsSent",
  "pliCount",
  "qpSum",
  "retransmittedBytesReceived",
  "retransmittedPacketsReceived",
  "roundTripTime",
  "totalDecodeTime",
  "totalFreezesDuration",
  "totalInterFrameDelay",
];
const C300X_STATS_RATE_FIELDS = [
  "bytesReceived",
  "bytesSent",
  "framesDecoded",
  "framesDropped",
  "framesReceived",
  "packetsLost",
  "packetsReceived",
  "packetsSent",
];
const C300X_PLAYBACK_QUALITY_RATE_FIELDS = [
  "corruptedVideoFrames",
  "droppedVideoFrames",
  "totalVideoFrames",
  "webkitDecodedFrameCount",
  "webkitDroppedFrameCount",
];

function c300xFirstPositiveNumber(...values) {
  for (const value of values) {
    if (typeof value === "number" && value > 0) {
      return value;
    }
  }
  return 0;
}

function c300xBrowserWindow() {
  return globalThis.window || globalThis;
}

export class C300XWebrtcDebugCollector {
  constructor({ getEntityId, isHomeCallMode, getRemoteStream, sendSnapshot }) {
    this._getEntityId = getEntityId;
    this._isHomeCallMode = isHomeCallMode;
    this._getRemoteStream = getRemoteStream;
    this._sendSnapshot = sendSnapshot || null;
    this._pc = null;
    this._timer = null;
    this._previous = null;
    this._sequence = 0;
    this._cleanup = [];
  }

  start(pc, mediaElement) {
    if (this._timer || !pc?.getStats) {
      return false;
    }
    const target = c300xBrowserWindow();
    this._pc = pc;
    this._previous = null;
    this._sequence = 0;
    this._attachEvents(pc, mediaElement);
    this._record(mediaElement, "start");
    this._timer = target.setInterval(
      () => this._record(mediaElement, "tick"),
      C300X_WEBRTC_STATS_DEBUG_INTERVAL_MS,
    );
    return true;
  }

  stop(reason) {
    if (this._timer) {
      c300xBrowserWindow().clearInterval(this._timer);
      this._timer = null;
    }
    this._detachEvents();
    if (this._previous) {
      this._push({
        event: "stop",
        reason,
        sequence: this._sequence,
        timestamp: new Date().toISOString(),
      });
    }
    this._previous = null;
    this._pc = null;
  }

  async _record(mediaElement, event) {
    const pc = this._pc;
    if (!pc?.getStats) {
      return;
    }
    const timestamp = Date.now();
    let report;
    try {
      report = await pc.getStats();
    } catch (err) {
      this._push({
        event: "error",
        message: err?.message || `${err}`,
        sequence: ++this._sequence,
        timestamp: new Date(timestamp).toISOString(),
      });
      return;
    }
    if (this._pc !== pc) {
      return;
    }
    const previous = this._previous;
    const next = new Map();
    const snapshot = {
      event,
      sequence: ++this._sequence,
      timestamp: new Date(timestamp).toISOString(),
      entity_id: this._getEntityId?.() || "",
      session_id: pc.__c300x_session_id || "",
      mode: this._isHomeCallMode?.() ? "home_call" : "doorbell",
      connection_state: pc.connectionState || "",
      ice_connection_state: pc.iceConnectionState || "",
      ice_gathering_state: pc.iceGatheringState || "",
      signaling_state: pc.signalingState || "",
      media: this._mediaStats(mediaElement, previous, next, timestamp),
      inbound: {},
      outbound: {},
      candidate_pair: null,
      candidates: {},
      transceivers: this._transceiverStats(pc),
    };

    const items = this._statsReportItems(report);
    const itemsById = new Map();
    for (const item of items) {
      next.set(item.id, { ...item, __c300x_seen_at: timestamp });
      itemsById.set(item.id, item);
    }

    for (const item of items) {
      if (item.type === "inbound-rtp" && !item.isRemote) {
        const kind = item.kind || item.mediaType || "unknown";
        snapshot.inbound[kind] = this._compactStats(item, previous, timestamp);
        continue;
      }
      if (item.type === "outbound-rtp" && !item.isRemote) {
        const kind = item.kind || item.mediaType || "unknown";
        snapshot.outbound[kind] = this._compactStats(item, previous, timestamp);
        continue;
      }
      if (
        item.type === "candidate-pair"
        && (item.selected === true || (item.nominated === true && item.state === "succeeded"))
      ) {
        snapshot.candidate_pair = this._compactStats(item, previous, timestamp);
        snapshot.candidates = this._candidatePairStats(item, itemsById);
      }
    }
    snapshot.observation = this.classifySnapshot(snapshot);

    this._previous = next;
    this._push(snapshot);
  }

  classifySnapshot(snapshot) {
    const inboundVideo = snapshot.inbound?.video || null;
    const playbackQuality = snapshot.media?.playbackQuality || null;
    const mediaRate = snapshot.media?.currentTimePerSecond;
    const bytesRate = inboundVideo?.bytesReceivedPerSecond;
    const decodedRate = c300xFirstPositiveNumber(
      inboundVideo?.framesDecodedPerSecond,
      inboundVideo?.framesPerSecond,
      playbackQuality?.totalVideoFramesPerSecond,
      playbackQuality?.webkitDecodedFrameCountPerSecond,
    );
    const receivedFrameRate = c300xFirstPositiveNumber(
      inboundVideo?.framesReceivedPerSecond,
      inboundVideo?.framesPerSecond,
    );
    const packetRate = inboundVideo?.packetsReceivedPerSecond;
    const connected = ["connected", "completed"].includes(snapshot.ice_connection_state)
      || snapshot.connection_state === "connected";
    const mediaProgressing = typeof mediaRate === "number" && mediaRate > 0.05;
    const inboundProgressing = [bytesRate, decodedRate, receivedFrameRate, packetRate].some(
      (value) => typeof value === "number" && value > 0,
    );
    const decodingProgressing = [decodedRate, receivedFrameRate].some(
      (value) => typeof value === "number" && value > 0,
    );
    let likelyLayer = "warming_up_or_unknown";
    if (!connected) {
      likelyLayer = "webrtc_transport";
    } else if (inboundProgressing && decodingProgressing && !mediaProgressing) {
      likelyLayer = "browser_media_element";
    } else if (inboundProgressing && !decodingProgressing) {
      likelyLayer = "browser_decoder";
    } else if (!inboundProgressing && typeof bytesRate === "number") {
      likelyLayer = "go2rtc_cloud_or_sender";
    }
    return {
      connected,
      decodingProgressing,
      inboundProgressing,
      likelyLayer,
      mediaProgressing,
    };
  }

  _statsReportItems(report) {
    const items = [];
    if (report?.forEach) {
      report.forEach((value) => items.push(value));
      return items;
    }
    if (report?.[Symbol.iterator]) {
      for (const item of report) {
        items.push(Array.isArray(item) ? item[1] : item);
      }
    }
    return items;
  }

  _compactStats(item, previous, timestamp) {
    const compact = {
      id: item.id,
      type: item.type,
      kind: item.kind || item.mediaType || "",
      codecId: item.codecId || "",
      state: item.state || "",
      localCandidateId: item.localCandidateId || "",
      remoteCandidateId: item.remoteCandidateId || "",
    };
    for (const field of C300X_STATS_FIELDS) {
      if (typeof item[field] === "number") {
        compact[field] = item[field];
      }
    }
    const previousItem = previous?.get?.(item.id);
    const elapsedSeconds = this._elapsedSeconds(item, previousItem, timestamp);
    if (elapsedSeconds > 0) {
      for (const field of C300X_STATS_RATE_FIELDS) {
        if (typeof item[field] !== "number" || typeof previousItem?.[field] !== "number") {
          continue;
        }
        compact[`${field}PerSecond`] = (item[field] - previousItem[field]) / elapsedSeconds;
      }
    }
    return compact;
  }

  _candidatePairStats(pair, itemsById) {
    return {
      local: this._compactCandidateStats(itemsById.get(pair.localCandidateId)),
      remote: this._compactCandidateStats(itemsById.get(pair.remoteCandidateId)),
    };
  }

  _compactCandidateStats(candidate) {
    if (!candidate) {
      return null;
    }
    return {
      id: candidate.id || "",
      type: candidate.type || "",
      candidateType: candidate.candidateType || "",
      networkType: candidate.networkType || "",
      protocol: candidate.protocol || "",
      relayProtocol: candidate.relayProtocol || "",
      transportId: candidate.transportId || "",
    };
  }

  _elapsedSeconds(item, previousItem, timestamp) {
    if (!previousItem) {
      return 0;
    }
    const currentTimestamp = typeof item.timestamp === "number"
      ? item.timestamp
      : timestamp;
    const previousTimestamp = typeof previousItem.timestamp === "number"
      ? previousItem.timestamp
      : previousItem.__c300x_seen_at;
    const elapsedMs = currentTimestamp - previousTimestamp;
    return elapsedMs > 0 ? elapsedMs / 1000 : 0;
  }

  _mediaStats(mediaElement, previous, next, timestamp) {
    if (!mediaElement) {
      return null;
    }
    const previousMedia = previous?.get?.("__media");
    const currentTime = Number(mediaElement.currentTime || 0);
    const elapsedSeconds = previousMedia
      ? (timestamp - previousMedia.__c300x_seen_at) / 1000
      : 0;
    const playbackQuality = this._playbackQualityStats(mediaElement);
    const media = {
      currentTime,
      paused: mediaElement.paused === true,
      ended: mediaElement.ended === true,
      readyState: mediaElement.readyState,
      networkState: mediaElement.networkState,
      videoHeight: mediaElement.videoHeight || 0,
      videoWidth: mediaElement.videoWidth || 0,
      playbackQuality,
      tracks: [],
    };
    if (elapsedSeconds > 0) {
      media.currentTimePerSecond = (currentTime - previousMedia.currentTime) / elapsedSeconds;
      for (const field of C300X_PLAYBACK_QUALITY_RATE_FIELDS) {
        if (
          typeof playbackQuality[field] === "number"
          && typeof previousMedia.playbackQuality?.[field] === "number"
        ) {
          playbackQuality[`${field}PerSecond`] = (
            playbackQuality[field] - previousMedia.playbackQuality[field]
          ) / elapsedSeconds;
        }
      }
    }
    for (const track of this._getRemoteStream?.()?.getTracks?.() || []) {
      media.tracks.push(this._trackStats(track));
    }
    next?.set?.("__media", {
      currentTime,
      playbackQuality,
      __c300x_seen_at: timestamp,
    });
    return media;
  }

  _playbackQualityStats(mediaElement) {
    const quality = {};
    if (typeof mediaElement.getVideoPlaybackQuality === "function") {
      const playbackQuality = mediaElement.getVideoPlaybackQuality();
      for (const field of [
        "corruptedVideoFrames",
        "creationTime",
        "droppedVideoFrames",
        "totalFrameDelay",
        "totalVideoFrames",
      ]) {
        if (typeof playbackQuality?.[field] === "number") {
          quality[field] = playbackQuality[field];
        }
      }
    }
    for (const [source, target] of [
      ["webkitDecodedFrameCount", "webkitDecodedFrameCount"],
      ["webkitDroppedFrameCount", "webkitDroppedFrameCount"],
    ]) {
      if (typeof mediaElement[source] === "number") {
        quality[target] = mediaElement[source];
      }
    }
    return quality;
  }

  _transceiverStats(pc) {
    if (typeof pc?.getTransceivers !== "function") {
      return [];
    }
    return pc.getTransceivers().map((transceiver) => ({
      currentDirection: transceiver.currentDirection || "",
      direction: transceiver.direction || "",
      mid: transceiver.mid || "",
      receiverTrack: this._trackStats(transceiver.receiver?.track),
      senderTrack: this._trackStats(transceiver.sender?.track),
      stopped: transceiver.stopped === true,
    }));
  }

  _trackStats(track) {
    if (!track) {
      return null;
    }
    return {
      enabled: track.enabled,
      id: track.id,
      kind: track.kind,
      muted: track.muted,
      readyState: track.readyState,
    };
  }

  _attachEvents(pc, mediaElement) {
    this._detachEvents();
    const cleanups = [];
    if (typeof pc?.addEventListener === "function") {
      for (const eventName of C300X_WEBRTC_PEER_DEBUG_EVENTS) {
        const handler = () => this._pushEvent("peer_event", {
          peer_event: eventName,
        });
        pc.addEventListener(eventName, handler);
        cleanups.push(() => pc.removeEventListener?.(eventName, handler));
      }
    }
    if (typeof mediaElement?.addEventListener === "function") {
      for (const eventName of C300X_WEBRTC_MEDIA_DEBUG_EVENTS) {
        const handler = (event) => this._pushEvent("media_event", {
          media_event: event.type || eventName,
          media: this._mediaStats(mediaElement, this._previous, null, Date.now()),
          media_error: this._mediaErrorStats(mediaElement.error),
        });
        mediaElement.addEventListener(eventName, handler);
        cleanups.push(() => mediaElement.removeEventListener?.(eventName, handler));
      }
    }
    this._cleanup = cleanups;
  }

  _detachEvents() {
    for (const cleanup of this._cleanup.splice(0)) {
      cleanup();
    }
  }

  _mediaErrorStats(error) {
    if (!error) {
      return null;
    }
    return {
      code: error.code || 0,
      message: error.message || "",
    };
  }

  _pushEvent(event, details = {}) {
    if (!this._timer && !this._previous) {
      return;
    }
    const pc = this._pc;
    this._push({
      event,
      sequence: ++this._sequence,
      timestamp: new Date().toISOString(),
      entity_id: this._getEntityId?.() || "",
      mode: this._isHomeCallMode?.() ? "home_call" : "doorbell",
      connection_state: pc?.connectionState || "",
      ice_connection_state: pc?.iceConnectionState || "",
      ice_gathering_state: pc?.iceGatheringState || "",
      signaling_state: pc?.signalingState || "",
      ...details,
    });
  }

  _push(snapshot) {
    const target = c300xBrowserWindow();
    const history = Array.isArray(target.__c300xWebrtcStats)
      ? target.__c300xWebrtcStats
      : [];
    history.push(snapshot);
    while (history.length > C300X_WEBRTC_STATS_DEBUG_HISTORY_LIMIT) {
      history.shift();
    }
    target.__c300xWebrtcStats = history;
    target.console?.debug?.("C300X WebRTC stats", snapshot);
    this._sendSnapshot?.(snapshot);
  }
}
