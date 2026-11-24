import assert from "node:assert/strict";

// The picture frame has the shape of the camera stream, which only a playing
// stream tells and the browser then remembers. A camera whose picture is not
// 5:3 must therefore resize the card at most once, with the first picture of
// its first stream in this browser; from then on the card keeps that shape
// before, during and after a stream, also while it shows a snapshot of
// another shape (the default snapshot is the 800x480 display).
export async function checkPictureShapeStart(page) {
  const results = [];
  await page.setViewport({ width: 500, height: 900 });
  for (const size of [[688, 480], [704, 576], [720, 576], [800, 480]]) {
    for (const snapshot of [[800, 480], null]) {
      await page.reload();
      await page.waitForFunction(() => !!window.lab);
      const result = await page.evaluate(async (size, snapshot) => {
        document.querySelector("#mount").style.height = "auto";
        localStorage.removeItem(`c300x-picture-ratio:${lab.camera}`);
        [lab.source.width, lab.source.height] = size;
        lab.hass.language = "en";
        lab.hass.states[lab.camera].attributes.stream_snapshots = !!snapshot;
        let url = "";
        if (snapshot) {
          const canvas = document.createElement("canvas");
          [canvas.width, canvas.height] = snapshot;
          canvas.getContext("2d").fillRect(0, 0, ...snapshot);
          url = URL.createObjectURL(await new Promise((done) => canvas.toBlob(done, "image/jpeg")));
        }
        const frames = async (count) => { for (let frame = 0; frame < count; frame++) await new Promise(requestAnimationFrame); };
        const until = async (done) => {
          const deadline = performance.now() + 8000;
          while (performance.now() < deadline && !done()) await new Promise((next) => setTimeout(next, 20));
          return done();
        };
        // One stream from the idle card to the idle card, measured every frame.
        const run = async () => {
          const card = lab.card = lab.mount();
          if (url) {
            card._snapshots.showPreview(url, 1800000000);
            await card._snapshotEl.decode();
          }
          await frames(2);
          const outer = card.shadowRoot.querySelector("ha-card");
          const rows = [];
          let recording = true;
          const sample = () => {
            const media = card._mediaEl.getBoundingClientRect();
            rows.push({ media: media.height, card: outer.getBoundingClientRect().height, width: media.width });
            if (recording) requestAnimationFrame(sample);
          };
          sample();
          const snapshotBefore = !card._snapshotEl.hidden;
          card._actionButtonEl.click();
          const played = await until(() => card._videoEl.readyState >= 2 && card._videoEl.videoWidth > 0);
          await frames(5);
          const video = card._videoEl.videoWidth / card._videoEl.videoHeight;
          const snapshotLive = !card._snapshotEl.hidden;
          card._closePeer(true);
          await until(() => !card._webrtc.remoteStream && !card._webrtc.running);
          await frames(5);
          recording = false;
          const heights = [];
          for (const row of rows) {
            if (!heights.length || Math.abs(heights[heights.length - 1] - row.media) >= 1) heights.push(row.media);
          }
          const cards = rows.map((row) => row.card);
          return { played, video, heights, width: rows[0].width, frames: rows.length,
            card: { min: Math.min(...cards), max: Math.max(...cards) },
            snapshot: [snapshotBefore, snapshotLive, !card._snapshotEl.hidden],
            fit: getComputedStyle(card._snapshotEl).objectFit };
        };
        try {
          return { first: await run(), next: await run() };
        } finally {
          lab.card._snapshots.showPreview("", 0);
          if (url) URL.revokeObjectURL(url);
          lab.hass.states[lab.camera].attributes.stream_snapshots = false;
          localStorage.removeItem(`c300x-picture-ratio:${lab.camera}`);
          [lab.source.width, lab.source.height] = [320, 240];
        }
      }, size, snapshot);
      const label = `${size.join("x")} stream, ${snapshot ? `${snapshot.join("x")} snapshot` : "no snapshot"}`;
      const text = `${label}: ${JSON.stringify(result)}`;
      const ratio = size[0] / size[1];
      for (const run of [result.first, result.next]) {
        assert.ok(run.played, `no picture: ${text}`);
        assert.ok(Math.abs(run.video - ratio) < 0.01, `the stream has another shape: ${text}`);
        assert.deepEqual(run.snapshot, [!!snapshot, false, !!snapshot], text);
        assert.equal(run.fit, "contain", text);
        // The playing picture fills its frame: no bars, and it stays so afterwards.
        assert.ok(Math.abs(run.heights.at(-1) - run.width / ratio) < 1.5, `wrong frame for the stream: ${text}`);
      }
      // Nothing is known before the first stream: the display's 5:3, then the stream's shape, once.
      assert.ok(Math.abs(result.first.heights[0] - result.first.width / (5 / 3)) < 1.5, `wrong first frame: ${text}`);
      assert.ok(result.first.heights.length <= (ratio === 5 / 3 ? 1 : 2), `the frame changed more than once: ${text}`);
      assert.equal(result.next.heights.length, 1, `the frame changed although the shape was known: ${text}`);
      assert.ok(result.next.card.max - result.next.card.min < 1, `the card changed its height: ${text}`);
      results.push(`${label}: ${result.first.heights.map((height) => height.toFixed(1)).join(" -> ")} px, `
        + `then ${result.next.heights[0].toFixed(1)} px`);
    }
  }
  return results;
}
