import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve, dirname, sep } from "node:path";
import puppeteer from "puppeteer-core";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "../../custom_components/bticino_c300x/frontend");
const artifacts = resolve(here, "../../.artifacts/browser");
const server = createServer(async (request, response) => {
  const pathname = new URL(request.url, "http://127.0.0.1").pathname;
  if (pathname === "/favicon.ico") { response.writeHead(204).end(); return; }
  let path;
  if (pathname === "/") path = resolve(here, "fixture.html");
  else if (pathname === "/fixture.mjs") path = resolve(here, "fixture.mjs");
  else if (pathname.startsWith("/frontend/")) {
    path = resolve(frontend, pathname.slice(10));
    if (!path.startsWith(frontend + sep) || !path.endsWith(".js")) path = null;
  }
  if (!path) { response.writeHead(404).end(); return; }
  try {
    response.setHeader("Content-Type", path.endsWith("html") ? "text/html" : "text/javascript");
    response.end(await readFile(path));
  } catch { response.writeHead(404).end(); }
});
await new Promise((done) => server.listen(0, "127.0.0.1", done));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
try {
  browser = await puppeteer.launch({
    executablePath: process.env.CHROME_BIN || "/usr/bin/google-chrome", headless: true,
    args: ["--disable-background-networking", "--autoplay-policy=no-user-gesture-required",
      "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
      ...(process.env.CI ? ["--no-sandbox"] : [])],
  });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    if (new URL(request.url()).origin === origin) request.continue();
    else { errors.push("Non-loopback request blocked"); request.abort(); }
  });
  await mkdir(artifacts, { recursive: true });
  await page.goto(origin);
  await page.waitForFunction(() => !!window.lab);
  const assertFooterLayout = async (label) => {
    const failures = await page.evaluate(() => {
      const root = lab.card.shadowRoot;
      const outer = lab.card.getBoundingClientRect();
      const body = root.querySelector(".body");
      const bodyRect = body.getBoundingClientRect();
      const top = bodyRect.top + parseFloat(getComputedStyle(body).paddingTop);
      const failures = [];
      if (document.documentElement.scrollWidth > innerWidth) failures.push("page overflow");
      for (const selector of [".row-actions", ".device-actions"]) {
        const element = root.querySelector(selector);
        const rect = element.getBoundingClientRect();
        if (rect.width && rect.height && Math.abs(rect.top - top) > 1) failures.push(`${selector} not at top`);
      }
      const buttons = [...root.querySelectorAll("button")].filter((button) => button.getBoundingClientRect().width);
      for (const button of buttons) {
        const rect = button.getBoundingClientRect();
        if (rect.left < outer.left || rect.right > outer.right + 1 || rect.bottom > outer.bottom + 1) failures.push(button.className);
        if (!button.getAttribute("aria-label")) failures.push("missing accessible button label");
        for (const other of buttons) {
          if (other === button) continue;
          const otherRect = other.getBoundingClientRect();
          if (rect.left < otherRect.right && rect.right > otherRect.left
            && rect.top < otherRect.bottom && rect.bottom > otherRect.top) failures.push("overlapping buttons");
        }
        const text = root.querySelector(".entity-text").getBoundingClientRect();
        if (rect.left < text.right && rect.right > text.left
          && rect.top < text.bottom && rect.bottom > text.top) failures.push("button overlaps text");
      }
      return failures;
    });
    assert.deepEqual(failures, [], label);
  };
  for (const width of [240, 320, 390, 1024]) {
    await page.setViewport({ width, height: 800 });
    for (const language of ["de", "en", "fr", "it"]) {
      await page.evaluate((language) => {
        lab.hass.language = language;
        lab.hass.states[lab.camera].attributes.friendly_name = "Synthetic very long door station name for layout testing";
        lab.card._error = "Synthetic long error message that must wrap without moving the door and light buttons below the text.";
        lab.card.hass = { ...lab.hass };
      }, language);
      await page.evaluate(() => new Promise(requestAnimationFrame));
      assert.equal(await page.evaluate(() => {
        const secondary = lab.card.shadowRoot.querySelector(".secondary");
        return secondary.offsetHeight > parseFloat(getComputedStyle(secondary).lineHeight);
      }), true, "Long status text did not wrap");
      await assertFooterLayout(`${width}px ${language}`);
    }
    await page.screenshot({ path: resolve(artifacts, `card-${width}.png`) });
  }
  const click = async (selector) => { await page.evaluate((selector) => lab.card.shadowRoot.querySelector(selector).click(), selector); };
  for (const width of [320, 1024]) {
    await page.setViewport({ width, height: 800 });
    for (const [showDoor, showLight] of [[false, true], [true, false], [false, false], [true, true]]) {
      await page.evaluate(([showDoor, showLight]) => {
        lab.card.setConfig({ ...lab.card._config, show_door_unlock: showDoor, show_stair_light: showLight });
      }, [showDoor, showLight]);
      await page.evaluate(() => new Promise(requestAnimationFrame));
      const actual = await page.evaluate(() => {
        const root = lab.card.shadowRoot;
        return [".door-action", ".light-action", ".device-actions"].map((selector) => {
          const element = root.querySelector(selector);
          return getComputedStyle(element).display !== "none" && element.getBoundingClientRect().width > 0;
        });
      });
      assert.deepEqual(actual, [showDoor, showLight, showDoor || showLight]);
      await assertFooterLayout(`${width}px door=${showDoor} light=${showLight}`);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      const before = await page.evaluate(() => lab.calls.length);
      if (!showDoor) await click(".door-action");
      if (!showLight) await click(".light-action");
      assert.equal(await page.evaluate(() => lab.calls.length), before, "Hidden device action was executed");
      await page.screenshot({ path: resolve(artifacts, `buttons-${width}-${Number(showDoor)}-${Number(showLight)}.png`) });
    }
  }
  await click(".door-action");
  await click(".light-action");
  await page.waitForFunction(() => lab.calls.length === 2);
  assert.deepEqual(await page.evaluate(() => lab.calls.map((call) => call.data.entity_id)), ["button.synthetic_door", "button.synthetic_light"]);
  await page.evaluate(() => {
    lab.hass.states["button.synthetic_door"].state = "unavailable";
    lab.card.hass = { ...lab.hass };
  });
  await page.waitForFunction(() => lab.card.shadowRoot.querySelector(".door-action").disabled);
  await click(".door-action");
  assert.equal(await page.evaluate(() => lab.calls.length), 2);
  await page.evaluate(() => {
    lab.hass.states["button.synthetic_door"].state = "unknown";
    lab.hass.callService = async (domain, service, data) => {
      lab.calls.push({ domain, service, data });
      if (domain === "button") await new Promise((resolve) => { lab.releaseAction = resolve; });
    };
    lab.card.hass = { ...lab.hass };
  });
  await page.waitForFunction(() => !lab.card.shadowRoot.querySelector(".door-action").disabled);
  await click(".door-action");
  await click(".door-action");
  assert.equal(await page.evaluate(() => lab.calls.length), 3, "Pending action was sent twice");
  await page.evaluate(() => lab.releaseAction());
  await page.evaluate(() => {
    lab.card.setConfig({ ...lab.card._config, mode: "auto" });
    lab.card.hass = { ...lab.hass };
  });
  for (let cycle = 0; cycle < 2; cycle++) {
    const width = cycle === 0 ? 320 : 1024;
    await page.setViewport({ width, height: 800 });
    await click(".row-action");
    await page.waitForFunction(() => lab.card._videoEl.videoWidth === 320 && lab.card._videoEl.readyState >= 2);
    assert.equal(await page.evaluate(() => [...lab.card.shadowRoot.querySelectorAll("button")]
      .filter((button) => button.getBoundingClientRect().width).length), 5);
    if (cycle === 0) {
      await page.setViewport({ width: 240, height: 800 });
      await assertFooterLayout("240px with all five controls");
      await page.screenshot({ path: resolve(artifacts, "stream-compact-controls.png") });
      await page.setViewport({ width, height: 800 });
    } else {
      await page.evaluate(() => { document.querySelector("#mount").style.width = "240px"; });
      await assertFooterLayout("240px dashboard card in a wide viewport");
      await page.screenshot({ path: resolve(artifacts, "stream-narrow-column.png") });
      await page.evaluate(() => { document.querySelector("#mount").style.width = ""; });
    }
    await assertFooterLayout(`${width}px streaming with microphone and Home Call`);
    const pixels = await page.evaluate(() => {
      const canvas = document.createElement("canvas"); canvas.width = 320; canvas.height = 240;
      const ctx = canvas.getContext("2d"); ctx.drawImage(lab.card._videoEl, 0, 0);
      return [...ctx.getImageData(80, 80, 1, 1).data];
    });
    assert.ok(pixels[0] > 150 && pixels[1] > 150 && pixels[2] < 100, "Video has no expected synthetic pixels");
    const frames = await page.evaluate(() => lab.card._videoEl.getVideoPlaybackQuality().totalVideoFrames);
    await page.waitForFunction((before) => lab.card._videoEl.getVideoPlaybackQuality().totalVideoFrames > before + 1, {}, frames);
    assert.equal(await page.evaluate(() => {
      const rect = lab.card._videoEl.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && rect.right <= innerWidth
        && getComputedStyle(lab.card._videoEl).objectFit === "contain"
        && document.documentElement.scrollWidth <= innerWidth;
    }), true);
    await page.screenshot({ path: resolve(artifacts, `stream-${width}.png`) });
    await click(".mic-action");
    assert.equal(await page.evaluate(() => lab.card._micStream.getAudioTracks()[0].enabled), false);
    await click(".mic-action");
    assert.equal(await page.evaluate(() => lab.card._micStream.getAudioTracks()[0].enabled), true);
    await click(".row-action");
    await page.waitForFunction(() => !lab.card._webrtc.running && lab.peers.size === 0);
    assert.equal(await page.evaluate(() => lab.card._videoEl.srcObject), null);
  }
  await click(".row-action");
  await page.waitForFunction(() => lab.card._videoEl.readyState >= 2);
  await page.evaluate(() => {
    lab.oldTracks = [...lab.card._micStream.getTracks(), ...lab.card._webrtc.remoteStream.getTracks()];
    lab.card.setConfig({ ...lab.card._config, name: "Reconfigured door" });
    lab.card.hass = { ...lab.hass };
  });
  await page.waitForFunction(() => lab.peers.size === 0 && lab.listeners.size === 1);
  assert.equal(await page.evaluate(() => lab.oldTracks.every((track) => track.readyState === "ended")), true);
  assert.equal(await page.evaluate(() => lab.card._videoEl.srcObject), null);
  await click(".row-action");
  await page.waitForFunction(() => lab.card._videoEl.readyState >= 2);
  await page.evaluate(() => {
    lab.oldTracks = [...lab.card._micStream.getTracks(), ...lab.card._webrtc.remoteStream.getTracks()];
    lab.card.remove();
  });
  await page.waitForFunction(() => lab.peers.size === 0 && lab.listeners.size === 0);
  assert.equal(await page.evaluate(() => lab.oldTracks.every((track) => track.readyState === "ended")), true);
  assert.deepEqual(errors, []);
  console.log("Browser smoke passed: 16 wrapped-text layouts, 8 button layouts, actions, RTC cycles, microphone, reconfigure and detach cleanup");
} finally {
  await browser?.close();
  await new Promise((done) => server.close(done));
}
