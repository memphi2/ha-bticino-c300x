import assert from "node:assert/strict";

// Starting a stream must not resize the card. On plain HTTP the browser has no
// microphone API, so every start shows a two-second notice; that notice (or a
// long error) must fit the footer instead of growing it for a moment.
export async function checkSteadyStreamStart(page) {
  const results = [];
  for (const width of [240, 320, 390, 1024]) {
    for (const language of ["en", "de"]) {
      await page.setViewport({ width, height: 900 });
      await page.reload();
      await page.waitForFunction(() => !!window.lab);
      const result = await page.evaluate(async (language) => {
        document.querySelector("#mount").style.height = "auto";
        Object.defineProperty(navigator.mediaDevices, "getUserMedia", { value: undefined, configurable: true });
        lab.hass.language = language;
        lab.hass.states[lab.camera].attributes.stream_snapshots = true;
        // The camera's picture size is known, as after its first stream: the
        // still and the synthetic stream share its 4:3 shape.
        localStorage.setItem(`c300x-picture-ratio:${lab.camera}`, "1.3333");
        const card = lab.card = lab.mount();
        const canvas = document.createElement("canvas");
        canvas.width = lab.source.width; canvas.height = lab.source.height;
        canvas.getContext("2d").fillRect(0, 0, canvas.width, canvas.height);
        const url = URL.createObjectURL(await new Promise((done) => canvas.toBlob(done, "image/jpeg")));
        card._snapshots.showPreview(url, 1800000000);
        await card._snapshotEl.decode();
        await new Promise(requestAnimationFrame);
        const outer = card.shadowRoot.querySelector("ha-card");
        const heights = [], phases = new Set();
        let notice = "", recording = true;
        const sample = () => {
          const live = card._videoEl.readyState >= 2 && card._videoEl.videoWidth > 0;
          const phase = live ? "playing" : card._webrtc.remoteStream || card._talkbackStarting ? "starting" : "snapshot";
          phases.add(phase);
          if (card._notice) notice = card._notice;
          heights.push({ phase, card: outer.getBoundingClientRect().height,
            body: card._bodyEl.getBoundingClientRect().height, media: card._mediaEl.getBoundingClientRect().height });
          if (recording) requestAnimationFrame(sample);
        };
        sample();
        card._actionButtonEl.click();
        const deadline = performance.now() + 8000;
        while (performance.now() < deadline && !(phases.has("playing") && notice && !card._notice)) {
          await new Promise((done) => setTimeout(done, 50));
        }
        for (let frame = 0; frame < 5; frame++) await new Promise(requestAnimationFrame);
        // An error stays until the next action and must fit the same footer.
        card._error = "C300X WebRTC session failed: the door station did not answer the offer in time";
        card._updateState();
        for (let frame = 0; frame < 3; frame++) await new Promise(requestAnimationFrame);
        recording = false;
        card._error = "";
        card._closePeer(true);
        card._snapshots.showPreview("", 0);
        URL.revokeObjectURL(url);
        lab.hass.states[lab.camera].attributes.stream_snapshots = false;
        localStorage.removeItem(`c300x-picture-ratio:${lab.camera}`);
        const span = (key) => {
          const values = heights.map((row) => row[key]);
          return { min: Math.min(...values), max: Math.max(...values) };
        };
        const byPhase = {};
        for (const row of heights) {
          const entry = byPhase[row.phase] ??= { min: Infinity, max: -Infinity };
          entry.min = Math.min(entry.min, row.card);
          entry.max = Math.max(entry.max, row.card);
        }
        return { phases: [...phases], notice, frames: heights.length,
          card: span("card"), body: span("body"), media: span("media"), byPhase };
      }, language);
      const label = `${width}px ${language}`;
      assert.deepEqual(result.phases, ["snapshot", "starting", "playing"], `${label}: ${JSON.stringify(result)}`);
      assert.ok(result.notice, `${label}: the microphone notice was not shown: ${JSON.stringify(result)}`);
      for (const part of ["card", "body", "media"]) {
        assert.ok(result[part].max - result[part].min < 1,
          `${label}: ${part} height changed during the stream start: ${JSON.stringify(result)}`);
      }
      results.push(`${label} ${result.card.min}px`);
    }
  }
  // The removed microphone API and the stored shape must not reach later checks.
  await page.reload();
  await page.waitForFunction(() => !!window.lab);
  return results;
}
