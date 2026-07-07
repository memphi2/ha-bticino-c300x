export class C300XCardActions {
  constructor(card) {
    this._card = card;
  }

  async handlePrimaryAction() {
    const card = this._card;
    if (!card._isHomeCallMode()) {
      if (card._lifecycle.activeHomeCallSession) {
        return;
      }
      const action = card._doorstationView().action;
      if (action === "external_call") {
        return;
      }
      if (action === "hang_up") {
        await this.hangupDoorstation();
        return;
      }
      if (action === "answer") {
        card._lifecycle.answeringDoorbell = true;
        try {
          await this.answerDoorbellCall();
          card._lifecycle.doorbellAnswered = true;
          if (card._lifecycle.ringPreviewActive && card._webrtc.pc) {
            await card._startAnsweredDoorbellStream();
          } else {
            await card._startTalkback();
          }
        } finally {
          card._lifecycle.answeringDoorbell = false;
        }
        return;
      }
      await card._startTalkback();
      return;
    }
    if (card._isConfiguredCallActive() || card._lifecycle.startingCall) {
      await this.hangup();
      return;
    }
    await this.startHomeCallAudio();
  }

  async handleHomeCallAction() {
    const card = this._card;
    if (!card._isAutoMode()) {
      return;
    }
    if (
      card._isConfiguredCallActive()
      || card._lifecycle.activeHomeCallSession
      || card._lifecycle.startingCall
    ) {
      await this.hangupHomeCall();
      return;
    }
    await this.startHomeCallAudio();
  }

  async startHomeCallAudio() {
    const card = this._card;
    if (card._webrtc.running || card._lifecycle.startingCall) {
      return;
    }
    card._lifecycle.startingCall = true;
    card._lifecycle.activeHomeCallSession = true;
    card._error = "";
    card._clearNotice();

    try {
      await card._startTalkback({ homeCall: true });
    } finally {
      card._lifecycle.startingCall = false;
      card._updateState();
    }
  }

  async _withHangupGuard(run) {
    const card = this._card;
    if (card._lifecycle.hangupInProgress) {
      return;
    }
    card._lifecycle.hangupInProgress = true;
    card._lifecycle.startingCall = false;
    let ok = true;
    try {
      ok = await run();
    } finally {
      card._lifecycle.hangupInProgress = false;
      card._closePeer(ok);
    }
  }

  async hangup() {
    const card = this._card;
    const homeCallMode = card._lifecycle.activeHomeCallSession || card._isHomeCallMode();
    await this._withHangupGuard(async () => {
      try {
        await (homeCallMode ? this.stopHomeCall() : this.stopDoorbellVideo());
        return true;
      } catch (err) {
        console.error("C300X hangup failed", err);
        card._error = err?.message || `${err}`;
        return false;
      }
    });
  }

  async hangupDoorstation() {
    const card = this._card;
    const hadDoorbellRingCallSession = this.hasDoorbellRingCallSession();
    await this._withHangupGuard(async () => {
      let ok = true;
      try {
        if (hadDoorbellRingCallSession) {
          try {
            ok = await this.hangupDoorbellCall({ closePeer: false }) && ok;
          } catch (err) {
            console.error("C300X ring-call hangup failed", err);
            card._error = err?.message || `${err}`;
            ok = false;
          }
        }
        await this.stopDoorbellVideo();
      } catch (err) {
        console.error("C300X doorbell video stop failed", err);
        card._error = err?.message || `${err}`;
        ok = false;
      }
      return ok;
    });
  }

  hasDoorbellRingCallSession() {
    return this._card._lifecycle.doorbellAnswered;
  }

  async stopHomeCall() {
    const card = this._card;
    if (!card._hass) {
      return;
    }
    await card._hass.callService("bticino_c300x", "stop_home_call", card._serviceData());
  }

  async hangupHomeCall() {
    const card = this._card;
    await this._withHangupGuard(async () => {
      try {
        await this.stopHomeCall();
        return true;
      } catch (err) {
        console.error("C300X home-call hangup failed", err);
        card._error = err?.message || `${err}`;
        return false;
      }
    });
  }

  async stopDoorbellVideo() {
    const card = this._card;
    if (!card._hass) {
      return;
    }
    await card._hass.callService("bticino_c300x", "stop_doorbell_video", card._serviceData());
  }

  async answerDoorbellCall() {
    const card = this._card;
    if (!card._hass) {
      return;
    }
    await card._hass.callService(
      "bticino_c300x",
      "answer_doorbell_call",
      card._serviceData(),
    );
  }

  async hangupDoorbellCall({ closePeer = true } = {}) {
    const card = this._card;
    if (!card._hass) {
      return false;
    }
    let ok = true;
    try {
      await card._hass.callService("bticino_c300x", "hangup_doorbell_call", card._serviceData());
    } catch (err) {
      console.error("C300X ring-call hangup failed", err);
      card._error = err?.message || `${err}`;
      ok = false;
    } finally {
      if (closePeer) {
        card._closePeer(ok);
      }
    }
    return ok;
  }
}
