import { C300XMediaAttachment } from "./c300x-media-attach.js?v=9bdbfdc3de6966e8";

const C300X_WEBRTC_DISCONNECTED_GRACE_MS = 10000;
const C300X_WEBRTC_DEBUG_STATUS_COMMAND = "bticino_c300x/debug/status";
const C300X_WEBRTC_DEBUG_MODULE = "./c300x-webrtc-debug.js?v=9bdbfdc3de6966e8";

export class C300XWebrtcClient {
  constructor({ getHass, getEntityId, isHomeCallMode, onClosed, onTrack, getCardGainDb }) {
    this._getHass = getHass;
    this._getEntityId = getEntityId;
    this._isHomeCallMode = isHomeCallMode;
    this._onClosed = onClosed;
    this._onTrack = onTrack;
    this._getCardGainDb = getCardGainDb || null;
    this._mediaAttachment = null;
    this._pc = null;
    this._remoteStream = null;
    this._unsub = null;
    this._closing = false;
    this._pendingOfferReject = null;
    this._sessionId = "";
    this._pendingCandidates = [];
    this._pendingRemoteCandidates = [];
    this._running = false;
    this._disconnectedTimer = null;
    this._statsDebug = null;
  }

  get running() {
    return this._running;
  }

  get remoteStream() {
    return this._remoteStream;
  }

  get pc() {
    return this._pc;
  }

  // Re-apply the client-side gain (call when the codec mode or configured
  // gain changes while a stream is playing).
  refreshGain() {
    return this._mediaAttachment?.refreshGain();
  }

  // Move the client-side gain/muting to the element that now renders the
  // stream (used when a preview stream is promoted to the main element).
  retargetMedia(mediaElement) {
    return this._mediaAttachment?.retarget(mediaElement);
  }

  async start(options = {}) {
    const {
      microphoneStream = null,
      receiveAudio = true,
      mediaElement,
      attachOnFirstTrack = false,
    } = options;
    if (this._running) {
      return;
    }
    this._running = true;
    this._closing = false;

    const clientConfig = await this._callWs({
      type: this._webrtcGetClientConfigCommand(),
      entity_id: this._getEntityId(),
    });
    const rtcConfig = c300xNormalizeRtcConfig(clientConfig);
    this._remoteStream = new MediaStream();
    const mediaAttachment = new C300XMediaAttachment(mediaElement, this._remoteStream, {
      getGainDb: this._getCardGainDb,
    });
    this._mediaAttachment = mediaAttachment;
    if (!attachOnFirstTrack) {
      mediaAttachment.attach();
    }

    const pc = new RTCPeerConnection(rtcConfig);
    this._pc = pc;

    if (!this._isHomeCallMode()) {
      pc.addTransceiver("video", { direction: "recvonly" });
    }
    if (microphoneStream) {
      for (const track of microphoneStream.getAudioTracks()) {
        pc.addTrack(track, microphoneStream);
      }
      for (const transceiver of pc.getTransceivers()) {
        if (transceiver.sender?.track?.kind === "audio") {
          transceiver.direction = "sendrecv";
        }
      }
    } else if (receiveAudio) {
      pc.addTransceiver("audio", { direction: "recvonly" });
    }

    pc.ontrack = (event) => {
      const tracks = event.streams?.[0]?.getTracks?.() || [event.track];
      for (const track of tracks) {
        if (!this._remoteStream.getTracks().some((item) => item.id === track.id)) {
          this._remoteStream.addTrack(track);
        }
      }
      mediaAttachment.play();
      this._onTrack?.();
    };

    pc.onicecandidate = (event) => {
      if (!event.candidate) {
        return;
      }
      this._sendOrQueueCandidate(event.candidate.toJSON());
    };

    const handleConnectionStateChange = () => {
      if (this._closing) {
        return;
      }
      const state = pc.connectionState || pc.iceConnectionState;
      if (state === "closed" || state === "failed") {
        this._clearDisconnectedTimer();
        this._handleProviderClosed(state);
        return;
      }
      if (state === "disconnected") {
        this._scheduleDisconnectedClose();
        return;
      }
      this._clearDisconnectedTimer();
    };
    pc.onconnectionstatechange = handleConnectionStateChange;
    pc.oniceconnectionstatechange = handleConnectionStateChange;
    this._maybeStartStatsDebug(mediaElement);

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    const answerSdp = await this._subscribeWebrtcOffer(pc.localDescription.sdp);
    if (!answerSdp) {
      throw new Error("HA WebRTC answer missing");
    }

    await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
    this._flushRemoteCandidates();
  }

  close() {
    this._closing = true;
    this._stopStatsDebug("close");
    if (this._pc) {
      try {
        this._pc.close();
      } catch (_err) {}
    }
    this._pc = null;
    this._running = false;
    this._clearDisconnectedTimer();

    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
    this._sessionId = "";
    this._pendingCandidates = [];
    this._pendingRemoteCandidates = [];
    if (this._pendingOfferReject) {
      const reject = this._pendingOfferReject;
      this._pendingOfferReject = null;
      reject(new Error("HA WebRTC offer cancelled"));
    }

    if (this._mediaAttachment) {
      this._mediaAttachment.detach();
      this._mediaAttachment = null;
    }
    if (this._remoteStream) {
      for (const track of this._remoteStream.getTracks()) {
        track.stop();
      }
    }
    this._remoteStream = null;
  }

  async _callWs(message) {
    const hass = this._getHass();
    if (!hass?.callWS) {
      throw new Error("Home Assistant WebSocket is not available");
    }
    return hass.callWS(message);
  }

  async _subscribeWebrtcOffer(offer) {
    const hass = this._getHass();
    if (!hass?.connection?.subscribeMessage) {
      throw new Error("Home Assistant subscription WebSocket is not available");
    }

    return new Promise((resolve, reject) => {
      let settled = false;
      const timeout = window.setTimeout(() => {
        if (settled) {
          return;
        }
        settled = true;
        this._pendingOfferReject = null;
        reject(new Error("HA WebRTC answer timeout"));
      }, 20000);
      this._pendingOfferReject = (err) => {
        if (settled) {
          return;
        }
        settled = true;
        window.clearTimeout(timeout);
        reject(err);
      };

      hass.connection
        .subscribeMessage(
          (message) => {
            if (!message) {
              return;
            }
            if (message.type === "closed") {
              if (this._closing) {
                return;
              }
              this._handleProviderClosed(message.reason || "closed");
              return;
            }
            if (message.type === "candidate" && message.candidate) {
              this._addRemoteCandidate(message.candidate);
              return;
            }
            if (settled) {
              return;
            }
            if (message.type === "session" && message.session_id) {
              this._sessionId = message.session_id;
              if (this._pc) {
                this._pc.__c300x_session_id = message.session_id;
              }
              this._flushPendingCandidates();
              return;
            }
            if (message.type === "answer") {
              settled = true;
              this._pendingOfferReject = null;
              window.clearTimeout(timeout);
              resolve(message.answer);
              return;
            }
            if (message.type === "error") {
              settled = true;
              this._pendingOfferReject = null;
              window.clearTimeout(timeout);
              reject(new Error(message.message || message.code || "HA WebRTC error"));
            }
          },
          {
            type: this._webrtcOfferCommand(),
            entity_id: this._getEntityId(),
            offer,
          },
          { resubscribe: false },
        )
        .then((unsub) => {
          if (this._closing || !this._pc) {
            unsub();
            return;
          }
          this._unsub = unsub;
        })
        .catch((err) => {
          if (settled) {
            return;
          }
          settled = true;
          this._pendingOfferReject = null;
          window.clearTimeout(timeout);
          reject(err);
        });
    });
  }

  _handleProviderClosed(reason) {
    // Notify the caller (which reads pc/remoteStream/running to decide
    // whether there is anything left to tear down) before this client
    // clears that same state via close(), then hard-close regardless of
    // what the callback did so no caller can leak the peer connection.
    this._onClosed?.(reason || "closed");
    this.close();
  }

  _scheduleDisconnectedClose() {
    if (this._disconnectedTimer) {
      return;
    }
    this._disconnectedTimer = window.setTimeout(() => {
      this._disconnectedTimer = null;
      if (this._closing || !this._pc) {
        return;
      }
      const state = this._pc.connectionState || this._pc.iceConnectionState;
      if (state === "disconnected") {
        this._handleProviderClosed("disconnected");
      }
    }, C300X_WEBRTC_DISCONNECTED_GRACE_MS);
  }

  _clearDisconnectedTimer() {
    if (!this._disconnectedTimer) {
      return;
    }
    window.clearTimeout(this._disconnectedTimer);
    this._disconnectedTimer = null;
  }

  async _maybeStartStatsDebug(mediaElement) {
    const pc = this._pc;
    if (this._statsDebug || !pc?.getStats) {
      return;
    }
    let status;
    try {
      status = await this._callWs({ type: C300X_WEBRTC_DEBUG_STATUS_COMMAND });
    } catch (_err) {
      return;
    }
    if (this._closing || this._pc !== pc || status?.webrtc_stats !== true) {
      return;
    }
    this._sendStatsDebugProbe("debug_setup", {
      debug_state: "enabled",
    });
    try {
      const { C300XWebrtcDebugCollector } = await import(C300X_WEBRTC_DEBUG_MODULE);
      if (this._closing || this._pc !== pc || this._statsDebug) {
        return;
      }
      pc.__c300x_session_id = this._sessionId || "";
      this._statsDebug = new C300XWebrtcDebugCollector({
        getEntityId: this._getEntityId,
        getRemoteStream: () => this._remoteStream,
        isHomeCallMode: this._isHomeCallMode,
        sendSnapshot: (snapshot) => this._sendStatsDebugSnapshot(snapshot),
      });
      if (!this._statsDebug.start(pc, mediaElement)) {
        this._sendStatsDebugProbe("debug_setup_failed", {
          reason: "collector_not_started",
        });
        this._statsDebug = null;
      }
    } catch (err) {
      this._sendStatsDebugProbe("debug_setup_failed", {
        message: c300xDebugErrorMessage(err),
        reason: "module_import_failed",
      });
      return;
    }
  }

  _stopStatsDebug(reason) {
    if (this._statsDebug) {
      this._statsDebug.stop(reason);
      this._statsDebug = null;
    }
  }

  _sendStatsDebugSnapshot(snapshot) {
    this._callWs({
      type: "bticino_c300x/debug/webrtc_stats",
      snapshot,
    }).catch((_err) => {});
  }

  _sendStatsDebugProbe(event, details = {}) {
    const pc = this._pc;
    this._sendStatsDebugSnapshot({
      event,
      entity_id: this._getEntityId?.() || "",
      mode: this._isHomeCallMode?.() ? "home_call" : "doorbell",
      session_id: this._sessionId || pc?.__c300x_session_id || "",
      connection_state: pc?.connectionState || "",
      ice_connection_state: pc?.iceConnectionState || "",
      ice_gathering_state: pc?.iceGatheringState || "",
      signaling_state: pc?.signalingState || "",
      timestamp: new Date().toISOString(),
      ...details,
    });
  }

  _sendOrQueueCandidate(candidate) {
    if (!this._sessionId) {
      this._pendingCandidates.push(candidate);
      return;
    }
    this._sendCandidate(candidate);
  }

  _flushPendingCandidates() {
    const candidates = this._pendingCandidates.splice(0);
    for (const candidate of candidates) {
      this._sendCandidate(candidate);
    }
  }

  _sendCandidate(candidate) {
    this._callWs({
      type: this._webrtcCandidateCommand(),
      entity_id: this._getEntityId(),
      session_id: this._sessionId,
      candidate,
    }).catch((err) => {
      console.warn("C300X candidate failed", err);
    });
  }

  _webrtcGetClientConfigCommand() {
    return this._isHomeCallMode()
      ? "bticino_c300x/home_call/webrtc/get_client_config"
      : "camera/webrtc/get_client_config";
  }

  _webrtcOfferCommand() {
    return this._isHomeCallMode()
      ? "bticino_c300x/home_call/webrtc/offer"
      : "camera/webrtc/offer";
  }

  _webrtcCandidateCommand() {
    return this._isHomeCallMode()
      ? "bticino_c300x/home_call/webrtc/candidate"
      : "camera/webrtc/candidate";
  }

  _addRemoteCandidate(candidate) {
    if (!candidate || !this._pc) {
      return;
    }
    if (!this._pc.remoteDescription) {
      this._pendingRemoteCandidates.push(candidate);
      return;
    }
    this._pc.addIceCandidate(candidate).catch((err) => {
      console.warn("C300X remote candidate failed", err);
    });
  }

  _flushRemoteCandidates() {
    const candidates = this._pendingRemoteCandidates.splice(0);
    for (const candidate of candidates) {
      this._addRemoteCandidate(candidate);
    }
  }
}

export function c300xNormalizeRtcConfig(config) {
  const source = config?.configuration || config || {};
  const result = { ...source };
  const iceServers = result.iceServers
    || result.ice_servers
    || config?.iceServers
    || config?.ice_servers
    || config?.configuration?.iceServers
    || config?.configuration?.ice_servers;

  if (iceServers) {
    result.iceServers = iceServers;
  }

  delete result.ice_servers;
  delete result.configuration;
  return result;
}

function c300xDebugErrorMessage(err) {
  return `${err?.message || err || "unknown"}`.slice(0, 180);
}
