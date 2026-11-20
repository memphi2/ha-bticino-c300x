const BASE = "/api/bticino_c300x/media-history/";
const SUBSCRIBE = "bticino_c300x/visitor_journal/subscribe";
const LIMITS = { list: 1024 * 1024, image: 512 * 1024, video: 64 * 1024 * 1024 };
const TYPES = { list: "application/json", image: "image/jpeg", video: "video/mp4" };

export function mediaKey(item) {
  return item ? JSON.stringify([item.id, item.kind, item.revision]) : "";
}

export function historyItems(data, now = Date.now()) {
  if (!Array.isArray(data?.items) || data.items.length > 1000) throw new Error("items");
  const seen = new Set();
  return data.items.filter((item) => {
    if (!item || typeof item.id !== "string" || !/^[a-f0-9]{64}$/.test(item.id) || !["image", "video"].includes(item.kind)
      || !Number.isFinite(item.at) || item.at < 0 || !Number.isFinite(new Date(item.at * 1000).getTime())
      || !Number.isFinite(item.expires_at) || !Number.isFinite(new Date(item.expires_at * 1000).getTime())
      || item.expires_at * 1000 <= now || typeof item.revision !== "string"
      || !item.revision.length || item.revision.length > 1024) return false;
    if (seen.has(item.id)) throw new Error("duplicate");
    seen.add(item.id);
    return true;
  }).map(({ id, kind, at, expires_at, revision }) => ({ id, kind, at, expires_at, revision }))
    .sort((a, b) => b.at - a.at || a.id.localeCompare(b.id));
}

export async function mediaBlob(response, kind, signal) {
  const limit = LIMITS[kind];
  if (!limit || !response.ok || signal.aborted
    || response.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase() !== TYPES[kind]
    || Number(response.headers.get("Content-Length")) > limit || !response.body) {
    await response.body?.cancel().catch(() => {});
    const error = new Error("media");
    error.status = response.status;
    throw error;
  }
  const reader = response.body.getReader(), chunks = [];
  const abort = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener("abort", abort, { once: true });
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
    return new Blob(chunks, { type: TYPES[kind] });
  } finally {
    signal.removeEventListener("abort", abort);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export class C300XMediaHistory {
  constructor(onChange = () => {}) {
    this.onChange = onChange;
    this.items = [];
    this.selected = null;
    this.url = "";
    this.generation = 0;
    this.navigation = 0;
    this.dirty = true;
    this.version = 0;
  }

  configure({ hass, entryId, enabled = true, connected = false, busy = false, stillAt = null }) {
    // The capture time of the last image while the card shows it as its still.
    this.stillAt = Number.isFinite(stillAt) ? stillAt : null;
    const identity = JSON.stringify([hass?.user?.id, hass?.user?.is_admin, hass?.user?.is_owner]);
    if (this.entryId !== entryId || this.connection !== hass?.connection
      || this.auth !== hass?.auth || this.identity !== identity) this.deactivate();
    Object.assign(this, { hass, entryId, connection: hass?.connection, auth: hass?.auth, identity, busy });
    if (!enabled || !connected || !entryId || typeof hass?.fetchWithAuth !== "function"
      || typeof this.connection?.subscribeMessage !== "function") { this.deactivate(); return; }
    if (busy) this.clearMedia();
    if (!this.active) this.activate();
  }

  activate() {
    this.active = true;
    const generation = ++this.generation, connection = this.connection, entryId = this.entryId;
    Promise.resolve().then(() => {
      if (!this.active || generation !== this.generation) return null;
      return connection.subscribeMessage((event) => {
        if (!this.active || generation !== this.generation || event?.entry_id !== entryId) return;
        if (event.closed) this.deactivate();
        else this.markDirty();
      }, { type: SUBSCRIBE, entry_id: entryId });
    }).then((unsubscribe) => {
      if (typeof unsubscribe !== "function") return;
      if (!this.active || generation !== this.generation) this.release(unsubscribe);
      else this.unsubscribe = unsubscribe;
    }).catch(() => { if (generation === this.generation) this.deactivate(); });
  }

  release(unsubscribe) {
    try { Promise.resolve(unsubscribe?.()).catch(() => {}); } catch { /* Already disconnected. */ }
  }

  markDirty() {
    this.dirty = true;
    this.version++;
    if (this.selected && !this.busy) void this.load();
    this.onChange();
  }

  async fetch(path, kind, controller) {
    const timer = setTimeout(() => controller.abort(), kind === "video" ? 30000 : 10000);
    try {
      const response = await this.hass.fetchWithAuth(BASE + encodeURIComponent(this.entryId) + path,
        { signal: controller.signal, cache: "no-store" });
      return await mediaBlob(response, kind, controller.signal);
    } finally { clearTimeout(timer); }
  }

  load() {
    if (!this.active || this.busy) return Promise.resolve(false);
    if (this.listPromise) return this.listPromise;
    if (!this.dirty) { this.expire(); return Promise.resolve(true); }
    const controller = this.listAbort = new AbortController(), generation = this.generation;
    const current = () => this.active && generation === this.generation
      && this.listAbort === controller && !controller.signal.aborted;
    const promise = (async () => {
      try {
        do {
          const version = this.version;
          const blob = await this.fetch("", "list", controller);
          const data = JSON.parse(await blob.text());
          if (!current()) return false;
          if (version !== this.version) continue;
          this.items = historyItems(data);
          this.dirty = false;
          this.error = "";
          this.expire();
        } while (this.dirty && current());
        return current();
      } catch {
        if (this.listAbort === controller && generation === this.generation) {
          this.items = [];
          this.clearSelection();
          this.error = "unavailable";
        }
        return false;
      } finally {
        if (this.listAbort === controller) {
          this.listAbort = null;
          this.listPromise = null;
          this.onChange();
        }
      }
    })();
    this.listPromise = promise;
    this.onChange();
    return promise;
  }

  expire() {
    clearTimeout(this.expiryTimer);
    const now = Date.now();
    this.items = this.items.filter((item) => item.expires_at * 1000 > now);
    if (this.selected) {
      const item = this.items.find((entry) => entry.id === this.selected.id);
      if (!item || mediaKey(item) !== mediaKey(this.selected)) this.clearSelection();
      else this.selected = item;
    }
    if (this.active && this.items.length) {
      const next = Math.min(...this.items.map((item) => item.expires_at * 1000));
      this.expiryTimer = setTimeout(() => this.expire(), Math.min(Math.max(1, next - now), 2147483647));
    }
    this.onChange();
  }

  async step(direction) {
    if (!this.active || this.busy || ![1, -1].includes(direction)) return;
    if (direction === -1 && !this.selected) return;
    const navigation = ++this.navigation, selected = this.selected?.id;
    if (!await this.load() || navigation !== this.navigation || this.busy || !this.active) return;
    if (selected && !this.selected) return;
    const next = this.neighbour(direction);
    if (next < 0) { this.clearMedia(); return; }
    if (next < this.items.length) await this.select(this.items[next]);
    else { this.error = this.items.length ? "" : "empty"; this.onChange(); }
  }

  // The card shows one saved image as its still already, wherever it sits
  // among the items; browsing steps over that one.
  neighbour(direction) {
    const still = this.stillAt === null ? null
      : this.items.find((item) => item.kind === "image" && Math.abs(item.at - this.stillAt) < 0.001);
    let index = this.selected ? this.items.findIndex((item) => item.id === this.selected.id) : -1;
    do index += direction; while (still && this.items[index] === still);
    return index;
  }

  async select(item) {
    if (!this.active || this.busy || item.expires_at * 1000 <= Date.now()
      || !this.items.some((entry) => mediaKey(entry) === mediaKey(item))) return;
    this.clearSelection(false);
    this.selected = item;
    this.error = "";
    const controller = this.mediaAbort = new AbortController();
    this.onChange();
    try {
      const blob = await this.fetch(`/${item.id}`, item.kind, controller);
      if (controller !== this.mediaAbort || controller.signal.aborted || !this.active) return;
      if (this.selected.expires_at * 1000 <= Date.now()) { this.expire(); return; }
      this.url = URL.createObjectURL(blob);
    } catch (error) {
      if (controller === this.mediaAbort) {
        if (error?.status === 401 || error?.status === 403) {
          this.deactivate();
          this.error = "unavailable";
        } else this.mediaUnavailable();
      }
    } finally {
      if (controller === this.mediaAbort) this.mediaAbort = null;
      this.onChange();
    }
  }

  mediaUnavailable() {
    // Keep the chronological cursor so an unreadable item can be skipped.
    this.clearSelection(false, true);
    this.error = "unavailable";
    this.onChange();
  }

  clearSelection(notify = true, keepCursor = false) {
    this.mediaAbort?.abort();
    this.mediaAbort = null;
    if (!keepCursor) this.selected = null;
    const url = this.url;
    this.url = "";
    if (notify) this.onChange();
    if (url) URL.revokeObjectURL(url);
  }

  clearMedia() {
    const changed = !!(this.selected || this.url || this.mediaAbort
      || this.listAbort || this.listPromise || this.error);
    // Even an empty view can have navigation awaiting a cached list promise.
    this.navigation++;
    this.listAbort?.abort();
    if (this.listAbort) this.dirty = true;
    this.listAbort = this.listPromise = null;
    this.error = "";
    this.clearSelection(changed);
    return changed;
  }

  deactivate() {
    const changed = !!this.active || this.items.length > 0 || !this.dirty;
    this.active = false;
    this.generation++;
    this.release(this.unsubscribe);
    this.unsubscribe = null;
    clearTimeout(this.expiryTimer);
    this.expiryTimer = null;
    this.items = [];
    this.dirty = true;
    const mediaChanged = this.clearMedia();
    if (changed && !mediaChanged) this.onChange();
  }
}
