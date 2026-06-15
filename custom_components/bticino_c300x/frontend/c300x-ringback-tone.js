const C300X_RINGBACK_DEFAULT_VOLUME = 0.12;
const C300X_RINGBACK_ON_MS = 700;
const C300X_RINGBACK_OFF_MS = 1300;

function c300xAudioContext() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  return AudioContextClass ? new AudioContextClass() : null;
}

function c300xRingbackVolume(value) {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) {
    return C300X_RINGBACK_DEFAULT_VOLUME;
  }
  return Math.min(Math.max(numberValue / 100, 0), 1);
}

export class C300XRingbackTone {
  constructor({ getEnabled, getVolume } = {}) {
    this._getEnabled = getEnabled || (() => true);
    this._getVolume = getVolume || (() => C300X_RINGBACK_DEFAULT_VOLUME * 100);
    this._context = null;
    this._gain = null;
    this._oscillators = [];
    this._timer = null;
    this._active = false;
  }

  start() {
    if (this._active || !this._getEnabled()) {
      return;
    }
    this._context = this._context || c300xAudioContext();
    if (!this._context) {
      return;
    }
    this._active = true;
    this._playPulse();
  }

  stop() {
    this._active = false;
    if (this._timer) {
      window.clearTimeout(this._timer);
      this._timer = null;
    }
    this._stopOscillators();
  }

  _playPulse() {
    if (!this._active || !this._context) {
      return;
    }
    if (this._context.state === "suspended") {
      this._context.resume().catch(() => undefined);
    }
    this._stopOscillators();
    this._gain = this._context.createGain();
    this._gain.gain.value = c300xRingbackVolume(this._getVolume());
    this._gain.connect(this._context.destination);
    this._oscillators = [440, 480].map((frequency) => {
      const oscillator = this._context.createOscillator();
      oscillator.type = "sine";
      oscillator.frequency.value = frequency;
      oscillator.connect(this._gain);
      oscillator.start();
      return oscillator;
    });
    this._timer = window.setTimeout(() => {
      this._stopOscillators();
      this._timer = window.setTimeout(() => this._playPulse(), C300X_RINGBACK_OFF_MS);
    }, C300X_RINGBACK_ON_MS);
  }

  _stopOscillators() {
    for (const oscillator of this._oscillators) {
      try {
        oscillator.stop();
      } catch (_err) {
        // Already stopped.
      }
      oscillator.disconnect();
    }
    this._oscillators = [];
    if (this._gain) {
      this._gain.disconnect();
      this._gain = null;
    }
  }
}
