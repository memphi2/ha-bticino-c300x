import { c300xLocalize } from "./c300x-translations.js?v=5391b85a94f19d3c";

const BASE = "/api/bticino_c300x/visitor-journal/";
const CHANGED = "bticino_c300x_visitor_journal_changed";

export async function journalBlob(response, limit, signal) {
  if (!response.ok || Number(response.headers.get("Content-Length")) > limit) throw new Error("media");
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (signal.aborted) throw new Error("aborted");
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw new Error("size");
      chunks.push(value);
    }
    if (!size) throw new Error("empty");
    return new Blob(chunks, { type: response.headers.get("Content-Type") });
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}

export class C300XVisitorJournal extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { display: block; flex: 0 1 auto; max-height: 50%; overflow: auto; color: var(--primary-text-color); font-size: 14px; letter-spacing: 0; }
        :host([hidden]) { display: none; }
        * { box-sizing: border-box; }
        details { border-top: 1px solid var(--divider-color); }
        summary { cursor: pointer; padding: 12px 16px; }
        button { font: inherit; color: inherit; cursor: pointer; border: 0; background: none; }
        button:focus-visible, summary:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
        button:disabled { opacity: .4; cursor: default; }
        .icon { width: 40px; height: 40px; flex: 0 0 40px; display: inline-flex; align-items: center; justify-content: center; border-radius: 4px; }
        ha-icon { --mdc-icon-size: 22px; }
        .tools { display: flex; justify-content: flex-end; padding: 0 8px; }
        .list { list-style: none; padding: 0; margin: 0; max-height: 280px; overflow: auto; }
        .visit { display: grid; grid-template-columns: minmax(0,1fr) 24px; width: 100%; text-align: start; padding: 10px 16px; gap: 4px 8px; border-top: 1px solid var(--divider-color); }
        .visit time, .outcome { overflow-wrap: anywhere; min-width: 0; }
        .outcome { font-size: 12px; color: var(--secondary-text-color); grid-column: 1; }
        .visit ha-icon { grid-column: 2; grid-row: 1 / 3; align-self: center; }
        .status { padding: 12px 16px; margin: 0; color: var(--secondary-text-color); }
        .more { width: 100%; min-height: 40px; }
        dialog { width: min(760px, calc(100vw - 24px)); max-width: none; max-height: calc(100dvh - 24px); padding: 12px; border: 1px solid var(--divider-color); border-radius: 8px; background: var(--card-background-color, #fff); color: var(--primary-text-color, #222); overflow: auto; }
        dialog::backdrop { background: rgb(0 0 0 / .55); }
        .heading { display: grid; grid-template-columns: minmax(0,1fr) 40px; align-items: center; gap: 8px; min-height: 48px; }
        h2 { font-size: 16px; font-weight: 500; line-height: 1.4; margin: 0; overflow-wrap: anywhere; }
        .frame { position: relative; width: 100%; height: min(50dvh, 420px); background: #151515; margin: 8px 0; touch-action: pan-y; }
        .frame img, .frame video { width: 100%; height: 100%; object-fit: contain; }
        .frame .status { position: absolute; inset: 0; display: grid; place-items: center; text-align: center; color: #eee; }
        [hidden] { display: none !important; }
        .navigation { display: grid; grid-template-columns: 40px minmax(0,1fr) 40px; align-items: center; gap: 8px; }
        .types { display: flex; justify-content: center; gap: 4px; }
        [aria-pressed="true"] { color: var(--primary-color); background: var(--secondary-background-color, #eee); }
        .position { text-align: center; font-size: 12px; color: var(--secondary-text-color); margin: 4px 0 0; }
      </style>
      <details>
        <summary></summary>
        <div class="tools"><button class="icon refresh" type="button"><ha-icon icon="mdi:refresh"></ha-icon></button></div>
        <p class="status list-status" role="status"></p>
        <ol class="list"></ol>
        <button class="more" type="button" hidden></button>
      </details>
      <dialog aria-labelledby="visit-time">
        <div class="heading"><h2 id="visit-time"></h2><button class="icon close" type="button"><ha-icon icon="mdi:close"></ha-icon></button></div>
        <div class="frame">
          <img hidden alt="">
          <video hidden controls playsinline preload="none"></video>
          <p class="status media-status" role="status"></p>
        </div>
        <div class="navigation">
          <button class="icon previous" type="button"><ha-icon icon="mdi:chevron-left"></ha-icon></button>
          <div class="types">
            <button class="icon image" type="button"><ha-icon icon="mdi:image-outline"></ha-icon></button>
            <button class="icon video" type="button"><ha-icon icon="mdi:video-outline"></ha-icon></button>
          </div>
          <button class="icon next" type="button"><ha-icon icon="mdi:chevron-right"></ha-icon></button>
        </div>
        <p class="position" aria-live="polite"></p>
      </dialog>`;
    this.details = root.querySelector("details");
    this.dialog = root.querySelector("dialog");
    this.details.addEventListener("toggle", () => this.details.open ? this.activate() : this.deactivate());
    root.querySelector(".refresh").addEventListener("click", () => void this.load());
    root.querySelector(".more").addEventListener("click", () => { this.visible += 20; this.renderList(); });
    root.querySelector(".close").addEventListener("click", () => this.dialog.close());
    this.dialog.addEventListener("close", () => {
      if (this.dialog.open) return;
      this.clearMedia();
      if (this.active && this.isConnected) {
        (root.querySelectorAll(".visit")[this.index] || root.querySelector("summary")).focus();
      }
    });
    root.querySelector(".previous").addEventListener("click", () => this.step(-1));
    root.querySelector(".next").addEventListener("click", () => this.step(1));
    for (const kind of ["image", "video"]) root.querySelector(`button.${kind}`).addEventListener("click", () => void this.show(this.index, kind));
    this.dialog.addEventListener("keydown", (event) => {
      if (event.target.tagName === "VIDEO" || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      this.step(event.key === "ArrowLeft" ? -1 : 1);
    });
    const frame = root.querySelector(".frame");
    frame.addEventListener("pointerdown", (event) => {
      this.touch = event.pointerType === "touch" ? { x: event.clientX, y: event.clientY, id: event.pointerId } : null;
    });
    frame.addEventListener("pointercancel", () => { this.touch = null; });
    frame.addEventListener("pointerup", (event) => {
      const start = this.touch;
      this.touch = null;
      if (!start || start.id !== event.pointerId) return;
      const dx = event.clientX - start.x, dy = event.clientY - start.y;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) this.step(dx < 0 ? 1 : -1);
    });
    for (const selector of ["img", "video"]) root.querySelector(selector).addEventListener("error", () => {
      if (this.dialog.open && this.url) this.mediaStatus("journal_media_missing");
    });
    this.items = [];
    this.visible = 20;
    this.generation = 0;
    this.hidden = true;
  }

  configure({ hass, entryId, enabled }) {
    if (!this.shadowRoot) return;
    const changed = this.entryId !== entryId || this.hass?.connection !== hass?.connection || this.hidden === !!enabled;
    if (changed) this.deactivate();
    this.hass = hass;
    this.entryId = entryId;
    this.hidden = !enabled || !entryId;
    this.labels();
    if (this.language !== hass?.language) {
      this.language = hass?.language;
      this.renderList();
      if (this.dialog.open) this.viewerLabels();
    }
    if (!this.hidden && this.details.open && !this.active) this.activate();
  }

  label(key) { return c300xLocalize(this.hass, key); }

  labels() {
    const root = this.shadowRoot;
    root.querySelector("summary").textContent = this.label("visitor_journal");
    root.querySelector(".more").textContent = this.label("journal_more");
    for (const [selector, key] of Object.entries({ refresh: "journal_refresh", close: "journal_close", previous: "journal_previous", next: "journal_next", image: "journal_image", video: "journal_video" })) {
      const button = root.querySelector(`button.${selector}`);
      button.setAttribute("aria-label", this.label(key));
      button.title = this.label(key);
    }
  }

  activate() {
    if (!this.isConnected || this.hidden || !this.entryId || this.active) return;
    this.active = true;
    const generation = ++this.generation;
    const subscribe = this.hass?.connection?.subscribeEvents;
    if (subscribe) {
      Promise.resolve().then(() => subscribe.call(this.hass.connection, (event) => {
        if (this.active && this.generation === generation && event.data?.entry_id === this.entryId) void this.load();
      }, CHANGED)).then((unsubscribe) => {
        if (!this.active || this.generation !== generation) unsubscribe();
        else this.unsubscribe = unsubscribe;
      }).catch(() => {});
    }
    void this.load();
  }

  async load() {
    if (!this.active) return;
    if (this.loading) { this.reload = true; return; }
    this.loading = true;
    const generation = this.generation;
    const controller = new AbortController();
    this.listAbort = controller;
    const timer = setTimeout(() => controller.abort(), 10000);
    const status = this.shadowRoot.querySelector(".list-status");
    status.hidden = false;
    status.textContent = this.label("journal_loading");
    try {
      const response = await this.hass.fetchWithAuth(BASE + encodeURIComponent(this.entryId), { signal: controller.signal });
      const blob = await journalBlob(response, 1024 * 1024, controller.signal);
      const data = JSON.parse(await blob.text());
      if (generation !== this.generation || controller.signal.aborted) return;
      if (!Array.isArray(data.visits) || data.visits.length > 1000) throw new Error("visits");
      const selected = this.items[this.index]?.id;
      this.items = data.visits.filter((item) => /^[a-f0-9]{32}$/.test(item.id) && Number.isFinite(item.at)
        && Number.isFinite(item.expires_at) && item.expires_at * 1000 > Date.now());
      if (this.dialog.open) {
        const index = this.items.findIndex((item) => item.id === selected);
        if (index < 0) this.dialog.close();
        else { this.index = index; this.viewerLabels(); }
      }
      this.renderList();
      this.expire();
      status.textContent = this.label("journal_empty");
      status.hidden = this.items.length > 0;
    } catch {
      if (generation === this.generation) {
        this.items = [];
        this.renderList();
        this.dialog.close();
        status.hidden = false;
        status.textContent = this.label("journal_unavailable");
      }
    } finally {
      clearTimeout(timer);
      if (generation === this.generation) {
        this.loading = false;
        if (this.reload) { this.reload = false; void this.load(); }
      }
    }
  }

  date(item) { return new Date(item.at * 1000).toLocaleString(this.hass?.language); }

  expire() {
    clearTimeout(this.expiryTimer);
    if (!this.active) return;
    const selected = this.items[this.index]?.id;
    this.items = this.items.filter((item) => item.expires_at * 1000 > Date.now());
    if (this.dialog.open) {
      const index = this.items.findIndex((item) => item.id === selected);
      if (index < 0) this.dialog.close();
      else { this.index = index; this.viewerLabels(); }
    }
    this.renderList();
    if (this.items.length) {
      const next = Math.min(...this.items.map((item) => item.expires_at * 1000));
      this.expiryTimer = setTimeout(() => this.expire(), Math.min(next - Date.now(), 2147483647));
    } else {
      const status = this.shadowRoot.querySelector(".list-status");
      status.textContent = this.label("journal_empty");
      status.hidden = false;
    }
  }

  renderList() {
    const list = this.shadowRoot.querySelector(".list");
    list.replaceChildren();
    for (const [index, item] of this.items.slice(0, this.visible).entries()) {
      const row = document.createElement("li"), button = document.createElement("button");
      button.type = "button";
      button.className = "visit";
      const time = document.createElement("time"), outcome = document.createElement("span"), icon = document.createElement("ha-icon");
      time.dateTime = new Date(item.at * 1000).toISOString();
      time.textContent = this.date(item);
      outcome.className = "outcome";
      outcome.textContent = this.label(item.outcome === "answered" ? "journal_answered" : "journal_unknown");
      icon.setAttribute("icon", item.video ? "mdi:video-outline" : item.image ? "mdi:image-outline" : "mdi:image-off-outline");
      icon.setAttribute("aria-hidden", "true");
      button.append(time, outcome, icon);
      button.addEventListener("click", () => { this.dialog.showModal(); void this.show(index); });
      row.append(button);
      list.append(row);
    }
    this.shadowRoot.querySelector(".more").hidden = this.visible >= this.items.length;
  }

  step(offset) {
    const next = this.index + offset;
    if (next >= 0 && next < this.items.length) void this.show(next);
  }

  viewerLabels() {
    const item = this.items[this.index];
    if (!item) return;
    const root = this.shadowRoot;
    root.querySelector("h2").textContent = this.date({ at: item[`${this.kind}_at`] || item.at });
    root.querySelector(".position").textContent = `${this.index + 1} / ${this.items.length}`;
    root.querySelector(".previous").disabled = this.index === 0;
    root.querySelector(".next").disabled = this.index === this.items.length - 1;
    for (const kind of ["image", "video"]) {
      const button = root.querySelector(`button.${kind}`);
      button.disabled = item[kind] !== true;
      button.setAttribute("aria-pressed", String(this.kind === kind));
    }
  }

  mediaStatus(key) {
    this.shadowRoot.querySelector(".frame").setAttribute("aria-busy", String(key === "journal_loading"));
    const status = this.shadowRoot.querySelector(".media-status");
    status.hidden = !key;
    status.textContent = key ? this.label(key) : "";
  }

  async show(index, kind) {
    this.clearMedia();
    const item = this.items[index];
    if (!item || !this.dialog.open) return;
    this.index = index;
    this.kind = kind || (item.image ? "image" : "video");
    this.viewerLabels();
    if (item[this.kind] !== true) { this.mediaStatus("journal_media_missing"); return; }
    this.mediaStatus("journal_loading");
    const controller = new AbortController();
    this.mediaAbort = controller;
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await this.hass.fetchWithAuth(`${BASE}${encodeURIComponent(this.entryId)}/${item.id}/${this.kind}`, { signal: controller.signal });
      const mime = this.kind === "image" ? "image/jpeg" : "video/mp4";
      if (response.headers.get("Content-Type")?.split(";")[0] !== mime) throw new Error("type");
      const blob = await journalBlob(response, this.kind === "image" ? 512 * 1024 : 64 * 1024 * 1024, controller.signal);
      if (controller !== this.mediaAbort || controller.signal.aborted || !this.dialog.open) return;
      this.url = URL.createObjectURL(blob);
      const media = this.shadowRoot.querySelector(this.kind === "image" ? "img" : "video");
      const label = `${this.label(`journal_${this.kind}`)}: ${this.date({ at: item[`${this.kind}_at`] || item.at })}`;
      media.setAttribute("aria-label", label);
      if (this.kind === "image") media.alt = label;
      media.src = this.url;
      media.hidden = false;
      this.mediaStatus("");
    } catch {
      if (controller === this.mediaAbort && this.dialog.open) this.mediaStatus("journal_media_missing");
    } finally { clearTimeout(timer); }
  }

  clearMedia() {
    this.mediaAbort?.abort();
    this.mediaAbort = null;
    if (!this.shadowRoot) return;
    const video = this.shadowRoot.querySelector("video"), img = this.shadowRoot.querySelector("img");
    video.pause();
    video.removeAttribute("src");
    video.load();
    video.hidden = true;
    img.removeAttribute("src");
    img.hidden = true;
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = "";
  }

  deactivate() {
    this.active = false;
    this.generation = (this.generation || 0) + 1;
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.listAbort?.abort();
    clearTimeout(this.expiryTimer);
    this.loading = false;
    this.reload = false;
    this.dialog?.close();
    this.clearMedia();
    this.items = [];
    this.visible = 20;
    if (this.shadowRoot) this.renderList();
  }

  disconnectedCallback() { this.deactivate(); }
}

if (!customElements.get("c300x-visitor-journal")) customElements.define("c300x-visitor-journal", C300XVisitorJournal);
