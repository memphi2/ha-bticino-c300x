import { C300XMediaAttachment } from "./c300x-media-attach.js?v=e68142b744a4830f";

export class C300XWebrtcClient {
  constructor({ getHass, getEntityId, isHomeCallMode, onClosed, onTrack }) {
    this._getHass = getHass;
    this._getEntityId = getEntityId;
    this._isHomeCallMode = isHomeCallMode;
    this._onClosed = onClosed;
    this._onTrack = onTrack;
    this._pc = null;
    this._remoteStream = null;
    this._unsub = null;
    this._closing = false;
    this._pendingOfferReject = null;
    this._sessionId = "";
    this._pendingCandidates = [];
    this._pendingRemoteCandidates = [];
    this._running = false;
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

  async start({
    microphoneStream = null,
    receiveAudio = true,
    mediaElement,
    attachOnFirstTrack = false,
  }) {
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
    const mediaAttachment = new C300XMediaAttachment(mediaElement, this._remoteStream);
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

    pc.onconnectionstatechange = () => {
      if (this._closing) {
        return;
      }
      const state = pc.connectionState || pc.iceConnectionState;
      if (["closed", "disconnected", "failed"].includes(state)) {
        this._onClosed?.(state);
      }
    };

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
    if (this._pc) {
      try {
        this._pc.close();
      } catch (_err) {}
    }
    this._pc = null;
    this._running = false;

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
              this._onClosed?.(message.reason || "closed");
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
