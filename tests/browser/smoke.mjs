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
  for (const width of [320, 390, 1024]) {
    await page.setViewport({ width, height: 800 });
    for (const language of ["de", "en", "fr", "it"]) {
      await page.evaluate((language) => {
        lab.hass.language = language;
        lab.hass.states[lab.camera].attributes.friendly_name = "Synthetic very long door station name for layout testing";
        lab.card.hass = { ...lab.hass };
      }, language);
      await page.evaluate(() => new Promise(requestAnimationFrame));
      const failures = await page.evaluate(() => {
        const root = lab.card.shadowRoot;
        const outer = lab.card.getBoundingClientRect();
        const failures = [];
        if (document.documentElement.scrollWidth > innerWidth) failures.push("page overflow");
        for (const button of root.querySelectorAll("button")) {
          const rect = button.getBoundingClientRect();
          if (!rect.width || !rect.height) continue;
          if (rect.left < outer.left || rect.right > outer.right + 1 || rect.bottom > outer.bottom + 1) failures.push(button.className);
          if (!button.getAttribute("aria-label")) failures.push("missing accessible button label");
        }
        return failures;
      });
      assert.deepEqual(failures, [], `${width}px ${language}`);
    }
    await page.screenshot({ path: resolve(artifacts, `card-${width}.png`) });
  }
  const click = async (selector) => { await page.evaluate((selector) => lab.card.shadowRoot.querySelector(selector).click(), selector); };
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
  for (let cycle = 0; cycle < 2; cycle++) {
    const width = cycle === 0 ? 320 : 1024;
    await page.setViewport({ width, height: 800 });
    await click(".row-action");
    await page.waitForFunction(() => lab.card._videoEl.videoWidth === 320 && lab.card._videoEl.readyState >= 2);
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
  console.log("Browser smoke passed: 12 layouts, actions, RTC cycles, microphone, reconfigure and detach cleanup");
} finally {
  await browser?.close();
  await new Promise((done) => server.close(done));
}
