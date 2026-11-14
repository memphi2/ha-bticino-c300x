// Display existing server archives only; never acquire or upload camera frames.
export class C300XStreamSnapshots {
  constructor({ getHass, showPreview }) {
    this.getHass = getHass;
    this.showPreview = showPreview;
    this.previewKey = "";
    this.url = "";
  }

  update({ entryId, attributes = {} }) {
    const enabled = attributes.stream_snapshots === true && !!entryId;
    const imageId = enabled ? attributes.snapshot_latest : null;
    const capturedAt = Number(attributes.snapshot_captured_at) || 0;
    const retention = Math.min(365, Math.max(1, Number(attributes.snapshot_retention_days) || 14));
    const expires = capturedAt * 1000 + retention * 86400000;
    const key = imageId && capturedAt > 0 && Number.isFinite(expires) && expires > Date.now()
      ? JSON.stringify([entryId, imageId, capturedAt, expires]) : "";
    if (key === this.previewKey) return;

    this.clearPreview(false);
    // Commit the new key before notifying the card, which can render synchronously.
    this.previewKey = key;
    this.showPreview("", 0);
    if (!key || this.previewKey !== key) return;
    void this.loadPreview(entryId, imageId, capturedAt, key);
    // Long retention periods exceed the browser timer limit. Expiration is
    // entirely local and never fetches another image.
    const expire = () => {
      if (this.previewKey !== key) return;
      if (expires <= Date.now()) this.clearPreview();
      else this.expiryTimer = setTimeout(expire, Math.min(expires - Date.now(), 2147483647));
    };
    expire();
  }

  async loadPreview(entryId, imageId, capturedAt, key) {
    const controller = new AbortController();
    this.previewAbort = controller;
    const timeout = setTimeout(() => controller.abort(), 10000);
    controller.signal.addEventListener("abort", () => clearTimeout(timeout), { once: true });
    try {
      const response = await this.getHass().fetchWithAuth(
        `/api/bticino_c300x/snapshots/${encodeURIComponent(entryId)}/${encodeURIComponent(imageId)}`,
        { signal: controller.signal },
      );
      if (controller.signal.aborted || this.previewKey !== key || !response.ok
        || !response.headers.get("Content-Type")?.startsWith("image/jpeg")) return;
      const blob = await response.blob();
      if (controller.signal.aborted || this.previewKey !== key || !blob.size || blob.size > 512 * 1024) return;
      this.url = URL.createObjectURL(blob);
      this.showPreview(this.url, capturedAt);
    } catch {
      // Failed loads remain blank until metadata changes. No retries or polling:
      // state updates announce the next available image.
    } finally {
      clearTimeout(timeout);
    }
  }

  clearPreview(notify = true) {
    this.previewAbort?.abort();
    this.previewAbort = null;
    clearTimeout(this.expiryTimer);
    this.expiryTimer = null;
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = "";
    this.previewKey = "";
    if (notify) this.showPreview("", 0);
  }

  dispose() {
    this.clearPreview();
  }
}
