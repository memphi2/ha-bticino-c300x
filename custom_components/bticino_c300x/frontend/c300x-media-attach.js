export class C300XMediaAttachment {
  constructor(mediaElement, stream) {
    this._mediaElement = mediaElement;
    this._stream = stream;
    this._attached = false;
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
  }
}
