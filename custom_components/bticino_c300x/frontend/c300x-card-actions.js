export class C300XCardActions {
  constructor(card) {
    this._card = card;
    this._pendingDeviceActions = new Set();
  }

  deviceActionPending(key) {
    return this._pendingDeviceActions.has(key);
  }

  _currentAction() {
    const card = this._card;
    const generation = card._resourceGeneration;
    const lifecycle = card._lifecycle;
    return () => !card._disposed && card._resourceGeneration === generation
      && card._lifecycle === lifecycle;
  }

  async handleDeviceAction(key) {
    const card = this._card;
    if (card._disposed || card._config?.[`show_${key}`] === false) {
      return;
    }
    const entityId = card._deviceActionEntity(key);
    if (!entityId || !card._hass?.callService || this.deviceActionPending(key)
      || card._hass.states?.[entityId]?.state === "unavailable") {
      return;
    }
    this._pendingDeviceActions.add(key);
    const isCurrent = this._currentAction();
    card._error = "";
    card._clearNotice();
    card._updateState();
    try {
      await card._hass.callService("button", "press", { entity_id: entityId });
    } catch (err) {
      if (isCurrent()) card._error = err?.message || `${err}`;
    } finally {
      this._pendingDeviceActions.delete(key);
      if (isCurrent()) card._updateState();
    }
  }

  async handlePrimaryAction() {
    const card = this._card;
    const lifecycle = card._lifecycle;
    if (card._disposed || lifecycle.answeringDoorbell || lifecycle.hangupInProgress) {
      return;
    }
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
        const isCurrent = this._currentAction();
        lifecycle.answeringDoorbell = true;
        try {
          await this.answerDoorbellCall();
          if (!isCurrent()) return;
          lifecycle.doorbellAnswered = true;
          if (lifecycle.ringPreviewActive && card._webrtc.pc) {
            await card._startAnsweredDoorbellStream();
          } else {
            await card._startTalkback();
          }
        } catch (err) {
          if (isCurrent()) card._error = err?.message || `${err}`;
        } finally {
          lifecycle.answeringDoorbell = false;
          if (isCurrent()) card._updateState();
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
    if (card._disposed || !card._isAutoMode() || card._lifecycle.hangupInProgress) {
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
    const lifecycle = card._lifecycle;
    const isCurrent = this._currentAction();
    if (card._disposed || card._webrtc.running || lifecycle.startingCall) {
      return;
    }
    card._lifecycle.startingCall = true;
    card._lifecycle.activeHomeCallSession = true;
    card._error = "";
    card._clearNotice();

    try {
      await card._startTalkback({ homeCall: true });
    } finally {
      lifecycle.startingCall = false;
      if (isCurrent()) card._updateState();
    }
  }

  async _withHangupGuard(run) {
    const card = this._card;
    const lifecycle = card._lifecycle;
    const isCurrent = this._currentAction();
    if (card._disposed || lifecycle.hangupInProgress) {
      return;
    }
    lifecycle.hangupInProgress = true;
    lifecycle.startingCall = false;
    let ok = true;
    try {
      ok = await run(isCurrent);
    } finally {
      lifecycle.hangupInProgress = false;
      if (isCurrent()) card._closePeer(ok);
    }
  }

  async hangup() {
    const card = this._card;
    const homeCallMode = card._lifecycle.activeHomeCallSession || card._isHomeCallMode();
    await this._withHangupGuard(async (isCurrent) => {
      try {
        await (homeCallMode ? this.stopHomeCall() : this.stopDoorbellVideo());
        return true;
      } catch (err) {
        console.error("C300X hangup failed", err);
        if (isCurrent()) card._error = err?.message || `${err}`;
        return false;
      }
    });
  }

  async hangupDoorstation() {
    const card = this._card;
    const hadDoorbellRingCallSession = this.hasDoorbellRingCallSession();
    await this._withHangupGuard(async (isCurrent) => {
      let ok = true;
      try {
        // Finish this hangup on its original device even if the editor replaces
        // the card configuration while the ring-call service is pending.
        const target = card._hass ? { hass: card._hass, data: card._serviceData() } : null;
        if (hadDoorbellRingCallSession) {
          try {
            ok = await this.hangupDoorbellCall({ closePeer: false, target }) && ok;
          } catch (err) {
            console.error("C300X ring-call hangup failed", err);
            if (isCurrent()) card._error = err?.message || `${err}`;
            ok = false;
          }
        }
        await this.stopDoorbellVideo(target);
      } catch (err) {
        console.error("C300X doorbell video stop failed", err);
        if (isCurrent()) card._error = err?.message || `${err}`;
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
    await this._withHangupGuard(async (isCurrent) => {
      try {
        await this.stopHomeCall();
        return true;
      } catch (err) {
        console.error("C300X home-call hangup failed", err);
        if (isCurrent()) card._error = err?.message || `${err}`;
        return false;
      }
    });
  }

  async stopDoorbellVideo(target) {
    const card = this._card;
    const hass = target === undefined ? card._hass : target?.hass;
    if (!hass) {
      return;
    }
    await hass.callService("bticino_c300x", "stop_doorbell_video", target?.data || card._serviceData());
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

  async hangupDoorbellCall({ closePeer = true, target } = {}) {
    const card = this._card;
    const isCurrent = this._currentAction();
    const hass = target === undefined ? card._hass : target?.hass;
    if (!hass) {
      return false;
    }
    let ok = true;
    try {
      await hass.callService("bticino_c300x", "hangup_doorbell_call", target?.data || card._serviceData());
    } catch (err) {
      console.error("C300X ring-call hangup failed", err);
      if (isCurrent()) card._error = err?.message || `${err}`;
      ok = false;
    } finally {
      if (closePeer && isCurrent()) {
        card._closePeer(ok);
      }
    }
    return ok;
  }
}
