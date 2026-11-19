import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve, dirname, sep } from "node:path";
import { execFileSync } from "node:child_process";
import puppeteer from "puppeteer-core";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "../../custom_components/bticino_c300x/frontend");
const artifacts = resolve(here, "../../.artifacts/browser");
const clip = execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i",
  "testsrc2=size=320x240:rate=12", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
  "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
  "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"]);
const server = createServer(async (request, response) => {
  const pathname = new URL(request.url, "http://localhost").pathname;
  if (pathname === "/favicon.ico") { response.writeHead(204).end(); return; }
  if (pathname === "/synthetic.mp4") { response.setHeader("Content-Type", "video/mp4"); response.end(clip); return; }
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
let browser, page;
const errors = [];
try {
  browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || "/usr/bin/google-chrome", headless: true,
    args: ["--disable-background-networking", "--autoplay-policy=no-user-gesture-required",
      "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
      ...(process.env.CI ? ["--no-sandbox"] : [])] });
  page = await browser.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    if (new URL(request.url()).origin === origin) request.continue();
    else { errors.push(`Non-loopback request blocked: ${request.url()}`); request.abort(); }
  });
  await mkdir(artifacts, { recursive: true });
  await page.goto(origin);
  const setup = async () => {
    await page.waitForFunction(() => !!window.lab);
    await page.evaluate(async () => {
      if (lab.controls) return;
      await lab.installMediaHistory();
      lab.hass.states[lab.camera].attributes.friendly_name = "Door";
      lab.card.setConfig({ entity: lab.camera, mode: "auto", ringback_tone: false, name: "Door" });
      lab.card.hass = { ...lab.hass };
      lab.controls = lab.card.shadowRoot.querySelector("c300x-media-controls");
      lab.control = (selector) => lab.controls.shadowRoot.querySelector(selector);
    });
    await page.waitForFunction(() => lab.historyListeners.size === 1);
  };
  await setup();
  const click = async (selector, parent = false) => {
    const element = await page.evaluateHandle((selector, parent) => parent
      ? lab.card.shadowRoot.querySelector(selector) : lab.control(selector), selector, parent);
    try { await element.asElement().click(); } finally { await element.dispose(); }
  };
  const selected = async (id, kind) => {
    await page.waitForFunction((id, kind) => lab.controls.history.selected?.id === id.repeat(64)
      && !!lab.controls.history.url && (kind === "video" ? lab.control("video").readyState >= 2
        : lab.control("img").complete && lab.control("img").naturalWidth === 320), {}, id, kind);
  };
  // Back to live: the right arrow steps past the newest saved item.
  const current = async () => {
    for (let step = 0; step < 10 && await page.evaluate(() => lab.controls.browsing); step++) {
      const before = await page.evaluate(() => lab.controls.history.selected?.id || "");
      await click(".next");
      await page.waitForFunction((before) => !lab.controls.browsing
        || (lab.controls.history.selected?.id || "") !== before, {}, before);
    }
    await page.waitForFunction(() => !lab.controls.browsing && !lab.controls.history.url);
  };
  const archiveVideo = async () => {
    await click(".previous"); await selected("a", "image");
    await click(".previous"); await selected("b", "video");
  };
  const idleTransport = async () => assert.deepEqual(await page.evaluate(() => ({
    calls: lab.calls, offers: lab.peerOffers, peers: lab.peers.size,
    commands: lab.wsCommands.filter((message) => message.type !== "bticino_c300x/debug/status"),
  })), { calls: [], offers: 0, peers: 0, commands: [] }, "Browsing must not record or start a device session");
  const dimensions = () => page.evaluate(() => {
    const bounds = (node) => {
      const { width, height } = node.getBoundingClientRect(); return { width, height };
    };
    return { card: bounds(lab.card), media: bounds(lab.card._mediaEl),
      picture: bounds(lab.controls.browsing ? lab.control(".archive") : lab.card._videoEl) };
  });
  const layoutFailures = [];
  const layout = async (label, collect = false) => {
    const failures = await page.evaluate(() => {
      const failures = [], root = lab.controls.shadowRoot;
      const box = lab.card.shadowRoot.querySelector("ha-card").getBoundingClientRect(), media = lab.card._mediaEl.getBoundingClientRect();
      const visible = (node) => !!node.getClientRects().length;
      if (document.documentElement.scrollWidth > innerWidth) failures.push("page overflow");
      const controls = [...root.querySelectorAll("button,input")].filter(visible);
      for (const node of controls) {
        const r = node.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) failures.push(`zero-size control: ${node.className}`);
        if (r.left < media.left - 1 || r.right > media.right + 1 || r.bottom > media.bottom + 1) failures.push(`bounds: ${node.className}`);
        if (!node.getAttribute("aria-label")) failures.push(`label: ${node.className}`);
        for (const other of controls) {
          // The picture itself is the large-view button under every control.
          if (other === node || node.classList.contains("expand") || other.classList.contains("expand")) continue;
          const s = other.getBoundingClientRect();
          if (r.left < s.right - 1 && r.right > s.left + 1 && r.top < s.bottom - 1 && r.bottom > s.top + 1) failures.push(`overlap: ${node.className}/${other.className}`);
        }
      }
      // The label and status shorten with an ellipsis by design.
      for (const selector of [".elapsed", ".stamp"]) {
        const node = root.querySelector(selector);
        if (!visible(node)) continue;
        if (node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1) failures.push(`clipped: ${selector}`);
      }
      for (const selector of [".row-action", ".home-action", ".mic-action", ".door-action", ".light-action", ".title", ".secondary"]) {
        const node = lab.card.shadowRoot.querySelector(selector), r = node.getBoundingClientRect();
        if (selector === ".mic-action" && !visible(node)) continue;
        if (selector === ".home-action" && lab.card._config.mode === "home_call") continue;
        if (!visible(node)) failures.push(`missing footer: ${selector}`);
        if (r.width <= 0 || r.height <= 0) failures.push(`zero-size footer: ${selector}`);
        if (r.left < box.left - 1 || r.right > box.right + 1 || r.bottom > box.bottom + 1 || r.top < media.bottom - 1) failures.push(`footer bounds: ${selector}`);
        if ([".title", ".secondary"].includes(selector) && node.scrollWidth > node.clientWidth + 1) {
          failures.push(`clipped footer: ${selector} (${node.clientWidth}px available, ${node.scrollWidth}px text)`);
        }
      }
      const footerButtons = [...lab.card.shadowRoot.querySelectorAll(".body button")].filter(visible);
      for (let index = 0; index < footerButtons.length; index++) {
        const r = footerButtons[index].getBoundingClientRect();
        for (const other of footerButtons.slice(index + 1)) {
          const s = other.getBoundingClientRect();
          if (r.left < s.right - 1 && r.right > s.left + 1 && r.top < s.bottom - 1 && r.bottom > s.top + 1) {
            failures.push(`footer overlap: ${footerButtons[index].className}/${other.className}`);
          }
        }
      }
      if (lab.controls.isVideo) {
        // Full screen is offered in the large view only.
        const required = [".previous", ".next", ".play", ".seek", ".mute", ".volume"];
        if (lab.card._cardMedia?.expanded) required.push(".fullscreen");
        for (const selector of required) {
          const r = root.querySelector(selector).getBoundingClientRect();
          if (r.width <= 0 || r.height <= 0) failures.push(`missing video control: ${selector}`);
        }
        const stamp = root.querySelector(".stamp").getBoundingClientRect();
        const frame = root.querySelector(".archive").getBoundingClientRect();
        // Lower right of the picture, just above the toolbar that lies on it.
        const bar = root.querySelector(".toolbar").getBoundingClientRect();
        if (Math.abs(frame.right - stamp.right - 8) > 1 || stamp.bottom > bar.top + 1 || bar.top - stamp.bottom > 24) failures.push("timestamp not bottom-right");
        if (stamp.top < frame.top || stamp.left < frame.left) failures.push("timestamp outside picture");
      }
      return failures;
    });
    if (collect) {
      if (failures.length) layoutFailures.push({ label, failures });
    } else assert.deepEqual(failures, [], label);
  };
  const narrowLayouts = async (state) => {
    assert.equal(await page.evaluate(() => lab.card.getGridOptions().min_rows), 6, "Doorstation requires at least six HA grid rows");
    for (const width of [180, 200]) {
      for (const height of ["auto", "328px"]) {
        await page.evaluate(async ({ width, height }) => {
          const mount = document.querySelector("#mount");
          mount.style.width = `${width}px`; mount.style.height = height;
          await new Promise(requestAnimationFrame);
        }, { width, height });
        for (const language of ["en", "de", "fr", "it"]) {
          await page.evaluate(async (language) => {
            lab.hass.language = language; lab.card.hass = { ...lab.hass };
            await new Promise(requestAnimationFrame);
          }, language);
          await layout(`${state} ${width}px ${height} ${language}`, true);
        }
        const sizing = await page.evaluate(() => {
          const root = lab.card.shadowRoot, bounds = (node) => node.getBoundingClientRect();
          return { cardHeight: bounds(root.querySelector("ha-card")).height,
            mediaHeight: bounds(lab.card._mediaEl).height, footerHeight: bounds(root.querySelector(".body")).height,
            textWidth: root.querySelector(".title").clientWidth,
            actionGroups: [".row-actions", ".device-actions"].map((selector) => bounds(root.querySelector(selector)).width),
            buttons: [...root.querySelectorAll(".body button")].filter((node) => node.getClientRects().length)
              .map((node) => ({ name: node.className, left: bounds(node).left, width: bounds(node).width })),
          };
        });
        assert.equal(sizing.buttons.length, state === "live" ? 5 : 4, `${state}: all expected footer actions remain visible`);
        console.log(`Narrow ${state} ${width}px ${height}: ${JSON.stringify(sizing)}`);
        await page.screenshot({ path: resolve(artifacts, `media-controls-${state}-${width}-${height}.png`) });
      }
    }
    await page.evaluate(async () => {
      const mount = document.querySelector("#mount"); mount.style.width = "600px"; mount.style.height = "420px";
      lab.hass.language = "en"; lab.card.hass = { ...lab.hass };
      await new Promise(requestAnimationFrame);
    });
  };

  await page.waitForFunction(() => lab.historyListeners.size === 1);
  assert.equal(await page.evaluate(() => lab.controls.config.enabled), true, "History defaults on when show_media_history is omitted");
  assert.equal(await page.evaluate(() => lab.controls.parentElement === lab.card._mediaEl
    && !lab.card.shadowRoot.querySelector("c300x-visitor-journal")), true);
  assert.equal(await page.evaluate(() => lab.historyFetches.length), 0, "Idle does not fetch media");
  assert.equal(await page.evaluate(() => lab.control(".previous").hidden), false,
    "Reconfiguration must restore archive navigation when history reactivates");
  await idleTransport();
  await click(".previous"); await selected("a", "image");
  assert.deepEqual(await page.evaluate(() => lab.historyFetches.map(({ url }) => url)), [
    "/api/bticino_c300x/media-history/entry-one", `/api/bticino_c300x/media-history/entry-one/${"a".repeat(64)}`,
  ]);
  const firstUrl = await page.evaluate(() => lab.controls.history.url);
  await click(".previous"); await selected("b", "video");
  assert.equal(await page.evaluate((url) => lab.revokedUrls.includes(url), firstUrl), true);
  assert.equal(await page.evaluate(() => lab.control("video").paused), true, "Archive never autoplays");
  assert.equal(await page.evaluate(() => lab.control(".stamp").dateTime),
    await page.evaluate(() => new Date(lab.controls.history.selected.at * 1000).toISOString()));
  await click(".play");
  await page.waitForFunction(() => !lab.control("video").paused && lab.control("video").currentTime > 0.2);
  await click(".play");
  assert.equal(await page.evaluate(() => lab.control("video").paused), true);
  const seek = await page.evaluateHandle(() => lab.control(".seek"));
  await seek.asElement().focus();
  await page.keyboard.press("Home");
  await page.waitForFunction(() => !lab.control("video").seeking);
  const seekStart = await page.evaluate(() => Number(lab.control(".seek").value));
  for (let index = 0; index < 10; index++) await page.keyboard.press("ArrowRight");
  await seek.dispose();
  await page.waitForFunction((start) => !lab.control("video").seeking
    && Math.abs(lab.control("video").currentTime - start - 1) < 0.15, {}, seekStart);
  const volume = await page.evaluateHandle(() => lab.control(".volume"));
  await volume.asElement().focus();
  await page.keyboard.press("Home");
  for (let index = 0; index < 7; index++) await page.keyboard.press("ArrowRight");
  await volume.dispose();
  assert.equal(await page.evaluate(() => lab.control("video").volume), 0.35);
  await click(".mute");
  assert.equal(await page.evaluate(() => lab.control("video").muted), true);
  await click(".mute");
  const pixels = await page.evaluate(() => {
    const canvas = document.createElement("canvas"); canvas.width = 320; canvas.height = 240;
    const context = canvas.getContext("2d"); context.drawImage(lab.control("video"), 0, 0);
    return [40, 100, 180, 260].map((x) => [...context.getImageData(x, 80, 1, 1).data]);
  });
  assert.ok(pixels.some(([r, g, b]) => Math.max(r, g, b) > 150 && Math.max(r, g, b) - Math.min(r, g, b) > 100), "Decoded video must contain visible synthetic colors");
  assert.ok(new Set(pixels.map((pixel) => pixel.join())).size > 2, "Video must not be a blank or solid frame");
  await click(".play");
  const refresh = await page.evaluate(() => {
    lab.control("video").loop = true;
    const state = { url: lab.controls.history.url, fetches: lab.historyFetches.length };
    lab.historyItems.reverse();
    for (const callback of lab.historyListeners) callback({ entry_id: "entry-one" });
    return state;
  });
  await page.waitForFunction((count) => lab.historyFetches.length > count && !lab.controls.history.listPromise, {}, refresh.fetches);
  assert.deepEqual(await page.evaluate(({ url, fetches }) => ({
    sameUrl: lab.controls.history.url === url, playing: !lab.control("video").paused,
    mediaFetches: lab.historyFetches.slice(fetches).filter(({ url }) => /\/[a-f0-9]{64}$/.test(url)).length,
  }), refresh), { sameUrl: true, playing: true, mediaFetches: 0 }, "History notifications must preserve unchanged playback");
  const old = await page.evaluate(() => { lab.oldVideo = lab.control("video"); return lab.controls.history.url; });
  await click(".previous"); await selected("c", "image");
  assert.equal(await page.evaluate((url) => lab.oldVideo.paused && !lab.oldVideo.getAttribute("src") && lab.revokedUrls.includes(url), old), true);
  assert.equal(await page.evaluate(() => lab.control(".previous").disabled), true);
  await click(".next"); await selected("b", "video");
  await click(".next"); await selected("a", "image");
  await click(".next");
  await page.waitForFunction(() => !lab.controls.browsing);
  assert.equal(await page.evaluate(() => lab.control(".next").disabled), true);
  await idleTransport();

  for (const kind of ["image", "video"]) {
    for (const failure of ["404", "corrupt"]) {
      const before = await page.evaluate(({ kind, failure }) => {
        lab.goodHistoryResponse = lab.historyResponse;
        lab.historyItems.find((item) => item.id === "a".repeat(64)).kind = kind;
        lab.decodeErrors = 0;
        if (failure === "corrupt") lab.control(kind === "image" ? "img" : "video")
          .addEventListener("error", () => { lab.decodeErrors++; }, { once: true });
        lab.historyResponse = (url) => url.endsWith("/" + "a".repeat(64))
          ? new Response("deliberately invalid media", { status: failure === "404" ? 404 : 200,
            headers: { "Content-Type": kind === "image" ? "image/jpeg" : "video/mp4" } })
          : lab.goodHistoryResponse(url);
        for (const callback of lab.historyListeners) callback({ entry_id: "entry-one" });
        return lab.createdUrls.length;
      }, { kind, failure });
      await click(".previous");
      await page.waitForFunction(() => lab.controls.history.error === "unavailable" && !lab.controls.history.mediaAbort);
      assert.deepEqual(await page.evaluate((before) => ({
        selected: lab.controls.history.selected?.id, url: lab.controls.history.url,
        olderEnabled: !lab.control(".previous").disabled, activeUrls: lab.activeUrls.size,
        created: lab.createdUrls.length - before, decodeErrors: lab.decodeErrors,
        statusVisible: !lab.control(".status").hidden && !!lab.control(".status").textContent,
      }), before), { selected: "a".repeat(64), url: "", olderEnabled: true, activeUrls: 0,
        created: failure === "corrupt" ? 1 : 0, decodeErrors: failure === "corrupt" ? 1 : 0,
        statusVisible: true }, `${failure} ${kind}: keep the failed cursor and release its media`);
      await click(".previous"); await selected("b", "video");
      await click(".play");
      await page.waitForFunction(() => !lab.control("video").paused && lab.control("video").currentTime > 0);
      await current();
      await page.evaluate(() => {
        lab.historyResponse = lab.goodHistoryResponse;
        lab.historyItems.find((item) => item.id === "a".repeat(64)).kind = "image";
        for (const callback of lab.historyListeners) callback({ entry_id: "entry-one" });
      });
      await idleTransport();
    }
  }

  for (const mobile of [false, true]) {
    for (const width of mobile ? [390] : [180, 200, 240, 320, 600]) {
      await page.setViewport({ width: mobile ? width : 800, height: 900, isMobile: mobile, hasTouch: mobile, deviceScaleFactor: 1 });
      await setup();
      await page.evaluate((width) => { document.querySelector("#mount").style.width = width; }, mobile ? "100%" : `${width}px`);
      for (const theme of ["light", "dark"]) {
        await page.evaluate((theme) => {
          const dark = theme === "dark", style = document.body.style;
          for (const [key, value] of Object.entries({ "--primary-text-color": dark ? "#eee" : "#222",
            "--secondary-text-color": dark ? "#bbb" : "#555", "--state-icon-color": dark ? "#bbb" : "#555",
            "--card-background-color": dark ? "#202020" : "#fff", "--divider-color": dark ? "#555" : "#ddd",
            "--disabled-text-color": dark ? "#777" : "#999" })) style.setProperty(key, value);
          style.background = dark ? "#161616" : "#fff";
        }, theme);
        const before = await dimensions();
        await archiveVideo();
        assert.deepEqual(await dimensions(), before, "Archive and live picture bounds must remain stable");
        for (const language of ["en", "de", "fr", "it"]) {
          await page.evaluate(async (language) => {
            lab.hass.language = language; lab.card.hass = { ...lab.hass };
            await new Promise(requestAnimationFrame);
          }, language);
          await layout(`${theme} ${width}px ${language} ${mobile ? "mobile" : "desktop"}`, true);
          assert.equal(await page.evaluate(() => lab.control(".stamp").textContent),
            await page.evaluate(() => new Date(lab.controls.history.selected.at * 1000).toLocaleString(lab.hass.language)));
        }
        const prefix = `media-controls-${theme}-${mobile ? "mobile-" : ""}${width}`;
        await page.screenshot({ path: resolve(artifacts, `${prefix}-video.png`) });
        await click(".next"); await selected("a", "image");
        assert.deepEqual(await dimensions(), before, "Snapshot/video switching must not resize the card");
        assert.equal(await page.evaluate(() => lab.control(".stamp").hidden), true, "Snapshot timestamp must not be duplicated");
        await page.screenshot({ path: resolve(artifacts, `${prefix}-image.png`) });
        await current();
        assert.equal(await page.evaluate(() => lab.activeUrls.size), 0);
      }
    }
  }
  await page.setViewport({ width: 800, height: 900 });
  await setup();
  await page.evaluate(() => { document.querySelector("#mount").style.width = "600px"; lab.hass.language = "en"; lab.card.hass = { ...lab.hass }; });
  await archiveVideo();
  await narrowLayouts("archive");
  if (await page.evaluate(() => document.fullscreenEnabled)) {
    // Full screen is offered in the large view; a picture click right after an
    // arrow is ignored, so wait for the window rather than assume the first click.
    await page.waitForFunction(() => Date.now() - (lab.controls.navigatedAt || 0) > 800);
    await click(".expand");
    await page.waitForFunction(() => lab.card._cardMedia.expanded && !lab.control(".fullscreen").hidden);
    await click(".fullscreen");
    await page.waitForFunction(() => !!lab.card.shadowRoot.fullscreenElement);
    assert.equal(await page.evaluate(() => lab.card.shadowRoot.fullscreenElement === lab.card.shadowRoot.querySelector("ha-card")), true, "Fullscreen must include footer, not only video");
    await layout("Fullscreen retains primary/home/door/light/name/status");
    await page.screenshot({ path: resolve(artifacts, "media-controls-fullscreen.png") });
    await click(".fullscreen");
    await page.waitForFunction(() => !document.fullscreenElement);
    await click(".close");
    await page.waitForFunction(() => !lab.card._cardMedia.expanded);
  } else console.log("Fullscreen unavailable in this browser; fullscreen entry skipped");

  await idleTransport();
  await click(".play");
  await page.evaluate(() => {
    lab.ringUrl = lab.controls.history.url;
    lab.footerNodes = [...lab.card.shadowRoot.querySelectorAll(".row-action,.home-action,.door-action,.light-action,.title,.secondary")];
    Object.assign(lab.hass.states[lab.camera].attributes, { media_state: "ring_pending", media_primary_action: "answer_ring" });
    lab.card.hass = { ...lab.hass };
  });
  await page.waitForFunction(() => !lab.controls.browsing);
  assert.equal(await page.evaluate(() => lab.control("video").paused && !lab.control("video").getAttribute("src")
    && lab.revokedUrls.includes(lab.ringUrl) && lab.footerNodes.every((node) => node.isConnected)), true);
  // The existing passive ring preview is allowed, unlike archive-triggered streams.
  await page.waitForFunction(() => lab.card._videoEl.readyState >= 2 && !lab.card._lifecycle.previewStarting);
  await page.waitForFunction(() => lab.card.shadowRoot.querySelector(".row-action").classList.contains("answerable"));
  assert.equal(await page.evaluate(() => lab.card.shadowRoot.querySelector(".row-action").classList.contains("answerable")), true);
  assert.equal(await page.evaluate(() => lab.card.shadowRoot.querySelector(".title").textContent), "Door");
  await layout("Incoming ring retains existing call footer");
  await narrowLayouts("ring");
  assert.deepEqual(await page.evaluate(() => lab.calls), [], "Incoming ring must not answer or record automatically");
  await page.evaluate(() => {
    Object.assign(lab.hass.states[lab.camera].attributes, { media_state: "idle", media_primary_action: "start_stream" });
    lab.card.hass = { ...lab.hass };
  });
  await page.waitForFunction(() => lab.peers.size === 0 && !lab.card._webrtc.running);

  const previewSize = await dimensions();
  await page.evaluate(() => { lab.withAudio = true; });
  await click(".row-action", true);
  await page.waitForFunction(() => lab.card._videoEl.readyState >= 2 && lab.controls.config.hasAudio);
  assert.deepEqual(await dimensions(), previewSize, "Live start must preserve snapshot/archive sizing");
  await narrowLayouts("live");
  const liveBefore = await page.evaluate(() => ({ fetches: lab.historyFetches.length, offers: lab.peerOffers, calls: lab.calls.length }));
  await page.evaluate(() => { lab.control(".previous").click(); lab.control(".next").click(); });
  assert.equal(await page.evaluate(() => lab.controls.browsing), false, "Live cannot navigate into archive");
  assert.deepEqual(await page.evaluate(() => ({ fetches: lab.historyFetches.length, offers: lab.peerOffers, calls: lab.calls.length })), liveBefore);
  await page.evaluate(() => {
    lab.card.setConfig({ ...lab.card._config, show_media_history: false }); lab.card.hass = { ...lab.hass };
  });
  await page.waitForFunction(() => lab.peers.size === 0 && lab.historyListeners.size === 0);
  await click(".row-action", true);
  await page.waitForFunction(() => lab.card._videoEl.readyState >= 2 && lab.controls.config.hasAudio);
  assert.equal(await page.evaluate(() => lab.control(".previous").hidden && !lab.control(".mute").hidden
    && !lab.control(".volume").hidden && lab.control(".fullscreen").hidden), true,
    "Disabled history retains live controls; full screen stays in the large view");
  await click(".mute");
  assert.equal(await page.evaluate(() => lab.card._playbackMuted), true, "Live mute must reach parent playback");
  await click(".mute");
  await page.screenshot({ path: resolve(artifacts, "media-controls-history-disabled-live.png") });
  await click(".row-action", true);
  await page.waitForFunction(() => lab.peers.size === 0);

  await page.evaluate(() => {
    lab.card.setConfig({ entity: lab.camera, mode: "home_call", ringback_tone: false, name: "Door" });
    lab.card.hass = { ...lab.hass };
  });
  assert.deepEqual(await page.evaluate(() => {
    const { rows, min_rows, max_rows } = lab.card.getGridOptions(); return { rows, min_rows, max_rows };
  }), { rows: 2, min_rows: 2, max_rows: 2 }, "Home Call keeps a two-row grid allocation");
  for (const state of ["idle", "active"]) {
    if (state === "active") {
      await click(".row-action", true);
      await page.waitForFunction(() => lab.card._micStream?.getAudioTracks()[0]?.readyState === "live"
        && lab.card._webrtc.remoteStream?.getAudioTracks().length === 1 && !lab.card._lifecycle.startingCall);
      await page.evaluate(() => {
        Object.assign(lab.hass.states[lab.camera].attributes, { media_state: "home_call_active", media_primary_action: "hangup" });
        lab.card.hass = { ...lab.hass };
      });
      await page.waitForFunction(() => !lab.card.shadowRoot.querySelector(".mic-action").classList.contains("hidden"));
    }
    for (const width of [180, 200]) {
      await page.evaluate(async (width) => {
        const mount = document.querySelector("#mount"); mount.style.width = `${width}px`; mount.style.height = "104px";
        await new Promise(requestAnimationFrame);
      }, width);
      for (const language of ["en", "de", "fr", "it"]) {
        await page.evaluate(async (language) => {
          lab.hass.language = language; lab.card.hass = { ...lab.hass };
          await new Promise(requestAnimationFrame);
        }, language);
        await layout(`Home Call ${state} ${width}px 104px ${language}`, true);
      }
      assert.deepEqual(await page.evaluate(() => ({
        mediaVisible: !!lab.card._mediaEl.getClientRects().length,
        actions: [...lab.card.shadowRoot.querySelectorAll(".body button")].filter((node) => node.getClientRects().length).length,
        height: lab.card.shadowRoot.querySelector("ha-card").getBoundingClientRect().height,
        footerFits: lab.card.shadowRoot.querySelector(".body").getBoundingClientRect().height <= 104,
      })), { mediaVisible: false, actions: state === "active" ? 4 : 3, height: 104, footerFits: true },
      `Home Call ${state} ${width}px must retain every action within two grid rows`);
      await page.screenshot({ path: resolve(artifacts, `media-controls-home-call-${state}-${width}-104px.png`) });
    }
  }
  await click(".mic-action", true);
  assert.equal(await page.evaluate(() => lab.card._micStream.getAudioTracks()[0].enabled), false);
  await click(".mic-action", true);
  assert.equal(await page.evaluate(() => lab.card._micStream.getAudioTracks()[0].enabled), true);
  await page.evaluate(() => { lab.homeMicTracks = lab.card._micStream.getTracks(); });
  await click(".row-action", true);
  await page.waitForFunction(() => lab.peers.size === 0 && lab.homeMicTracks.every((track) => track.readyState === "ended"));
  await page.evaluate(() => {
    const mount = document.querySelector("#mount"); mount.style.width = "600px"; mount.style.height = "420px";
    Object.assign(lab.hass.states[lab.camera].attributes, { media_state: "idle", media_primary_action: "start_stream" });
    lab.hass.language = "en";
    lab.card.hass = { ...lab.hass };
  });

  // Test list and media requests separately against every ownership boundary.
  for (const boundary of ["disable", "reconfigure", "unload", "detach"]) {
    for (const kind of ["list", "media"]) {
      await page.evaluate(() => {
        lab.holdHistoryFetch = null;
        lab.pendingHistory = null;
        if (!lab.card.isConnected) document.querySelector("#mount").append(lab.card);
        lab.card.setConfig({ entity: lab.camera, mode: "auto", ringback_tone: false, show_media_history: true, name: "Door" });
        lab.card.hass = { ...lab.hass };
      });
      await page.waitForFunction(() => lab.historyListeners.size === 1);
      await page.evaluate((kind) => { lab.holdHistoryFetch = (url) => kind === "list" ? url.endsWith("entry-one") : /\/[a-f0-9]{64}$/.test(url); }, kind);
      await click(".previous");
      await page.waitForFunction(() => !!lab.pendingHistory);
      const late = await page.evaluate(async (boundary) => {
        const pending = lab.pendingHistory, created = lab.createdUrls.length;
        if (boundary === "disable") lab.card.setConfig({ ...lab.card._config, show_media_history: false });
        if (boundary === "reconfigure") {
          lab.oldHistoryListeners = lab.historyListeners;
          lab.oldHistoryCallback = [...lab.historyListeners][0];
          lab.historyListeners = new Set();
          lab.hass.connection = { ...lab.hass.connection };
          lab.card.hass = { ...lab.hass };
        }
        if (boundary === "unload") for (const callback of lab.historyListeners) callback({ entry_id: "entry-one", closed: true });
        if (boundary === "detach") lab.card.remove();
        pending.finish();
        await new Promise((done) => setTimeout(done, 0));
        return { aborted: pending.request.aborted, newUrls: lab.createdUrls.length - created,
          activeUrls: lab.activeUrls.size, browsing: lab.controls.browsing, url: lab.controls.history.url,
          listeners: boundary === "reconfigure" ? lab.oldHistoryListeners.size : lab.historyListeners.size };
      }, boundary);
      assert.deepEqual(late, { aborted: true, newUrls: 0, activeUrls: 0, browsing: false, url: "", listeners: 0 }, `${boundary} pending ${kind}`);
      if (boundary === "reconfigure") {
        assert.equal(await page.evaluate(() => {
          const count = lab.historyFetches.length;
          lab.oldHistoryCallback({ entry_id: "entry-one" });
          return count === lab.historyFetches.length;
        }), true, "Old subscription cannot trigger a fetch after reconfiguration");
      }
    }
  }
  await page.evaluate(() => {
    lab.holdHistoryFetch = null;
    document.querySelector("#mount").append(lab.card);
    lab.card.hass = { ...lab.hass };
  });
  await page.waitForFunction(() => lab.historyListeners.size === 1);
  await page.evaluate(() => {
    lab.normalHistoryResponse = lab.historyResponse;
    lab.bodyCancelled = 0;
    lab.historyResponse = (url) => url.endsWith("entry-one") ? lab.normalHistoryResponse(url)
      : new Response(new ReadableStream({ cancel() { lab.bodyCancelled++; } }), {
        headers: { "Content-Type": "image/jpeg", "Content-Length": String(512 * 1024 + 1) },
      });
  });
  await click(".previous");
  await page.waitForFunction(() => lab.controls.history.error === "unavailable");
  assert.deepEqual(await page.evaluate(() => [lab.bodyCancelled, lab.activeUrls.size, lab.controls.browsing]),
    [1, 0, true], "Oversized response must cancel its body without losing the history cursor");
  assert.equal(await page.evaluate(() => !lab.control(".status").hidden && !!lab.control(".status").textContent), true);
  await current();
  await page.evaluate(() => {
    lab.bodyReading = false;
    lab.historyResponse = (url) => url.endsWith("entry-one") ? lab.normalHistoryResponse(url)
      : new Response(new ReadableStream({
        start(controller) { controller.enqueue(new Uint8Array([255, 216])); lab.bodyReading = true; },
        cancel() { lab.bodyCancelled++; },
      }), { headers: { "Content-Type": "image/jpeg" } });
  });
  await click(".previous");
  await page.waitForFunction(() => lab.bodyReading && !!lab.controls.history.mediaAbort);
  await current();
  await page.waitForFunction(() => lab.bodyCancelled === 2);
  assert.equal(await page.evaluate(() => lab.historyFetches.at(-1).aborted && lab.activeUrls.size === 0), true,
    "Leaving archive must cancel a pending body read, not only a pending fetch");
  await page.evaluate(() => { lab.historyResponse = lab.normalHistoryResponse; });
  await archiveVideo();
  await click(".play");
  await page.evaluate(() => { lab.closedVideo = lab.control("video"); lab.card.remove(); });
  await page.waitForFunction(() => lab.historyListeners.size === 0 && lab.listeners.size === 0 && lab.peers.size === 0);
  assert.equal(await page.evaluate(() => lab.closedVideo.paused && !lab.closedVideo.getAttribute("src") && lab.activeUrls.size === 0), true);
  assert.deepEqual(errors, []);
  console.log("Media behavior: 404/decode recovery, older playback, fullscreen, ring/live priority and resource cleanup: PASS");
  assert.deepEqual(layoutFailures, [], "Responsive layout matrix");
  await rm(resolve(artifacts, "media-controls-failure.png"), { force: true });
  console.log("Unified media controls: mixed history, real video/seek/volume, responsive themes, fullscreen, ring/live priority, disabled history and abort/URL/subscription cleanup: PASS");
  console.log(`Screenshots: ${artifacts}/media-controls-*.png`);
} catch (error) {
  await page?.screenshot({ path: resolve(artifacts, "media-controls-failure.png") }).catch(() => {});
  console.error("Browser errors:", errors);
  console.error("Browser state:", await page?.evaluate(() => ({
    selected: lab.controls?.history.selected, busy: lab.controls?.config.busy,
    historyActive: lab.controls?.history.active, previousHidden: lab.control(".previous").hidden,
    configureSignature: lab.controls?.configureSignature,
    video: { time: lab.control("video").currentTime, paused: lab.control("video").paused,
      seeking: lab.control("video").seeking, ready: lab.control("video").readyState },
    action: lab.card.shadowRoot.querySelector(".row-action").outerHTML,
    peers: lab.peers.size, listeners: lab.historyListeners.size, urls: lab.activeUrls.size,
  })).catch(() => null));
  throw error;
} finally {
  await browser?.close();
  await new Promise((done) => server.close(done));
}
