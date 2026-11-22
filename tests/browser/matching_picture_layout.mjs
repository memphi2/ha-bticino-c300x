import assert from "node:assert/strict";
import { resolve } from "node:path";

export async function checkMatchingPictureLayout(page, artifacts) {
  const dimensions = () => page.evaluate(() => {
    const card = lab.card;
    const bounds = (node) => {
      const { width, height } = node.getBoundingClientRect();
      return { width, height };
    };
    const media = bounds(card._mediaEl);
    const buttons = [...card.shadowRoot.querySelectorAll("button")]
      .map((node) => node.getBoundingClientRect()).filter((rect) => rect.width && rect.height);
    const outer = card.shadowRoot.querySelector("ha-card").getBoundingClientRect();
    return { card: bounds(card.shadowRoot.querySelector("ha-card")), media,
      overflow: document.documentElement.scrollWidth > innerWidth,
      buttonsContained: buttons.every((rect) => rect.left >= outer.left && rect.right <= outer.right + 1
        && rect.top >= outer.top && rect.bottom <= outer.bottom + 1),
      fit: getComputedStyle(card._videoEl).objectFit,
      snapshotFit: getComputedStyle(card._snapshotEl).objectFit,
      snapshotVisible: !card._snapshotEl.hidden };
  });
  const screenshot = async (label) => {
    await page.screenshot({ path: resolve(artifacts, `${label}.png`) });
    const element = await page.evaluateHandle(() => lab.card._mediaEl);
    let pixels;
    try {
      const encoded = await element.asElement().screenshot({ encoding: "base64" });
      // Read rendered screenshot edges, not just source pixels: contain bars
      // would be black here even if the decoded video itself were nonblank.
      pixels = await page.evaluate(async (encoded) => {
        const bytes = Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0));
        const image = await createImageBitmap(new Blob([bytes], { type: "image/png" }));
        const canvas = document.createElement("canvas");
        canvas.width = image.width; canvas.height = image.height;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(image, 0, 0);
        image.close();
        return [[2, canvas.height / 2], [canvas.width - 3, canvas.height / 2],
          [canvas.width / 2, 2], [canvas.width / 2, canvas.height - 3]]
          .map(([x, y]) => [...ctx.getImageData(Math.floor(x), Math.floor(y), 1, 1).data]);
      }, encoded);
    } finally {
      await element.dispose();
    }
    for (const pixel of pixels) {
      assert.ok(pixel[0] > 170 && pixel[1] > 130 && pixel[2] < 100,
        `${label}: missing yellow picture edge or added bar: ${pixel}`);
    }
  };
  const assertStable = (before, after, label) => {
    for (const part of ["card", "media"]) for (const axis of ["width", "height"]) {
      assert.ok(Math.abs(before[part][axis] - after[part][axis]) < 1,
        `${label}: ${part}.${axis} jumped: ${JSON.stringify({ before, after })}`);
    }
    assert.ok(Math.abs(after.media.width / after.media.height - 5 / 3) < 0.001, label);
    assert.equal(after.overflow, false, label);
    assert.equal(after.buttonsContained, true, label);
    assert.equal(after.fit, "contain", label);
    assert.equal(after.snapshotFit, "contain", label);
  };

  for (const width of [240, 320, 390, 1024]) {
    await page.setViewport({ width, height: 900, isMobile: width === 390, hasTouch: width === 390 });
    await page.waitForFunction(() => !!window.lab);
    await page.evaluate(async () => {
      localStorage.removeItem(`c300x-picture-ratio:${lab.camera}`);
      document.querySelector("#mount").style.height = "auto";
      lab.hass.language = "en";
      lab.hass.states[lab.camera].attributes.stream_snapshots = true;
      lab.card = lab.mount();
      const picture = (width, height) => {
        const canvas = document.createElement("canvas");
        canvas.width = width; canvas.height = height;
        const ctx = canvas.getContext("2d");
        const paint = () => {
          ctx.fillStyle = "#efdc22";
          ctx.fillRect(0, 0, width, height);
          ctx.fillStyle = "#337799";
          ctx.fillRect(width * 0.04, height * 0.04, width * 0.92, height * 0.92);
          ctx.fillStyle = "#efdc22";
          ctx.fillRect(width * 0.4, height * 0.3, width * 0.2, height * 0.4);
        };
        paint();
        return { canvas, paint };
      };
      const snapshot = picture(800, 480), live = picture(960, 576);
      const url = URL.createObjectURL(await new Promise((done) => snapshot.canvas.toBlob(done, "image/jpeg")));
      lab.geometry = { url, live, timer: setInterval(live.paint, 1000 / 24) };
      lab.card._snapshots.showPreview(url, 1800000000);
      await lab.card._snapshotEl.decode();
      await new Promise(requestAnimationFrame);
    });
    try {
      for (const expanded of [false, true]) {
        await page.evaluate((expanded) => lab.card._cardMedia.setExpanded(expanded), expanded);
        const label = `matching-5x3-${width}-${expanded ? "expanded" : "inline"}`;
        const before = await dimensions();
        assertStable(before, before, label);
        assert.equal(before.snapshotVisible, true);
        await screenshot(`${label}-snapshot`);
        await page.evaluate(async () => {
          const card = lab.card, stream = lab.geometry.live.canvas.captureStream(24);
          lab.geometry.stream = stream;
          card._webrtc._remoteStream = stream;
          card._videoEl.srcObject = stream;
          await card._videoEl.play();
          card._updateState();
          await new Promise(requestAnimationFrame);
        });
        await page.waitForFunction(() => lab.card._videoEl.videoWidth === 960 && lab.card._videoEl.videoHeight === 576);
        const frames = await page.evaluate(() => lab.card._videoEl.getVideoPlaybackQuality().totalVideoFrames);
        await page.waitForFunction((frames) => lab.card._videoEl.getVideoPlaybackQuality().totalVideoFrames > frames + 1, {}, frames);
        const live = await dimensions();
        assertStable(before, live, label);
        assert.equal(live.snapshotVisible, false);
        await screenshot(`${label}-live`);
        await page.evaluate(async () => {
          lab.card._webrtc._remoteStream = null;
          lab.card._videoEl.srcObject = null;
          lab.geometry.stream.getTracks().forEach((track) => track.stop());
          lab.card._updateState();
          await new Promise(requestAnimationFrame);
        });
        const stopped = await dimensions();
        assertStable(before, stopped, label);
        assert.equal(stopped.snapshotVisible, true);
        await screenshot(`${label}-stopped`);
      }
    } finally {
      await page.evaluate(() => {
        lab.card._cardMedia.setExpanded(false);
        lab.geometry.stream?.getTracks().forEach((track) => track.stop());
        clearInterval(lab.geometry.timer);
        lab.card._snapshots.showPreview("", 0);
        URL.revokeObjectURL(lab.geometry.url);
        lab.hass.states[lab.camera].attributes.stream_snapshots = false;
        lab.card.hass = { ...lab.hass };
        document.querySelector("#mount").style.height = "";
      });
    }
  }
}
