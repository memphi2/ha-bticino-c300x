const GAIN_NEUTRAL_DB = 0;

// Peak soft-limiter applied AFTER the makeup gain. The doorstation source is
// very quiet (~-48 dB mean), so users configure a makeup gain to lift speech
// out of the noise/quantization floor -- but a plain multiply pushes the rare
// loud peaks past full scale, where the DAC hard-clips (audible distortion).
// A gentle limiter reduces only those near-clip peaks and stays transparent
// for normal levels, so the makeup gain can be cranked without distortion.
const LIMITER_THRESHOLD_DB = -1.5;
const LIMITER_KNEE_DB = 4;
const LIMITER_RATIO = 20;
const LIMITER_ATTACK_S = 0.003;
const LIMITER_RELEASE_S = 0.25;

function gainDbToLinear(gainDb) {
  return Math.pow(10, gainDb / 20);
}

export class C300XMediaAttachment {
  constructor(mediaElement, stream, { getGainDb = null } = {}) {
    this._mediaElement = mediaElement;
    this._stream = stream;
    this._attached = false;
    this._getGainDb = getGainDb;
    this._audioContext = null;
    this._sourceNode = null;
    this._gainNode = null;
    this._limiterNode = null;
  }

  get attached() {
    return this._attached;
  }

  attach() {
    if (this._attached || !this._mediaElement) {
      return;
    }
    this._mediaElement.srcObject = this._stream;
    this._attached = true;
  }

  play() {
    if (!this._mediaElement) {
      return;
    }
    this.attach();
    this._mediaElement.autoplay = true;
    this._mediaElement.muted = false;
    this._mediaElement.volume = 1;
    this._mediaElement.play?.().catch?.(() => {});
    return this.refreshGain();
  }

  // Re-evaluate the client-side gain. gain == 0 dB means passthrough: the
  // media element plays the stream directly and Web Audio stays disengaged.
  // A non-zero gain routes the stream through a GainNode instead (the element
  // is muted so the audio is not played twice). If the AudioContext cannot be
  // built or cannot be started (autoplay policy: no user gesture yet, or the
  // per-page context limit), we fall back to passthrough so the audio stays
  // AUDIBLE rather than muting the element to a suspended/silent graph.
  async refreshGain() {
    const gainDb = this._currentGainDb();
    if (gainDb === GAIN_NEUTRAL_DB || !this._ensureAudioGraph()) {
      this._disengageGain();
      return;
    }
    try {
      await this._audioContext.resume?.();
    } catch (_error) {
      // resume rejected by the autoplay policy; the state check below handles it
    }
    if (this._currentGainDb() !== gainDb) {
      return;  // gain changed while awaiting resume; a newer call owns the state
    }
    if (this._audioContext.state && this._audioContext.state !== "running") {
      this._disengageGain();  // could not start -> audible passthrough
      return;
    }
    try {
      this._sourceNode.disconnect();
    } catch (_error) {
      // not connected yet
    }
    this._sourceNode.connect(this._gainNode);
    this._gainNode.gain.value = gainDbToLinear(gainDb);
    if (this._mediaElement) {
      this._mediaElement.muted = true;
    }
  }

  // Follow the element that actually renders the stream (e.g. when a ring
  // preview is promoted to the main video element). The Web Audio graph reads
  // from the stream, not the element, so only the muting has to move: release
  // the old element and let refreshGain mute/unmute the new one.
  retarget(mediaElement) {
    if (!mediaElement || mediaElement === this._mediaElement) {
      return;
    }
    const previousElement = this._mediaElement;
    this._mediaElement = mediaElement;
    if (previousElement) {
      previousElement.muted = false;
    }
    // If a gain graph is already engaged, mute the new element synchronously so
    // the hand-off never leaves a window where it plays the stream directly
    // while the graph also outputs it (audible double). refreshGain then
    // reconciles (and falls back to passthrough if the context can't run).
    if (this._gainNode && this._currentGainDb() !== GAIN_NEUTRAL_DB) {
      mediaElement.muted = true;
    }
    return this.refreshGain();
  }

  detach() {
    this._disengageGain();
    if (this._audioContext) {
      this._audioContext.close?.().catch?.(() => {});
    }
    this._audioContext = null;
    this._sourceNode = null;
    this._gainNode = null;
    this._limiterNode = null;
  }

  _currentGainDb() {
    if (!this._getGainDb) {
      return GAIN_NEUTRAL_DB;
    }
    const value = Number(this._getGainDb());
    return Number.isFinite(value) ? value : GAIN_NEUTRAL_DB;
  }

  _disengageGain() {
    if (this._sourceNode) {
      try {
        this._sourceNode.disconnect();
      } catch (_error) {
        // already disconnected
      }
    }
    if (this._mediaElement) {
      this._mediaElement.muted = false;
    }
  }

  _ensureAudioGraph() {
    if (this._gainNode) {
      return true;
    }
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextCtor || !this._stream) {
      return false;
    }
    // MediaStreamAudioSourceNode binds to the audio track present at creation
    // time; building it before the track arrives yields a permanently silent
    // source. Defer until the stream actually carries audio.
    const audioTracks = this._stream.getAudioTracks?.() || [];
    if (!audioTracks.length) {
      return false;
    }
    try {
      this._audioContext = new AudioContextCtor();
      this._sourceNode = this._audioContext.createMediaStreamSource(this._stream);
      this._gainNode = this._audioContext.createGain();
      // gain -> soft limiter -> destination. If the limiter cannot be built,
      // fall back to gain -> destination (the previous behaviour) so gain still
      // works; only the anti-clip safety net is lost.
      this._limiterNode = this._buildLimiter(this._audioContext);
      if (this._limiterNode) {
        this._gainNode.connect(this._limiterNode);
        this._limiterNode.connect(this._audioContext.destination);
      } else {
        this._gainNode.connect(this._audioContext.destination);
      }
    } catch (_error) {
      this._audioContext = null;
      this._sourceNode = null;
      this._gainNode = null;
      this._limiterNode = null;
      return false;
    }
    return true;
  }

  _buildLimiter(audioContext) {
    if (typeof audioContext.createDynamicsCompressor !== "function") {
      return null;
    }
    try {
      const limiter = audioContext.createDynamicsCompressor();
      limiter.threshold.value = LIMITER_THRESHOLD_DB;
      limiter.knee.value = LIMITER_KNEE_DB;
      limiter.ratio.value = LIMITER_RATIO;
      limiter.attack.value = LIMITER_ATTACK_S;
      limiter.release.value = LIMITER_RELEASE_S;
      return limiter;
    } catch (_error) {
      return null;
    }
  }
}
