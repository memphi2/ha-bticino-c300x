export class C300XCardActions {
  constructor(card) {
    this._card = card;
    this._pendingDeviceActions = new Set();
  }

  deviceActionPending(key) {
    return this._pendingDeviceActions.has(key);
  }

  _currentAction(includeMedia = false) {
    const card = this._card;
    const generation = card._resourceGeneration;
    const lifecycle = card._lifecycle;
    const mediaGeneration = card._mediaGeneration;
    return () => !card._disposed && card._resourceGeneration === generation
      && card._lifecycle === lifecycle
      && (!includeMedia || card._mediaGeneration === mediaGeneration);
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
    if (card._disposed || lifecycle.hangupInProgress) {
      return;
    }
    if (!card._isHomeCallMode()) {
      if (card._lifecycle.activeHomeCallSession) {
        return;
      }
      const view = card._doorstationView();
      const action = view.action;
      if (view.actionDisabled || action === "external_call") {
        return;
      }
      if (action === "hang_up") {
        await this.hangupDoorstation();
        return;
      }
      // A pending microphone prompt must not prevent the user from hanging up.
      // Keep repeated answer/start actions coalesced after handling cancellation.
      if (lifecycle.answeringDoorbell) {
        return;
      }
      if (action === "answer") {
        const isCurrent = this._currentAction(true);
        const sameCard = this._currentAction();
        lifecycle.answeringDoorbell = true;
        try {
          await this.answerDoorbellCall();
          if (!isCurrent()) return;
          lifecycle.doorbellAnswered = true;
          card._rememberAnsweredRing?.();
          if (lifecycle.ringPreviewActive && card._webrtc.pc) {
            await card._startAnsweredDoorbellStream();
          } else {
            const started = await card._startTalkback();
            // The call is answered on the device even when the stream does
            // not start. A failed start reports its error and closes the
            // peer, which resets the peer state and ends the media
            // generation; keep the call answered so the user can still hang
            // up. A hang-up in the meantime is not such a failure.
            const startFailed = started === false && sameCard()
              && !lifecycle.hangupInProgress && (isCurrent() || !!card._error);
            if (startFailed) {
              lifecycle.doorbellAnswered = true;
              if (!isCurrent()) card._updateState();
            }
          }
        } catch (err) {
          if (isCurrent()) card._error = err?.message || `${err}`;
        } finally {
          if (isCurrent()) {
            lifecycle.answeringDoorbell = false;
            card._updateState();
          }
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
    const isCurrent = this._currentAction(true);
    if (card._disposed || card._webrtc.running || card._talkbackStarting
      || card._transitionWebrtc || lifecycle.answeringDoorbell
      || lifecycle.hangupInProgress || lifecycle.startingCall) {
      return;
    }
    card._lifecycle.startingCall = true;
    card._lifecycle.activeHomeCallSession = true;
    card._error = "";
    card._clearNotice();

    try {
      await card._startTalkback({ homeCall: true });
    } finally {
      if (isCurrent()) {
        lifecycle.startingCall = false;
        card._updateState();
      }
    }
  }

  async _withHangupGuard(run) {
    const card = this._card;
    const lifecycle = card._lifecycle;
    if (card._disposed || lifecycle.hangupInProgress) {
      return;
    }
    card._cancelPendingMediaStart?.();
    const isCurrent = this._currentAction(true);
    lifecycle.hangupInProgress = true;
    lifecycle.startingCall = false;
    let ok = true;
    try {
      ok = await run(isCurrent);
    } finally {
      if (isCurrent()) {
        lifecycle.hangupInProgress = false;
        card._closePeer(ok);
      }
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
    // Asked to hang up: no new connection for this call, even if this fails.
    if (hadDoorbellRingCallSession) card._lifecycle.answeredRingHangup = true;
    await this._withHangupGuard(async (isCurrent) => {
      let ok = true;
      try {
        // Finish this hangup on its original device even if the editor replaces
        // the card configuration while the ring-call service is pending.
        const target = card._hass
          ? { hass: card._hass, data: card._callData(), stop: this._stopTarget() } : null;
        if (hadDoorbellRingCallSession) {
          try {
            ok = await this.hangupDoorbellCall({ closePeer: false, target }) && ok;
          } catch (err) {
            console.error("C300X ring-call hangup failed", err);
            if (isCurrent()) card._error = err?.message || `${err}`;
            ok = false;
          }
        }
        if (!isCurrent()) {
          // A replacement session on this device must not inherit the old
          // session's stop command. Only continue cleanup when the card now
          // belongs to a different device and the old target is still distinct.
          let currentTarget;
          try {
            currentTarget = card._serviceData();
          } catch (_error) {
            return ok;
          }
          if (currentTarget.entity_id === target?.data.entity_id) return ok;
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
    const card = this._card;
    return card._lifecycle.doorbellAnswered || !!card._answeredRingHere?.();
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

  // The Stop doorbell video button, or null when it is disabled or missing.
  _stopTarget() {
    try {
      return this._card._stopVideoData();
    } catch (_error) {
      return null;
    }
  }

  async stopDoorbellVideo(target) {
    const card = this._card;
    const hass = target === undefined ? card._hass : target?.hass;
    if (!hass) {
      return;
    }
    const stop = target === undefined ? this._stopTarget() : target?.stop;
    if (stop) {
      await hass.callService("button", "press", stop);
      return;
    }
    // Without the button an on-demand view, a call of its own, ends by its call.
    // A ring is never hung up here: closing its preview leaves it ringing.
    const data = target === undefined ? card._callData() : target?.data;
    if (!data?.call_id || card._cameraEntity?.()?.attributes?.call_state !== "viewing") {
      return;
    }
    try {
      await hass.callService("bticino_c300x", "hangup_call", data);
    } catch (err) {
      if (err?.translation_key !== "call_not_current") throw err;
    }
  }

  async answerDoorbellCall() {
    const card = this._card;
    if (!card._hass) {
      return;
    }
    await card._hass.callService("bticino_c300x", "answer_call", card._callData());
  }

  async hangupDoorbellCall({ closePeer = true, target } = {}) {
    const card = this._card;
    const isCurrent = this._currentAction(true);
    const hass = target === undefined ? card._hass : target?.hass;
    if (!hass) {
      return false;
    }
    let ok = true;
    try {
      await hass.callService("bticino_c300x", "hangup_call", target?.data || card._callData());
    } catch (err) {
      // The call ended meanwhile: nothing left to hang up.
      if (err?.translation_key === "call_not_current") return ok;
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
