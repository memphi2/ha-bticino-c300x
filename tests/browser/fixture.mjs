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
    "button.synthetic_door": key("door_unlock"),
    "button.synthetic_light": key("stair_light"),
  },
  states: {
    [camera]: { state: "idle", attributes: { friendly_name: "Synthetic door", media_state: "idle", media_primary_action: "start_stream" } },
    "button.synthetic_door": { state: "unknown", attributes: { lock_id: "default" } },
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
      if (message.type !== "camera/webrtc/offer") throw new Error("Unexpected offer command");
      const id = `synthetic-${++nextSession}`;
      const pc = new RTCPeerConnection({ iceServers: [] });
      const stream = source.captureStream(10);
      peers.set(id, { pc, stream });
      pc.onicecandidate = ({ candidate }) => { if (candidate) callback({ type: "candidate", candidate: candidate.toJSON() }); };
      await pc.setRemoteDescription({ type: "offer", sdp: message.offer });
      pc.addTrack(stream.getVideoTracks()[0], stream);
      await pc.setLocalDescription(await pc.createAnswer());
      callback({ type: "session", session_id: id });
      callback({ type: "answer", answer: pc.localDescription.sdp });
      return () => {
        pc.close();
        stream.getTracks().forEach((track) => track.stop());
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
