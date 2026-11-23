import assert from "node:assert/strict";
import { resolve } from "node:path";

export async function checkSnapshotLayout(page, artifacts) {
  // The picture frame takes the shape of the stream and the browser keeps it
  // per camera: after one stream, preview, live and stopped share one size.
  const shape = await page.evaluate(async () => {
    const video = lab.card._videoEl, stream = lab.source.captureStream(10);
    try {
      video.srcObject = stream;
      await video.play();
      if (!video.videoWidth) await new Promise((done) => video.addEventListener("loadedmetadata", done, { once: true }));
    } finally {
      video.srcObject = null;
      stream.getTracks().forEach((track) => track.stop());
    }
    return lab.card.style.getPropertyValue("--c300x-picture-ratio");
  });
  assert.equal(shape, "1.3333");
  for (const width of [240, 320, 390, 1024]) {
    await page.setViewport({ width, height: 800 });
    for (const height of ["auto", "420px"]) {
      for (const size of [[688, 480], [800, 480], [320, 240]]) {
        const result = await page.evaluate(async ({ height, size }) => {
          document.querySelector("#mount").style.height = height;
          const card = lab.card;
          lab.hass.language = "en";
          const canvas = document.createElement("canvas");
          [canvas.width, canvas.height] = size;
          const context = canvas.getContext("2d");
          context.fillStyle = "#337799";
          context.fillRect(0, 0, ...size);
          const url = URL.createObjectURL(await new Promise((done) => canvas.toBlob(done, "image/jpeg")));
          lab.hass.states[lab.camera].attributes.stream_snapshots = true;
          card.hass = { ...lab.hass };
          card._snapshots.showPreview(url, 1800000000);
          await card._snapshotEl.decode();
          const tick = () => new Promise(requestAnimationFrame);
          const bounds = () => {
            const outer = card.getBoundingClientRect();
            const media = card._mediaEl.getBoundingClientRect();
            return { height: outer.height, width: outer.width, mediaWidth: media.width, mediaHeight: media.height };
          };
          await tick();
          const preview = bounds();
          const accessible = card._snapshotEl.getAttribute("aria-label");
          const overlay = !!card.shadowRoot.querySelector(".snapshot-label");
          const stream = lab.source.captureStream(10);
          try {
            card._webrtc._remoteStream = stream;
            card._videoEl.srcObject = stream;
            await card._videoEl.play();
            card._updateState();
            await tick();
            const live = bounds();
            const snapshotHidden = card._snapshotEl.hidden;
            card._webrtc._remoteStream = null;
            card._videoEl.srcObject = null;
            card._updateState();
            await tick();
            return { preview, live, stopped: bounds(), accessible, overlay,
              snapshotHidden, snapshotRestored: !card._snapshotEl.hidden,
              fit: getComputedStyle(card._snapshotEl).objectFit,
              overflow: document.documentElement.scrollWidth > innerWidth };
          } finally {
            stream.getTracks().forEach((track) => track.stop());
            URL.revokeObjectURL(url);
          }
        }, { height, size });
        const label = `${width}px ${height} ${size.join("x")}`;
        for (const [state, ratio] of [[result.preview, size[0] / size[1]],
          [result.live, 4 / 3], [result.stopped, size[0] / size[1]]]) {
          assert.ok(Math.abs(state.mediaHeight - state.mediaWidth / ratio) < 1,
            `${label}: wrong picture frame: ${JSON.stringify(state)}`);
        }
        assert.ok(result.preview.mediaHeight > 0, label);
        assert.equal(result.overlay, false, `${label}: duplicate timestamp overlay`);
        assert.match(result.accessible, /Archived image \(not live\)/);
        assert.equal(result.fit, "contain");
        assert.equal(result.overflow, false, label);
        assert.ok(result.snapshotHidden && result.snapshotRestored, label);
      }
      await page.screenshot({ path: resolve(artifacts, `snapshot-layout-${width}-${height}.png`) });
    }
  }
  await page.evaluate(() => {
    document.querySelector("#mount").style.height = "";
    lab.card._snapshots.showPreview("", 0);
    lab.hass.states[lab.camera].attributes.stream_snapshots = false;
    lab.card.hass = { ...lab.hass };
  });
}
