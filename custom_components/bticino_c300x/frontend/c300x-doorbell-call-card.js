const C300X_CARD_TAG = "c300x-doorbell-call-card";
const C300X_CARD_TYPE = `custom:${C300X_CARD_TAG}`;
const C300X_CAMERA_OBJECT_ID = "bticino_c300x_doorbell_camera";
const C300X_DOORBELL_STATE_OBJECT_ID = "bticino_c300x_doorbell_state";
const C300X_DOORBELL_STATE_UNIQUE_SUFFIX = "_doorbell_state";
const C300X_DOORBELL_STATE_TRANSLATION_KEY = "doorbell_state";
const C300X_HOME_CALL_OBJECT_ID = "bticino_c300x_home_call_active";
const C300X_HOME_CALL_UNIQUE_SUFFIX = "_home_call_active";
const C300X_HOME_CALL_TRANSLATION_KEY = "home_call_active";
const C300X_DOCUMENTATION_URL = "https://github.com/memphi2/ha-bticino-c300x#doorbell-video-ring-calls-and-talkback";
const C300X_DEFAULT_CONFIG = {
  mode: "doorbell_call",
  hangup_script: "",
};

const C300X_TRANSLATIONS = {
  en: {
    answer: "Answer",
    call_home: "Call Home",
    calling: "Calling",
    camera: "Camera",
    connected: "Connected",
    card_description: "Doorbell video and Home Call controls for BTicino C300X.",
    door_station: "C300X Door Station",
    doorbell: "Doorbell",
    doorbell_call: "Doorbell / On-demand",
    doorbell_state_entity: "Doorbell state entity",
    entity: "Camera entity",
    external_call: "External Call",
    hang_up: "Hang Up",
    home_call: "Home Call",
    home_call_entity: "Home Call state entity",
    home_call_name: "C300X Home Call",
    idle: "Idle",
    mode: "Mode",
    name: "Name",
    microphone_required: "Microphone access requires HTTPS or Home Assistant Cloud",
    microphone_stream_only: "Microphone unavailable; listen only",
    no_active_door_call: "No active door call",
    no_active_home_call: "No active home-call audio",
    optional_hangup_script: "Optional hang-up script",
    stream: "Stream",
    unavailable: "Unavailable",
    unknown: "Unknown",
  },
  de: {
    answer: "Abheben",
    call_home: "Zuhause anrufen",
    calling: "Ruft an",
    camera: "Kamera",
    connected: "Verbunden",
    card_description: "Türvideo- und Home-Call-Bedienung für BTicino C300X.",
    door_station: "C300X Türstation",
    doorbell: "Türklingel",
    doorbell_call: "Türklingel / On-Demand",
    doorbell_state_entity: "Türklingel-Status-Entität",
    entity: "Kamera-Entität",
    external_call: "Externer Anruf",
    hang_up: "Auflegen",
    home_call: "Home Call",
    home_call_entity: "Home-Call-Status-Entität",
    home_call_name: "C300X Home Call",
    idle: "Idle",
    mode: "Modus",
    name: "Name",
    microphone_required: "Mikrofonzugriff benötigt HTTPS oder Home Assistant Cloud",
    microphone_stream_only: "Mikrofon nicht verfügbar; nur hören",
    no_active_door_call: "Kein aktiver Türanruf",
    no_active_home_call: "Kein aktives Home-Call-Audio",
    optional_hangup_script: "Optionales Auflegen-Script",
    stream: "Stream",
    unavailable: "Nicht verfügbar",
    unknown: "Unbekannt",
  },
  fr: {
    answer: "Répondre",
    call_home: "Appeler la maison",
    calling: "Appel en cours",
    camera: "Caméra",
    connected: "Connecté",
    card_description: "Contrôles vidéo de sonnette et Home Call pour BTicino C300X.",
    door_station: "Platine C300X",
    doorbell: "Sonnette",
    doorbell_call: "Sonnette / à la demande",
    doorbell_state_entity: "Entité d'état de sonnette",
    entity: "Entité caméra",
    external_call: "Appel externe",
    hang_up: "Raccrocher",
    home_call: "Home Call",
    home_call_entity: "Entité d'état Home Call",
    home_call_name: "Home Call C300X",
    idle: "Inactif",
    mode: "Mode",
    name: "Nom",
    microphone_required: "L'accès au microphone nécessite HTTPS ou Home Assistant Cloud",
    microphone_stream_only: "Microphone indisponible ; écoute seule",
    no_active_door_call: "Aucun appel de porte actif",
    no_active_home_call: "Aucun audio Home Call actif",
    optional_hangup_script: "Script de raccrochage optionnel",
    stream: "Stream",
    unavailable: "Indisponible",
    unknown: "Inconnu",
  },
  it: {
    answer: "Rispondi",
    call_home: "Chiama casa",
    calling: "Chiamata in corso",
    camera: "Telecamera",
    connected: "Connesso",
    card_description: "Controlli video campanello e Home Call per BTicino C300X.",
    door_station: "Postazione porta C300X",
    doorbell: "Campanello",
    doorbell_call: "Campanello / on-demand",
    doorbell_state_entity: "Entità stato campanello",
    entity: "Entità telecamera",
    external_call: "Chiamata esterna",
    hang_up: "Riaggancia",
    home_call: "Home Call",
    home_call_entity: "Entità stato Home Call",
    home_call_name: "C300X Home Call",
    idle: "Inattivo",
    mode: "Modalità",
    name: "Nome",
    microphone_required: "L'accesso al microfono richiede HTTPS o Home Assistant Cloud",
    microphone_stream_only: "Microfono non disponibile; solo ascolto",
    no_active_door_call: "Nessuna chiamata porta attiva",
    no_active_home_call: "Nessun audio Home Call attivo",
    optional_hangup_script: "Script riaggancio opzionale",
    stream: "Stream",
    unavailable: "Non disponibile",
    unknown: "Sconosciuto",
  },
};

function c300xLanguage(hass) {
  const language = (hass?.language || hass?.locale?.language || "en").toLowerCase();
  return language.split("-")[0];
}

function c300xLocalize(hass, key) {
  const language = c300xLanguage(hass);
  return (C300X_TRANSLATIONS[language] || C300X_TRANSLATIONS.en)[key] || C300X_TRANSLATIONS.en[key] || key;
}

function c300xFireConfigChanged(element, config) {
  element.dispatchEvent(new CustomEvent("config-changed", {
    detail: { config },
    bubbles: true,
    composed: true,
  }));
}

function c300xObjectSuffix(objectId, baseObjectId) {
  if (objectId === baseObjectId) {
    return "";
  }
  if (objectId?.startsWith(`${baseObjectId}_`)) {
    return objectId.slice(baseObjectId.length);
  }
  return null;
}

function c300xEntityId(domain, baseObjectId, suffix) {
  return `${domain}.${baseObjectId}${suffix || ""}`;
}

class C300XDoorbellCallCard extends HTMLElement {
  static getStubConfig(hass, entityId) {
    const entity = entityId || C300XDoorbellCallCard._firstEntity(
      hass,
      "camera",
      C300X_CAMERA_OBJECT_ID,
    );
    return {
      entity: entity || c300xEntityId("camera", C300X_CAMERA_OBJECT_ID),
      ...C300X_DEFAULT_CONFIG,
    };
  }

  static getConfigElement() {
    return document.createElement("c300x-doorbell-call-card-editor");
  }

  static getEntitySuggestion(hass, entityId) {
    const [domain, objectId] = entityId.split(".");
    if (!domain || !objectId) {
      return null;
    }

    if (domain === "camera") {
      const suffix = c300xObjectSuffix(objectId, C300X_CAMERA_OBJECT_ID);
      if (suffix === null) {
        return null;
      }
      return [
        {
          label: c300xLocalize(hass, "doorbell_call"),
          config: {
            type: C300X_CARD_TYPE,
            ...C300XDoorbellCallCard.getStubConfig(hass, entityId),
          },
        },
        {
          label: c300xLocalize(hass, "home_call"),
          config: {
            type: C300X_CARD_TYPE,
            ...C300XDoorbellCallCard.getStubConfig(hass, entityId),
            mode: "home_call",
          },
        },
      ];
    }

    if (domain === "sensor") {
      const suffix = c300xObjectSuffix(objectId, C300X_DOORBELL_STATE_OBJECT_ID);
      if (
        suffix === null
        && !C300XDoorbellCallCard._isRegistryEntity(
          hass,
          entityId,
          C300X_DOORBELL_STATE_UNIQUE_SUFFIX,
          C300X_DOORBELL_STATE_TRANSLATION_KEY,
        )
      ) {
        return null;
      }
      return {
        config: {
          type: C300X_CARD_TYPE,
          ...C300XDoorbellCallCard.getStubConfig(
            hass,
            C300XDoorbellCallCard._relatedCameraFromEntity(hass, entityId, suffix),
          ),
          doorbell_state_entity: entityId,
        },
      };
    }

    if (domain === "binary_sensor") {
      const suffix = c300xObjectSuffix(objectId, C300X_HOME_CALL_OBJECT_ID);
      if (
        suffix === null
        && !C300XDoorbellCallCard._isRegistryEntity(
          hass,
          entityId,
          C300X_HOME_CALL_UNIQUE_SUFFIX,
          C300X_HOME_CALL_TRANSLATION_KEY,
        )
      ) {
        return null;
      }
      return {
        config: {
          type: C300X_CARD_TYPE,
          ...C300XDoorbellCallCard.getStubConfig(
            hass,
            C300XDoorbellCallCard._relatedCameraFromEntity(hass, entityId, suffix),
          ),
          mode: "home_call",
          home_call_entity: entityId,
        },
      };
    }

    return null;
  }

  static _isRegistryEntity(hass, entityId, uniqueSuffix, translationKey) {
    const entity = hass?.entities?.[entityId] || {};
    const uniqueId = entity.unique_id || entity.uniqueId || "";
    return entity.translation_key === translationKey
      || entity.translationKey === translationKey
      || (uniqueSuffix && uniqueId.endsWith(uniqueSuffix));
  }

  static _relatedCameraFromEntity(hass, entityId, suffix) {
    if (suffix !== null) {
      return c300xEntityId("camera", C300X_CAMERA_OBJECT_ID, suffix);
    }
    const entryId = hass?.entities?.[entityId]?.config_entry_id;
    if (!entryId) {
      return c300xEntityId("camera", C300X_CAMERA_OBJECT_ID);
    }
    return C300XDoorbellCallCard._firstRelatedCameraEntityId(hass, entryId)
      || c300xEntityId("camera", C300X_CAMERA_OBJECT_ID);
  }

  static _firstRelatedCameraEntityId(hass, entryId) {
    const entities = hass?.entities || {};
    for (const entityId of Object.keys(entities)) {
      if (entities[entityId]?.config_entry_id !== entryId) {
        continue;
      }
      const [domain, objectId] = entityId.split(".");
      if (domain === "camera" && objectId?.startsWith(C300X_CAMERA_OBJECT_ID)) {
        return entityId;
      }
    }
    return null;
  }

  static _firstEntity(hass, domain, prefix) {
    return Object.keys(hass?.states || {}).find((entityId) => {
      const [entityDomain, objectId] = entityId.split(".");
      return entityDomain === domain && objectId?.startsWith(prefix);
    });
  }

  getGridOptions() {
    if (this._isHomeCallMode()) {
      return {
        rows: 1,
        columns: 6,
        min_rows: 1,
        max_rows: 1,
        min_columns: 3,
      };
    }
    return {
      rows: 5,
      columns: 12,
      min_rows: 5,
      max_rows: 5,
      min_columns: 6,
    };
  }

  setConfig(config) {
    this._config = {
      ...C300X_DEFAULT_CONFIG,
      ...config,
      entity: config.entity || c300xEntityId("camera", C300X_CAMERA_OBJECT_ID),
    };
    this._remoteStream = null;
    this._micStream = null;
    this._pc = null;
    this._webrtcUnsub = null;
    this._pendingOfferReject = null;
    this._sessionId = "";
    this._pendingCandidates = [];
    this._pendingRemoteCandidates = [];
    this._running = false;
    this._startingCall = false;
    this._previewStarting = false;
    this._answeringDoorbell = false;
    this._ringPreviewActive = false;
    this._error = "";
    this._notice = "";
    this._ensureRendered();
  }

  set hass(hass) {
    this._hass = hass;
    this._ensureRendered();
    this._updateState();
  }

  disconnectedCallback() {
    this._closePeer(false);
  }

  getCardSize() {
    return this._isHomeCallMode() ? 1 : 7;
  }

  _ensureRendered() {
    if (!this._config || this.shadowRoot) {
      return;
    }

    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100%;
        }
        ha-card {
          overflow: hidden;
          height: 100%;
          display: flex;
          flex-direction: column;
        }
        .media {
          position: relative;
          width: 100%;
          flex: 1 1 auto;
          background: #111;
          min-height: 0;
        }
        video {
          width: 100%;
          height: 100%;
          object-fit: contain;
          display: block;
          background: #111;
        }
        .remote-audio {
          position: absolute;
          width: 1px;
          height: 1px;
          opacity: 0;
          pointer-events: none;
        }
        .empty {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--secondary-text-color);
          font-size: 14px;
          pointer-events: none;
        }
        .body {
          min-height: 48px;
          padding: 4px 16px;
          display: flex;
          align-items: center;
          flex: 0 0 auto;
        }
        .entity-main {
          display: flex;
          align-items: center;
          min-width: 0;
          flex: 1 1 auto;
        }
        .row-action {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 40px;
          height: 40px;
          margin: 0 16px 0 0;
          padding: 0;
          border: 0;
          color: var(--state-icon-color);
          background: color-mix(in srgb, var(--state-icon-color) 14%, transparent);
          flex: 0 0 auto;
          --mdc-icon-size: 24px;
          border-radius: 50%;
          cursor: pointer;
          font: inherit;
          transition: background-color 140ms ease, color 140ms ease, transform 140ms ease;
        }
        .row-action.active {
          color: var(--primary-color);
          background: color-mix(in srgb, var(--primary-color) 18%, transparent);
        }
        .row-action.dialing,
        .row-action.answerable {
          color: var(--warning-color, var(--primary-color));
          background: color-mix(in srgb, var(--warning-color, var(--primary-color)) 20%, transparent);
          animation: c300x-ring 900ms ease-in-out infinite, c300x-answer-glow 1400ms ease-in-out infinite;
        }
        .row-action.recording {
          position: relative;
          color: var(--error-color);
          background: color-mix(in srgb, var(--error-color) 18%, transparent);
          animation: c300x-record-breathe 1300ms ease-in-out infinite;
        }
        .row-action.blocked {
          color: var(--disabled-text-color);
          background: color-mix(in srgb, var(--disabled-text-color) 14%, transparent);
          cursor: default;
        }
        .row-action.recording::after {
          content: "";
          position: absolute;
          top: 7px;
          right: 7px;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--error-color);
          box-shadow: 0 0 0 0 color-mix(in srgb, var(--error-color) 45%, transparent);
          animation: c300x-record-dot 1100ms ease-out infinite;
        }
        @keyframes c300x-ring {
          0%, 100% { transform: rotate(0deg) scale(1); }
          18% { transform: rotate(-12deg) scale(1.03); }
          36% { transform: rotate(10deg) scale(1.03); }
          54% { transform: rotate(-7deg) scale(1.02); }
          72% { transform: rotate(5deg) scale(1.01); }
        }
        @keyframes c300x-answer-glow {
          0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--warning-color, var(--primary-color)) 0%, transparent); }
          45% { box-shadow: 0 0 0 8px color-mix(in srgb, var(--warning-color, var(--primary-color)) 18%, transparent); }
        }
        @keyframes c300x-record-breathe {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(1.05); }
        }
        @keyframes c300x-record-dot {
          0% { opacity: 1; box-shadow: 0 0 0 0 color-mix(in srgb, var(--error-color) 45%, transparent); }
          100% { opacity: .35; box-shadow: 0 0 0 8px color-mix(in srgb, var(--error-color) 0%, transparent); }
        }
        .row-action:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }
        .action-icon {
          display: flex;
        }
        .entity-text {
          min-width: 0;
        }
        .title {
          font-size: 14px;
          font-weight: 400;
          line-height: 20px;
          color: var(--primary-text-color);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .secondary {
          color: var(--secondary-text-color);
          font-size: 13px;
          line-height: 18px;
        }
        .secondary.error {
          color: var(--error-color);
        }
        .secondary.notice {
          color: var(--warning-color, var(--secondary-text-color));
        }
      </style>
      <ha-card>
        <audio class="remote-audio" autoplay playsinline></audio>
        <div class="media">
          <video playsinline autoplay></video>
          <div class="empty"></div>
        </div>
        <div class="body">
          <div class="entity-main">
            <button class="row-action" type="button">
              <ha-icon class="action-icon" icon="mdi:phone"></ha-icon>
            </button>
            <div class="entity-text">
              <div class="title"></div>
              <div class="secondary"></div>
            </div>
          </div>
        </div>
      </ha-card>
    `;

    this._videoEl = root.querySelector("video");
    this._audioEl = root.querySelector("audio");
    this._mediaEl = root.querySelector(".media");
    this._emptyEl = root.querySelector(".empty");
    this._bodyEl = root.querySelector(".body");
    this._actionButtonEl = root.querySelector(".row-action");
    this._actionIconEl = root.querySelector(".action-icon");
    this._titleEl = root.querySelector(".title");
    this._secondaryEl = root.querySelector(".secondary");

    this._actionButtonEl.addEventListener("click", () => this._handlePrimaryAction());
    this._updateState();
  }

  _updateState() {
    if (!this.shadowRoot || !this._config) {
      return;
    }

    const homeCallMode = this._isHomeCallMode();
    const entity = this._hass?.states?.[this._config.entity];
    const stateEntity = this._hass?.states?.[this._stateEntityId()];
    const name = this._displayName(entity);
    const callActive = homeCallMode && this._isStateOn(stateEntity);
    const homeCallConnected = callActive && !!stateEntity?.attributes?.answered;
    const doorstationActive = !homeCallMode && (this._running || !!this._remoteStream);
    const doorstationAction = this._doorstationAction(stateEntity, entity, doorstationActive);
    const doorstationActionLabel = this._label(doorstationAction);

    this._titleEl.textContent = name;
    this._emptyEl.textContent = this._label(homeCallMode ? "no_active_home_call" : "no_active_door_call");
    this._bodyEl.classList.toggle("home-call", homeCallMode);
    this._bodyEl.classList.toggle("doorstation", !homeCallMode);
    const actionActive = homeCallMode
      ? (callActive || this._startingCall)
      : (doorstationActive || doorstationAction === "answer");
    const action = homeCallMode ? ((callActive || this._startingCall) ? "hang_up" : "call_home") : doorstationAction;
    const actionLabel = homeCallMode ? this._label(action) : doorstationActionLabel;
    const actionIcon = homeCallMode
      ? ((callActive || this._startingCall) ? "mdi:phone-hangup" : "mdi:phone")
      : (
        action === "hang_up"
          ? "mdi:phone-hangup"
          : (action === "answer" ? "mdi:phone-in-talk" : (action === "external_call" ? "mdi:phone-off" : "mdi:play"))
      );
    this._actionIconEl.setAttribute("icon", actionIcon);
    this._actionButtonEl.title = actionLabel;
    this._actionButtonEl.setAttribute("aria-label", actionLabel);
    this._actionButtonEl.disabled = action === "external_call";
    this._actionButtonEl.classList.toggle("active", actionActive);
    this._actionButtonEl.classList.toggle(
      "dialing",
      (homeCallMode && callActive && !homeCallConnected)
        || (!homeCallMode && doorstationAction === "answer"),
    );
    this._actionButtonEl.classList.toggle("answerable", !homeCallMode && doorstationAction === "answer");
    this._actionButtonEl.classList.toggle("blocked", !homeCallMode && doorstationAction === "external_call");
    this._actionButtonEl.classList.toggle(
      "recording",
      homeCallConnected || (!homeCallMode && doorstationActive),
    );
    this._secondaryEl.textContent = this._error
      || this._notice
      || (homeCallMode ? this._homeCallStatusText(stateEntity) : doorstationActionLabel);
    this._secondaryEl.classList.toggle("error", !!this._error);
    this._secondaryEl.classList.toggle("notice", !this._error && !!this._notice);
    this._mediaEl.style.display = homeCallMode ? "none" : "";
    this._emptyEl.style.display = this._remoteStream ? "none" : "";
    if (!homeCallMode && doorstationAction === "answer") {
      this._ensureDoorbellPreview();
    }
  }

  async _handlePrimaryAction() {
    if (!this._isHomeCallMode()) {
      const stateEntity = this._hass?.states?.[this._stateEntityId()];
      const action = this._doorstationAction(
        stateEntity,
        this._hass?.states?.[this._config.entity],
        this._running || !!this._remoteStream,
      );
      if (action === "external_call") {
        return;
      }
      if (action === "hang_up") {
        await this._hangupDoorstation();
        return;
      }
      if (action === "answer") {
        this._answeringDoorbell = true;
        try {
          this._closePeer(true, { keepMediaElement: true });
          await this._answerDoorbellCall();
          await this._startTalkback();
        } finally {
          this._answeringDoorbell = false;
        }
        return;
      }
      await this._startTalkback();
      return;
    }
    if (this._isConfiguredCallActive() || this._startingCall) {
      await this._hangup();
      return;
    }
    await this._startHomeCallAudio();
  }

  async _startHomeCallAudio() {
    if (this._running || this._startingCall) {
      return;
    }
    this._startingCall = true;
    this._error = "";
    this._notice = "";

    try {
      await this._startTalkback();
    } finally {
      this._startingCall = false;
      this._updateState();
    }
  }

  async _ensureDoorbellPreview() {
    if (this._running || this._previewStarting || this._answeringDoorbell) {
      return;
    }
    this._previewStarting = true;
    try {
      await this._startTalkback({ microphone: false, receiveAudio: false });
      if (this._remoteStream && !this._error) {
        this._ringPreviewActive = true;
        this._updateState();
      }
    } finally {
      this._previewStarting = false;
    }
  }

  async _startTalkback({ microphone = true, receiveAudio = true } = {}) {
    if (this._running) {
      return;
    }
    this._running = true;
    this._error = "";
    this._notice = "";

    try {
      if (microphone) {
        await this._prepareMicrophone();
      } else {
        this._micStream = null;
      }

      const clientConfig = await this._callWs({
        type: this._webrtcGetClientConfigCommand(),
        entity_id: this._config.entity,
      });
      const rtcConfig = this._normalizeRtcConfig(clientConfig);
      this._remoteStream = new MediaStream();
      const mediaElement = this._isHomeCallMode() ? this._audioEl : this._videoEl;
      mediaElement.srcObject = this._remoteStream;

      const pc = new RTCPeerConnection(rtcConfig);
      this._pc = pc;

      if (!this._isHomeCallMode()) {
        pc.addTransceiver("video", { direction: "recvonly" });
      }
      if (this._micStream) {
        for (const track of this._micStream.getAudioTracks()) {
          pc.addTrack(track, this._micStream);
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
        mediaElement.autoplay = true;
        mediaElement.muted = false;
        mediaElement.volume = 1;
        mediaElement.play().catch(() => {});
        this._updateState();
      };

      pc.onicecandidate = (event) => {
        if (!event.candidate) {
          return;
        }
        this._sendOrQueueCandidate(event.candidate.toJSON());
      };

      pc.onconnectionstatechange = () => {
        const state = pc.connectionState || pc.iceConnectionState;
        if (["closed", "disconnected", "failed"].includes(state)) {
          this._handleWebrtcClosed(state);
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
    } catch (err) {
      if (err?.message === "HA WebRTC offer cancelled") {
        this._closePeer(true);
        return;
      }
      console.error("C300X talkback failed", err);
      this._error = err?.message || `${err}`;
      this._closePeer(false);
    } finally {
      this._running = !!this._pc;
      this._updateState();
    }
  }

  async _prepareMicrophone() {
    const mediaDevices = globalThis.navigator?.mediaDevices;
    const getUserMedia = mediaDevices?.getUserMedia;
    if (typeof getUserMedia !== "function") {
      this._notice = this._label("microphone_required");
      return;
    }
    try {
      this._micStream = await getUserMedia.call(mediaDevices, {
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
    } catch (err) {
      console.warn("C300X microphone unavailable; starting receive-only stream", err);
      this._notice = this._label("microphone_stream_only");
    }
  }

  async _hangup() {
    this._startingCall = false;
    let ok = true;
    try {
      if (this._isHomeCallMode()) {
        await this._stopHomeCall();
      } else {
        await this._stopDoorbellVideo();
      }
    } catch (err) {
      console.error("C300X hangup failed", err);
      this._error = err?.message || `${err}`;
      ok = false;
    } finally {
      this._closePeer(ok);
    }
  }

  async _hangupDoorstation() {
    this._startingCall = false;
    let ok = true;
    try {
      await this._hangupDoorbellCall({ closePeer: false });
    } catch (err) {
      console.error("C300X ring-call hangup failed", err);
      ok = false;
    }
    try {
      await this._stopDoorbellVideo();
    } catch (err) {
      console.error("C300X doorbell video stop failed", err);
      this._error = err?.message || `${err}`;
      ok = false;
    } finally {
      this._closePeer(ok);
    }
  }

  _closePeer(clearStatus, options = {}) {
    if (this._pc) {
      try {
        this._pc.close();
      } catch (_err) {}
    }
    this._pc = null;
    this._running = false;

    if (this._webrtcUnsub) {
      this._webrtcUnsub();
      this._webrtcUnsub = null;
    }
    this._sessionId = "";
    this._pendingCandidates = [];
    this._pendingRemoteCandidates = [];
    if (this._pendingOfferReject) {
      const reject = this._pendingOfferReject;
      this._pendingOfferReject = null;
      reject(new Error("HA WebRTC offer cancelled"));
    }

    if (this._micStream) {
      for (const track of this._micStream.getTracks()) {
        track.stop();
      }
    }
    this._micStream = null;

    if (this._remoteStream) {
      for (const track of this._remoteStream.getTracks()) {
        track.stop();
      }
    }
    this._remoteStream = null;
    this._ringPreviewActive = false;
    if (this._videoEl && !options.keepMediaElement) {
      this._videoEl.srcObject = null;
    }
    if (this._audioEl && !options.keepMediaElement) {
      this._audioEl.srcObject = null;
    }
    this._notice = "";
    if (clearStatus) {
      this._error = "";
    }
    this._updateState();
  }

  _handleWebrtcClosed(reason) {
    if (!this._pc && !this._remoteStream && !this._running) {
      return;
    }
    this._closePeer(false);
  }

  _isHomeCallMode() {
    return this._config?.mode === "home_call";
  }

  _stateEntityId() {
    return this._isHomeCallMode()
      ? (this._config.home_call_entity || this._autoRelatedEntityId(
        "binary_sensor",
        C300X_HOME_CALL_OBJECT_ID,
        C300X_HOME_CALL_UNIQUE_SUFFIX,
        C300X_HOME_CALL_TRANSLATION_KEY,
      ))
      : (this._config.doorbell_state_entity || this._autoRelatedEntityId(
        "sensor",
        C300X_DOORBELL_STATE_OBJECT_ID,
        C300X_DOORBELL_STATE_UNIQUE_SUFFIX,
        C300X_DOORBELL_STATE_TRANSLATION_KEY,
      ));
  }

  _autoRelatedEntityId(domain, baseObjectId, uniqueSuffix, translationKey) {
    const entryId = this._hass?.entities?.[this._config?.entity]?.config_entry_id;
    if (entryId) {
      const relatedEntityId = this._firstRelatedEntityId(
        domain,
        baseObjectId,
        entryId,
        uniqueSuffix,
        translationKey,
      );
      if (relatedEntityId) {
        return relatedEntityId;
      }
    }
    return this._relatedEntityId(domain, baseObjectId);
  }

  _firstRelatedEntityId(domain, baseObjectId, entryId, uniqueSuffix, translationKey) {
    const entities = this._hass?.entities || {};
    let fallback = "";
    for (const entityId of Object.keys(entities)) {
      const registryEntity = entities[entityId] || {};
      if (registryEntity.config_entry_id !== entryId) {
        continue;
      }
      const [entityDomain, objectId] = entityId.split(".");
      if (entityDomain !== domain) {
        continue;
      }
      const uniqueId = registryEntity.unique_id || registryEntity.uniqueId || "";
      const registryMatch = registryEntity.translation_key === translationKey
        || registryEntity.translationKey === translationKey
        || (uniqueSuffix && uniqueId.endsWith(uniqueSuffix));
      const objectIdMatch = objectId?.startsWith(baseObjectId);
      if (!registryMatch && !objectIdMatch) {
        continue;
      }
      if (objectId === baseObjectId || registryMatch) {
        return entityId;
      }
      if (!fallback || entityId.localeCompare(fallback) < 0) {
        fallback = entityId;
      }
    }
    return fallback;
  }

  _relatedEntityId(domain, baseObjectId) {
    const entityId = this._config?.entity || "";
    const objectId = entityId.split(".")[1] || "";
    const suffix = c300xObjectSuffix(objectId, C300X_CAMERA_OBJECT_ID);
    if (suffix !== null) {
      return c300xEntityId(domain, baseObjectId, suffix);
    }
    return c300xEntityId(domain, baseObjectId);
  }

  _displayName(entity) {
    if (entity && this._hass?.formatEntityName) {
      try {
        if (this._config.name || this._isHomeCallMode()) {
          return this._hass.formatEntityName(
            entity,
            this._config.name || this._defaultName(),
            { separator: " " },
          );
        }
        return this._hass.formatEntityName(entity);
      } catch (err) {
        console.warn("C300X entity name formatting failed", err);
      }
    }
    if (typeof this._config.name === "string") {
      return this._config.name;
    }
    return entity?.attributes?.friendly_name || this._defaultName();
  }

  _entryId() {
    if (this._config.entry_id) {
      return this._config.entry_id;
    }
    return this._hass?.entities?.[this._config.entity]?.config_entry_id
      || this._hass?.entities?.[this._stateEntityId()]?.config_entry_id
      || "";
  }

  _serviceData() {
    const entryId = this._entryId();
    return entryId ? { entry_id: entryId } : {};
  }

  _isConfiguredCallActive() {
    return this._isStateOn(this._hass?.states?.[this._stateEntityId()]);
  }

  _isStateOn(entity) {
    return entity?.state === "on";
  }

  _homeCallStatusText(entity) {
    if (!entity) {
      return this._label("unknown");
    }
    if (entity.state === "unavailable") {
      return this._label("unavailable");
    }
    if (entity.state === "unknown") {
      return this._label("unknown");
    }
    if (entity.state === "on") {
      return this._label(entity.attributes?.answered ? "connected" : "calling");
    }
    if (entity.state === "off") {
      return this._label("idle");
    }
    return entity.state;
  }

  _doorstationAction(entity, cameraEntity, active) {
    if (this._isExternalDoorstationMedia(cameraEntity)) {
      return "external_call";
    }
    if (this._isRingCallPending(entity, cameraEntity)) {
      return "answer";
    }
    if (this._isRingPreviewAvailable(cameraEntity)) {
      if (this._previewStarting || this._ringPreviewActive) {
        return "answer";
      }
      return active ? "hang_up" : "answer";
    }
    if (active) {
      return "hang_up";
    }
    if (this._isRingCallAvailable(entity, cameraEntity)) {
      return "hang_up";
    }
    return "stream";
  }

  _isRingCallPending(entity, cameraEntity) {
    const state = entity?.state;
    return (state === "ringing" || state === "doorbell_pressed")
      && !this._isExternalDoorstationMedia(cameraEntity);
  }

  _isRingPreviewAvailable(cameraEntity) {
    const attributes = cameraEntity?.attributes || {};
    return attributes.video_owner === "ring"
      && !this._isExternalDoorstationMedia(cameraEntity);
  }

  _isRingCallAvailable(entity, cameraEntity) {
    const state = entity?.state;
    const attributes = cameraEntity?.attributes || {};
    return (state === "ringing" || state === "doorbell_pressed" || state === "view_requested")
      && attributes.video_owner === "ring";
  }

  _isExternalDoorstationMedia(cameraEntity) {
    const attributes = cameraEntity?.attributes || {};
    return attributes.external_media_active === true
      || attributes.video_owner === "external_media"
      || attributes.external_owner === "external_media";
  }

  _defaultName() {
    return this._label(this._isHomeCallMode() ? "home_call_name" : "door_station");
  }

  _label(key) {
    return c300xLocalize(this._hass, key);
  }

  async _stopHomeCall() {
    if (!this._hass) {
      return;
    }
    await this._hass.callService("bticino_c300x", "stop_home_call", this._serviceData());
  }

  async _stopDoorbellVideo() {
    if (!this._hass) {
      return;
    }
    if (this._config.hangup_script) {
      await this._runScript(this._config.hangup_script);
      return;
    }
    await this._hass.callService("bticino_c300x", "stop_doorbell_video", this._serviceData());
  }

  async _answerDoorbellCall() {
    if (!this._hass) {
      return;
    }
    await this._hass.callService("bticino_c300x", "answer_doorbell_call", {
      ...this._serviceData(),
      audio: true,
    });
  }

  async _hangupDoorbellCall({ closePeer = true } = {}) {
    if (!this._hass) {
      return;
    }
    let ok = true;
    try {
      await this._hass.callService("bticino_c300x", "hangup_doorbell_call", this._serviceData());
    } catch (err) {
      console.error("C300X ring-call hangup failed", err);
      this._error = err?.message || `${err}`;
      ok = false;
    } finally {
      if (closePeer) {
        this._closePeer(ok);
      }
    }
  }

  async _runScript(entityId) {
    if (!entityId || !this._hass) {
      return;
    }
    await this._hass.callService("script", "turn_on", {}, { entity_id: entityId });
  }

  async _callWs(message) {
    if (!this._hass?.callWS) {
      throw new Error("Home Assistant WebSocket is not available");
    }
    return this._hass.callWS(message);
  }

  async _subscribeWebrtcOffer(offer) {
    if (!this._hass?.connection?.subscribeMessage) {
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

      this._hass.connection
        .subscribeMessage(
          (message) => {
            if (!message) {
              return;
            }
            if (message.type === "closed") {
              this._handleWebrtcClosed(message.reason || "closed");
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
            entity_id: this._config.entity,
            offer,
          },
          { resubscribe: false },
        )
        .then((unsub) => {
          this._webrtcUnsub = unsub;
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
      entity_id: this._config.entity,
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

  _normalizeRtcConfig(config) {
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
}

class C300XDoorbellCallCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = {
      ...C300XDoorbellCallCard.getStubConfig(this._hass),
      ...config,
    };
    this._render();
  }

  set hass(hass) {
    const languageChanged = c300xLanguage(this._hass) !== c300xLanguage(hass);
    this._hass = hass;
    if (!this.shadowRoot || languageChanged) {
      this._render();
      return;
    }
    const form = this.shadowRoot.querySelector("ha-form");
    if (form) {
      form.hass = hass;
    }
  }

  _render() {
    if (!this._config || !this._hass) {
      return;
    }
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    const homeCallMode = this._config.mode === "home_call";
    root.innerHTML = `
      <ha-form></ha-form>
    `;

    const form = root.querySelector("ha-form");
    form.hass = this._hass;
    form.data = this._config;
    form.schema = [
      {
        name: "mode",
        required: true,
        selector: {
          select: {
            mode: "dropdown",
            options: [
              { value: "doorbell_call", label: this._label("doorbell_call") },
              { value: "home_call", label: this._label("home_call") },
            ],
          },
        },
      },
      {
        name: "entity",
        required: true,
        selector: { entity: { domain: "camera" } },
      },
      {
        name: "name",
        selector: { entity_name: {} },
        context: { entity: "entity" },
      },
      ...(homeCallMode ? [] : [{
        name: "hangup_script",
        selector: { entity: { domain: "script" } },
      },
      {
        name: "doorbell_state_entity",
        selector: { entity: { domain: "sensor" } },
      }]),
      ...(homeCallMode ? [{
        name: "home_call_entity",
        selector: { entity: { domain: "binary_sensor" } },
      }] : []),
    ];
    form.computeLabel = (schema) => this._label(
      schema.name === "hangup_script" ? "optional_hangup_script" : schema.name,
    );
    form.addEventListener("value-changed", (event) => {
      this._setConfig(event.detail.value || {});
    });
  }

  _setConfig(config) {
    const nextConfig = { ...config };
    const modeChanged = this._config.mode !== nextConfig.mode;
    for (const [key, value] of Object.entries(nextConfig)) {
      if (key !== "entity" && value === "") {
        delete nextConfig[key];
      }
    }
    if (nextConfig.mode === "home_call") {
      delete nextConfig.hangup_script;
      delete nextConfig.doorbell_state_entity;
    } else {
      delete nextConfig.home_call_entity;
    }
    if (JSON.stringify(this._config) === JSON.stringify(nextConfig)) {
      return;
    }
    this._config = nextConfig;
    c300xFireConfigChanged(this, nextConfig);
    if (modeChanged) {
      this._render();
    }
  }

  _label(key) {
    return c300xLocalize(this._hass, key);
  }
}

if (!customElements.get("c300x-doorbell-call-card-editor")) {
  customElements.define("c300x-doorbell-call-card-editor", C300XDoorbellCallCardEditor);
}
if (!customElements.get(C300X_CARD_TAG)) {
  customElements.define(C300X_CARD_TAG, C300XDoorbellCallCard);
}

window.customCards = window.customCards || [];
window.customCards = window.customCards.filter((card) => card.type !== C300X_CARD_TAG);
window.customCards.push({
  type: C300X_CARD_TAG,
  name: "C300X Doorbell Call Card",
  preview: true,
  description: C300X_TRANSLATIONS.en.card_description,
  documentationURL: C300X_DOCUMENTATION_URL,
  getEntitySuggestion: (hass, entityId) => C300XDoorbellCallCard.getEntitySuggestion(hass, entityId),
});
