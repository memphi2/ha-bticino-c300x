import "/frontend/c300x-doorbell-call-card.js";

// HA host elements and transport are fixtures; card/RTC/media DOM are real.
customElements.define("ha-icon", class extends HTMLElement {
  connectedCallback() { this.style.cssText = "display:block;width:24px;height:24px"; }
});
const camera = "camera.synthetic_door";
const source = document.createElement("canvas");
source.width = 320;
source.height = 240;
const context = source.getContext("2d");
let frame = 0;
const paint = () => {
  context.fillStyle = frame++ % 2 ? "#148833" : "#2244bb";
  context.fillRect(0, 0, 320, 240);
  context.fillStyle = "#efdc22";
  context.fillRect(40, 40, 140, 100);
};
paint();
const timer = setInterval(paint, 100);
const calls = [];
const peers = new Map();
const listeners = new Set();
let nextSession = 0;
const key = (translation_key) => ({ device_id: "device-one", platform: "bticino_c300x", translation_key });
const hass = {
  language: "de",
  devices: { "device-one": { config_entry_id: "entry-one" } },
  entities: {
    [camera]: key("doorbell_camera"),
    "button.synthetic_door": key("door"),
    "button.synthetic_light": key("stair_light"),
    "button.synthetic_stop_video": key("stop_doorbell_video"),
  },
  states: {
    [camera]: { state: "idle", attributes: { friendly_name: "Synthetic door", media_state: "idle", media_primary_action: "start_stream", door_entity_id: "button.synthetic_door" } },
    "button.synthetic_door": { state: "unknown", attributes: {} },
    "button.synthetic_stop_video": { state: "unknown", attributes: {} },
    "button.synthetic_light": { state: "unknown", attributes: {} },
  },
  formatEntityName: (entity) => entity.attributes.friendly_name,
  callService: async (domain, service, data) => { calls.push({ domain, service, data }); },
  callWS: async (message) => {
    if (message.type.endsWith("/get_client_config")) return { configuration: { iceServers: [] } };
    if (message.type.endsWith("/candidate")) {
      await peers.get(message.session_id)?.pc.addIceCandidate(message.candidate);
      return {};
    }
    if (message.type === "bticino_c300x/debug/status") return { webrtc_stats: false };
    throw new Error(`Unexpected WS command ${message.type}`);
  },
  connection: {
    subscribeEvents: async (callback) => { listeners.add(callback); return () => listeners.delete(callback); },
    subscribeMessage: async (callback, message) => {
      const homeCall = message.type === "bticino_c300x/home_call/webrtc/offer";
      if (!homeCall && message.type !== "camera/webrtc/offer") throw new Error("Unexpected offer command");
      const id = `synthetic-${++nextSession}`;
      const pc = new RTCPeerConnection({ iceServers: [] });
      const stream = homeCall ? new MediaStream() : source.captureStream(10);
      let audio;
      if (window.lab?.withAudio) {
        audio = new AudioContext();
        const oscillator = audio.createOscillator();
        const destination = audio.createMediaStreamDestination();
        oscillator.connect(destination);
        oscillator.start();
        await audio.resume();
        stream.addTrack(destination.stream.getAudioTracks()[0]);
      }
      peers.set(id, { pc, stream });
      pc.onicecandidate = ({ candidate }) => { if (candidate) callback({ type: "candidate", candidate: candidate.toJSON() }); };
      await pc.setRemoteDescription({ type: "offer", sdp: message.offer });
      stream.getTracks().forEach((track) => pc.addTrack(track, stream));
      await pc.setLocalDescription(await pc.createAnswer());
      callback({ type: "session", session_id: id });
      callback({ type: "answer", answer: pc.localDescription.sdp });
      return () => {
        pc.close();
        stream.getTracks().forEach((track) => track.stop());
        void audio?.close();
        peers.delete(id);
      };
    },
  },
};
function mount(config = {}) {
  const card = document.createElement("c300x-doorbell-call-card");
  card.setConfig({ entity: camera, mode: "doorstation", ringback_tone: false, ...config });
  card.hass = hass;
  document.querySelector("#mount").replaceChildren(card);
  return card;
}
const card = mount();
window.lab = { card, hass, calls, peers, listeners, mount, source, timer, camera };

// Only the history suite opts into this transport; smoke keeps its original setup.
window.lab.installMediaHistory = async () => {
  const lab = window.lab;
  const image = await new Promise((done) => source.toBlob(done, "image/jpeg"));
  const video = await (await fetch("/synthetic.mp4")).blob();
  const now = Math.floor(Date.now() / 1000);
  lab.historyItems = [
    { id: "c".repeat(64), kind: "image", at: now - 180, expires_at: now + 3600, revision: "3" },
    { id: "a".repeat(64), kind: "image", at: now - 60, expires_at: now + 3600, revision: "1" },
    { id: "b".repeat(64), kind: "video", at: now - 120, expires_at: now + 3600, revision: "2" },
  ];
  lab.historyFetches = [];
  lab.historyListeners = new Set();
  lab.historySubscriptions = [];
  lab.wsCommands = [];
  lab.peerOffers = 0;
  lab.createdUrls = [];
  lab.revokedUrls = [];
  lab.activeUrls = new Set();
  const create = URL.createObjectURL.bind(URL);
  const revoke = URL.revokeObjectURL.bind(URL);
  URL.createObjectURL = (blob) => {
    const url = create(blob);
    lab.createdUrls.push(url);
    lab.activeUrls.add(url);
    return url;
  };
  URL.revokeObjectURL = (url) => {
    lab.revokedUrls.push(url);
    lab.activeUrls.delete(url);
    revoke(url);
  };
  const callWS = hass.callWS;
  hass.callWS = (message) => { lab.wsCommands.push(message); return callWS(message); };
  const subscribe = hass.connection.subscribeMessage;
  hass.connection.subscribeMessage = async (callback, message) => {
    if (message.type !== "bticino_c300x/visitor_journal/subscribe") {
      lab.peerOffers++;
      return subscribe(callback, message);
    }
    if (message.entry_id !== "entry-one") throw new Error("Unexpected history entry");
    const listeners = lab.historyListeners;
    lab.historySubscriptions.push({ ...message });
    listeners.add(callback);
    return () => listeners.delete(callback);
  };
  lab.historyResponse = (url) => {
    const base = "/api/bticino_c300x/media-history/entry-one";
    if (url === base) return Response.json({ items: lab.historyItems });
    const item = lab.historyItems.find((entry) => url === `${base}/${entry.id}`);
    if (!item) throw new Error(`Unexpected history URL: ${url}`);
    return new Response(item.kind === "video" ? video : image, {
      headers: { "Content-Type": item.kind === "video" ? "video/mp4" : "image/jpeg" },
    });
  };
  hass.fetchWithAuth = async (url, options = {}) => {
    if (!(options.signal instanceof AbortSignal)) throw new Error("History fetch requires abort signal");
    if (options.cache !== "no-store") throw new Error("History fetch must bypass caches");
    const request = { url, signal: options.signal, aborted: options.signal.aborted };
    options.signal.addEventListener("abort", () => { request.aborted = true; }, { once: true });
    lab.historyFetches.push(request);
    if (lab.holdHistoryFetch?.(url)) {
      // Deliberately allow a late response even after abort to detect stale results.
      return new Promise((resolve) => {
        lab.pendingHistory = { request, finish: () => resolve(lab.historyResponse(url)) };
      });
    }
    return lab.historyResponse(url);
  };
  lab.card.hass = { ...hass };
};
