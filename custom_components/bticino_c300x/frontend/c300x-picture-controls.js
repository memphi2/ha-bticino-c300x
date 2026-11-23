import { mediaLocalize } from "./c300x-media-translations.js?v=074d997cd553be86";

const keys = ["brightness", "contrast", "saturation"];

export class C300XPictureControls extends HTMLElement {
  constructor() {
    super();
    this.generation = 0;
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `<style>
      :host {position:absolute;left:8px;bottom:52px;z-index:2;color:white;font:inherit}
      :host([hidden]),[hidden]{display:none!important}
      button,section {background:#202124;color:white}
      button {border:0;border-radius:50%;width:36px;height:36px;cursor:pointer}
      section {position:absolute;bottom:0;left:42px;box-sizing:border-box;width:min(200px,55vw);
        max-height:145px;overflow:auto;padding:8px;border-radius:6px}
      label {display:grid;grid-template-columns:1fr auto;font-size:12px}
      input {grid-column:1/-1;width:100%;margin:0}
      p {margin:0;font-size:12px}
    </style><button type="button" aria-expanded="false" aria-controls="settings"><ha-icon icon="mdi:tune"></ha-icon></button>
    <section id="settings" hidden><p role="status"></p>${keys.map(k =>
      `<label><span></span><output></output><input type="range" min="0" max="100" step="10" data-key="${k}"></label>`).join("")}</section>`;
    this.button = root.querySelector("button");
    this.panel = root.querySelector("section");
    this.status = root.querySelector("p");
    this.inputs = [...root.querySelectorAll("input")];
    this.button.onclick = () => {
      if (!this.panel.hidden) { this.close(); return; }
      this.panel.hidden = false;
      this.button.setAttribute("aria-expanded", "true");
      void this.request({});
    };
    for (const input of this.inputs) {
      input.oninput = () => { input.previousElementSibling.value = input.value + "%"; };
      input.onchange = () => void this.request({control: input.dataset.key, value: Number(input.value)});
    }
  }

  configure(hass, entryId, enabled) {
    if (!enabled || entryId !== this.entryId) this.close();
    this.hidden = !enabled;
    this.hass = hass;
    this.entryId = entryId;
    this.button.title = mediaLocalize(hass, "picture");
    this.button.setAttribute("aria-label", this.button.title);
    for (const input of this.inputs) input.parentElement.firstElementChild.textContent = mediaLocalize(hass, input.dataset.key);
  }

  disconnectedCallback() { this.close(); }
  close() {
    this.generation++;
    this.panel.hidden = true;
    this.button.setAttribute("aria-expanded", "false");
  }

  async request(fields) {
    if (this.panel.hidden || !this.entryId) return;
    const generation = ++this.generation;
    for (const input of this.inputs) {
      input.disabled = true;
      input.parentElement.hidden = !fields.control;
    }
    this.status.textContent = mediaLocalize(this.hass, "loading");
    try {
      const result = await this.hass.callWS({type:"call_service",domain:"bticino_c300x",
        service:"camera_picture",service_data:{entry_id:this.entryId,...fields},return_response:true});
      if (generation !== this.generation) return;
      const values = result?.response;
      if (!keys.every(k => Number.isInteger(values?.[k]) && values[k] >= 0 && values[k] <= 100)) throw Error();
      this.status.textContent = "";
      for (const input of this.inputs) {
        input.parentElement.hidden = input.disabled = false;
        input.value = values[input.dataset.key];
        input.oninput();
      }
    } catch {
      if (generation !== this.generation) return;
      this.status.textContent = mediaLocalize(this.hass, "picture_unavailable");
      for (const input of this.inputs) input.parentElement.hidden = true;
    }
  }
}
if (!customElements.get("c300x-picture-controls")) customElements.define("c300x-picture-controls", C300XPictureControls);
