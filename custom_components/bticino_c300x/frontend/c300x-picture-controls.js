import { mediaLocalize } from "./c300x-media-translations.js?v=2cf4087c2531195b";

const keys = ["brightness", "contrast", "saturation"];

export class C300XPictureControls extends HTMLElement {
  constructor() {
    super();
    this.generation = 0;
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `<style>
      :host {position:absolute;inset:4px 8px;pointer-events:none;z-index:2;color:white;font:inherit}
      :host([hidden]),[hidden]{display:none!important}
      button,section {pointer-events:auto;color:white}
      button {background:#202124;position:absolute;left:0;bottom:clamp(0px,100% - 36px,48px);border:0;border-radius:50%;width:36px;height:36px;cursor:pointer}
      section {position:absolute;bottom:clamp(0px,100% - 145px,48px);left:42px;
        box-sizing:border-box;width:min(200px,100% - 42px);max-height:min(145px,100%);
        overflow:auto;overscroll-behavior:contain;padding:4px;border-radius:6px;background:#202124}
      :host([live]) section {background:rgb(32 33 36/.5);text-shadow:0 0 2px #000,0 0 2px #000,0 1px 3px #000}
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
      if (this.open) { this.close(); return; }
      this.setOpen(true);
      void this.request({});
    };
    for (const input of this.inputs) {
      input.oninput = () => { input.previousElementSibling.value = input.value + "%"; };
      input.onchange = () => void this.request({control: input.dataset.key, value: Number(input.value)});
    }
  }

  configure(hass, entryId, session) {
    if (entryId !== this.entryId || session !== this.session) this.close();
    this.session = session;
    this.hidden = !session;
    this.hass = hass;
    this.entryId = entryId;
    this.button.title = mediaLocalize(hass, "picture");
    this.button.setAttribute("aria-label", this.button.title);
    for (const input of this.inputs) input.parentElement.firstElementChild.textContent = mediaLocalize(hass, input.dataset.key);
  }

  disconnectedCallback() { this.close(); }
  close() {
    this.generation++;
    this.values = null;
    this.setOpen(false);
  }

  get open() { return !this.panel.hidden; }
  // Every open and close, also the ones the panel does on its own, is told:
  // the card hides the media toolbar under the open panel.
  setOpen(open) {
    this.panel.hidden = !open;
    this.button.setAttribute("aria-expanded", String(open));
    this.dispatchEvent(new Event("picture-toggle"));
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
      this.show(this.values = values);
    } catch (error) {
      if (generation !== this.generation) return;
      // The service error names the agent's code. Not applied or busy: the
      // station kept the last confirmed values, so the sliders stay.
      const code = /\b(picture_not_applied|media_busy)\b/.exec(String(error?.message || ""))?.[1];
      this.status.textContent = mediaLocalize(this.hass,
        code === "picture_not_applied" ? "picture_not_applied" : code ? "picture_busy" : "picture_unavailable");
      this.show(code && this.values);
    }
  }

  show(values) {
    for (const input of this.inputs) {
      input.parentElement.hidden = input.disabled = !values;
      if (!values) continue;
      input.value = values[input.dataset.key];
      input.oninput();
    }
  }
}
if (!customElements.get("c300x-picture-controls")) customElements.define("c300x-picture-controls", C300XPictureControls);
