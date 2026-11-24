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
          card._cardMedia.setExpanded(true);
          await tick();
          const expanded = card.shadowRoot.querySelector(".body").getBoundingClientRect();
          const footerFits = expanded.bottom <= innerHeight + 1 && expanded.top >= 0;
          const enlarged = bounds();
          card._cardMedia.setExpanded(false);
          await tick();
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
            return { preview, enlarged, live, stopped: bounds(), accessible, overlay, footerFits,
              snapshotHidden, snapshotRestored: !card._snapshotEl.hidden,
              fit: getComputedStyle(card._snapshotEl).objectFit,
              overflow: document.documentElement.scrollWidth > innerWidth };
          } finally {
            stream.getTracks().forEach((track) => track.stop());
            URL.revokeObjectURL(url);
          }
        }, { height, size });
        const label = `${width}px ${height} ${size.join("x")}`;
        // In the card the snapshot sits in the camera's frame, whatever its own
        // shape; only the enlarged preview takes the shape of the snapshot.
        for (const [state, ratio] of [[result.preview, 4 / 3], [result.enlarged, size[0] / size[1]],
          [result.live, 4 / 3], [result.stopped, 4 / 3]]) {
          assert.ok(Math.abs(state.mediaHeight - state.mediaWidth / ratio) < 1,
            `${label}: wrong picture frame: ${JSON.stringify(state)}`);
        }
        for (const key of ["height", "width", "mediaHeight"]) {
          assert.ok(Math.abs(result.live[key] - result.preview[key]) < 1 && Math.abs(result.stopped[key] - result.preview[key]) < 1,
            `${label}: ${key} changed: ${JSON.stringify(result)}`);
        }
        assert.ok(result.preview.mediaHeight > 0, label);
        assert.ok(result.footerFits, `${label}: expanded preview footer outside viewport`);
        assert.equal(result.overlay, false, `${label}: duplicate timestamp overlay`);
        assert.match(result.accessible, /Archived image \(not live\)/);
        assert.equal(result.fit, "contain");
        assert.equal(result.overflow, false, label);
        assert.ok(result.snapshotHidden && result.snapshotRestored, label);
      }
      await page.screenshot({ path: resolve(artifacts, `snapshot-layout-${width}-${height}.png`) });
    }
  }
  // A camera that has not played in this browser has no shape yet: until its
  // first stream the frame takes the shape of the snapshot.
  const unknown = await page.evaluate(async () => {
    document.querySelector("#mount").style.height = "auto";
    const shape = localStorage.getItem(`c300x-picture-ratio:${lab.camera}`);
    localStorage.removeItem(`c300x-picture-ratio:${lab.camera}`);
    const card = lab.mount();
    const canvas = document.createElement("canvas");
    [canvas.width, canvas.height] = [688, 480];
    canvas.getContext("2d").fillRect(0, 0, 688, 480);
    const url = URL.createObjectURL(await new Promise((done) => canvas.toBlob(done, "image/jpeg")));
    try {
      card._snapshots.showPreview(url, 1800000000);
      await card._snapshotEl.decode();
      await new Promise(requestAnimationFrame);
      await new Promise(requestAnimationFrame);
      const media = card._mediaEl.getBoundingClientRect();
      return { width: media.width, height: media.height, visible: !card._snapshotEl.hidden };
    } finally {
      card._snapshots.showPreview("", 0);
      URL.revokeObjectURL(url);
      localStorage.setItem(`c300x-picture-ratio:${lab.camera}`, shape);
      lab.card = lab.mount();
    }
  });
  assert.equal(unknown.visible, true);
  assert.ok(Math.abs(unknown.height - unknown.width / (688 / 480)) < 1, `snapshot frame without a known camera shape: ${JSON.stringify(unknown)}`);
  await page.evaluate(() => {
    document.querySelector("#mount").style.height = "";
    lab.card._snapshots.showPreview("", 0);
    lab.hass.states[lab.camera].attributes.stream_snapshots = false;
    lab.card.hass = { ...lab.hass };
  });
}
