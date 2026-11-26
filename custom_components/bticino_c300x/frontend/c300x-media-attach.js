// The agent applies the door level and the fine adjustment to the stream, so
// the card plays the received audio as it comes, through the element.
export class C300XMediaAttachment {
  constructor(mediaElement, stream, { getPlayback = null, onPlaybackBlocked = null } = {}) {
    this._mediaElement = mediaElement;
    this._stream = stream;
    this._attached = false;
    this._getPlayback = getPlayback;
    this._onPlaybackBlocked = onPlaybackBlocked;
    this._playbackBlocked = false;
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
    this.refreshPlayback();
    this._startElement();
  }

  get playbackBlocked() { return this._playbackBlocked; }

  // Without a user gesture (iOS Safari, a notification answer) the browser
  // refuses sound: play muted so the picture runs, and let the owner ask for
  // a tap, which calls resumePlayback.
  _startElement() {
    const element = this._mediaElement;
    element?.play?.()?.catch?.((error) => {
      if (error?.name !== "NotAllowedError" || element !== this._mediaElement) return;
      this._setPlaybackBlocked(true);
      element.play?.()?.catch?.(() => {});
    });
  }

  // Call from a user gesture.
  resumePlayback() {
    if (!this._playbackBlocked || !this._mediaElement) return;
    this._setPlaybackBlocked(false);
    this._startElement();
  }

  _setPlaybackBlocked(blocked) {
    if (this._playbackBlocked === blocked) return;
    this._playbackBlocked = blocked;
    this.refreshPlayback();
    this._onPlaybackBlocked?.(blocked);
  }

  refreshPlayback() {
    const playback = this._getPlayback?.() || {};
    const value = Number(playback.volume ?? 1);
    const volume = Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 1;
    const muted = playback.muted === true;
    if (this._mediaElement) {
      this._mediaElement.volume = volume;
      this._mediaElement.muted = this._playbackBlocked || muted;
    }
  }

  // Follow the element that actually renders the stream (e.g. when a ring
  // preview is promoted to the main video element): release the old element
  // and give the new one the current volume and muting.
  retarget(mediaElement) {
    if (!mediaElement || mediaElement === this._mediaElement) {
      return;
    }
    const previousElement = this._mediaElement;
    this._mediaElement = mediaElement;
    if (previousElement) {
      previousElement.muted = false;
    }
    this.refreshPlayback();
    // The element that takes over starts on its own, without a gesture too.
    if (this._attached) this._startElement();
  }

  detach() {
    this.refreshPlayback();
  }
}
