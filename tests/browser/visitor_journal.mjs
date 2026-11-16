import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve, dirname, sep } from "node:path";
import { execFileSync } from "node:child_process";
import puppeteer from "puppeteer-core";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "../../custom_components/bticino_c300x/frontend");
const artifacts = resolve(here, "../../.artifacts/browser");
const clip = execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "color=green:size=160x120:rate=10", "-t", "1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"]);
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
let browser;
try {
  browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN || "/usr/bin/google-chrome", headless: true,
    args: ["--disable-background-networking", ...(process.env.CI ? ["--no-sandbox"] : [])] });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    if ([origin, "null"].includes(new URL(request.url()).origin)) request.continue();
    else { errors.push("Unexpected external request"); request.abort(); }
  });
  await mkdir(artifacts, { recursive: true });
  await page.goto(origin);
  await page.waitForFunction(() => !!window.lab);
  await page.evaluate(async () => {
    const image = await new Promise((done) => lab.source.toBlob(done, "image/jpeg"));
    const video = await (await fetch("/synthetic.mp4")).blob();
    const now = Date.now() / 1000;
    lab.visits = [
      { id: "a".repeat(32), at: now, image_at: now + 2, video_at: now + 5, image_revision: "1".repeat(64), video_revision: "2".repeat(64), expires_at: now + 86400, outcome: "answered", image: true, video: true },
      { id: "b".repeat(32), at: now - 60, expires_at: now + 86400, outcome: "unknown", image: true, video: false },
      { id: "c".repeat(32), at: now - 120, expires_at: now + 86400, outcome: "unknown", image: false, video: false },
    ];
    lab.fetches = [];
    lab.journalListeners = new Set();
    const subscribe = lab.hass.connection.subscribeMessage;
    lab.hass.connection.subscribeMessage = async (callback, message) => {
      if (message.type !== "bticino_c300x/visitor_journal/subscribe") return subscribe(callback, message);
      if (message.entry_id !== "entry-one") throw new Error("Unexpected journal entry");
      const listeners = lab.journalListeners;
      listeners.add(callback);
      return () => listeners.delete(callback);
    };
    lab.hass.fetchWithAuth = async (url, options) => {
      lab.fetches.push({ url, signal: options.signal });
      if (url.endsWith("/image")) return new Response(image, { headers: { "Content-Type": "image/jpeg" } });
      if (url.endsWith("/video")) return new Response(video, { headers: { "Content-Type": "video/mp4" } });
      return Response.json({ visits: lab.visits });
    };
    lab.readJournal = lab.hass.fetchWithAuth;
    lab.revoked = [];
    const revoke = URL.revokeObjectURL.bind(URL);
    URL.revokeObjectURL = (url) => { lab.revoked.push(url); revoke(url); };
    lab.journal = lab.card.shadowRoot.querySelector("c300x-visitor-journal");
  });
  assert.equal(await page.evaluate(() => lab.journal.hidden), true);
  assert.equal(await page.evaluate(() => lab.fetches.length), 0);
  await page.evaluate(() => { lab.card.setConfig({ entity: lab.camera, show_visitor_journal: true }); lab.card.hass = lab.hass; });
  await page.waitForFunction(() => !lab.journal.hidden);
  assert.equal(await page.evaluate(() => lab.fetches.length), 0, "Collapsed journal must not fetch");
  await page.evaluate(() => { lab.journal.details.open = true; });
  await page.waitForFunction(() => lab.journal.items.length === 3);
  assert.equal(await page.evaluate(() => lab.journalListeners.size), 1);
  await page.evaluate(() => { lab.journal.shadowRoot.querySelector(".visit").focus(); });
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => !!lab.journal.url);
  await page.waitForFunction(() => lab.journal.shadowRoot.querySelector("img").naturalWidth > 0);
  assert.equal(await page.evaluate(() => lab.journal.shadowRoot.querySelector(".previous").disabled), true);
  const firstUrl = await page.evaluate(() => lab.journal.url);
  await page.keyboard.press("ArrowRight");
  await page.waitForFunction(() => lab.journal.index === 1 && !!lab.journal.url);
  assert.equal(await page.evaluate((url) => lab.revoked.includes(url), firstUrl), true);
  await page.evaluate(() => lab.journal.shadowRoot.querySelector(".next").click());
  assert.equal(await page.evaluate(() => lab.journal.index), 2);
  assert.equal(await page.evaluate(() => lab.journal.shadowRoot.querySelector(".next").disabled), true);
  assert.equal(await page.evaluate(() => lab.journal.url), "");
  await page.evaluate(() => {
    const frame = lab.journal.shadowRoot.querySelector(".frame");
    frame.dispatchEvent(new PointerEvent("pointerdown", { pointerType: "touch", pointerId: 2, clientX: 30, clientY: 50 }));
    frame.dispatchEvent(new PointerEvent("pointerup", { pointerType: "touch", pointerId: 2, clientX: 110, clientY: 54 }));
  });
  await page.waitForFunction(() => lab.journal.index === 1 && !!lab.journal.url);
  await page.evaluate(() => lab.journal.show(0, "video"));
  await page.waitForFunction(() => lab.journal.shadowRoot.querySelector("video").readyState >= 2);
  assert.equal(await page.evaluate(() => lab.journal.shadowRoot.querySelector("video").paused), true, "No autoplay");
  await page.evaluate(() => lab.journal.shadowRoot.querySelector("video").play());
  await page.evaluate(() => lab.journal.step(1));
  await page.waitForFunction(() => !!lab.journal.url);
  assert.equal(await page.evaluate(() => {
    const video = lab.journal.shadowRoot.querySelector("video");
    return video.paused && !video.getAttribute("src");
  }), true);
  await page.evaluate(async () => {
    lab.originalVisits = structuredClone(lab.visits);
    await lab.journal.show(0, "video");
  });
  await page.waitForFunction(() => lab.journal.shadowRoot.querySelector("video").readyState >= 2);
  const playing = await page.evaluate(async () => {
    const video = lab.journal.shadowRoot.querySelector("video");
    video.loop = true;
    await video.play();
    const url = lab.journal.url;
    const fetches = lab.fetches.length;
    lab.visits[0].outcome = "unknown";
    lab.visits[0].image_revision = "3".repeat(64);
    lab.visits.unshift({ ...lab.visits[1], id: "d".repeat(32), at: Date.now() / 1000 });
    await lab.journal.load();
    return { sameUrl: lab.journal.url === url, paused: video.paused, index: lab.journal.index,
      mediaFetches: lab.fetches.slice(fetches).filter(({ url }) => url.endsWith("/video") || url.endsWith("/image")).length };
  });
  assert.deepEqual(playing, { sameUrl: true, paused: false, index: 1, mediaFetches: 0 });
  await page.evaluate(async () => {
    await lab.journal.show(3);
    lab.visits[3].video = true;
    lab.visits[3].video_revision = "4".repeat(64);
    lab.visits[3].video_at = Date.now() / 1000;
    for (const callback of lab.journalListeners) callback({ entry_id: "entry-one" });
  });
  await page.waitForFunction(() => !!lab.journal.url && lab.journal.shadowRoot.querySelector("video").readyState >= 2);
  assert.equal(await page.evaluate(() => lab.journal.shadowRoot.querySelector("video").paused), true);
  const replacedUrl = await page.evaluate(() => {
    const url = lab.journal.url;
    lab.visits[3].video_revision = "5".repeat(64);
    for (const callback of lab.journalListeners) callback({ entry_id: "entry-one" });
    return url;
  });
  await page.waitForFunction((old) => !!lab.journal.url && lab.journal.url !== old, {}, replacedUrl);
  assert.equal(await page.evaluate((old) => lab.revoked.includes(old) && lab.journal.shadowRoot.querySelector("video").paused, replacedUrl), true);
  await page.evaluate(async () => {
    lab.visits = lab.originalVisits;
    lab.journal.shadowRoot.querySelector("video").loop = false;
    await lab.journal.load();
    await lab.journal.show(1);
  });
  for (const width of [240, 320, 390, 1024]) {
    await page.setViewport({ width, height: 800 });
    for (const language of ["en", "de", "fr", "it"]) {
      const result = await page.evaluate(async (language) => {
        lab.hass.language = language;
        lab.card.hass = { ...lab.hass };
        await new Promise(requestAnimationFrame);
        const root = lab.journal.shadowRoot;
        const dialog = lab.journal.dialog.getBoundingClientRect();
        const frame = root.querySelector(".frame").getBoundingClientRect();
        const buttons = [...root.querySelectorAll("dialog button")];
        return { inside: dialog.left >= 0 && dialog.right <= innerWidth && dialog.top >= 0 && dialog.bottom <= innerHeight,
          overflow: document.documentElement.scrollWidth > innerWidth,
          labels: buttons.every((button) => !!button.getAttribute("aria-label")),
          frame: { width: frame.width, height: frame.height },
          timestamp: root.querySelector("h2").textContent,
          expected: new Date((lab.journal.items[lab.journal.index][`${lab.journal.kind}_at`] || lab.journal.items[lab.journal.index].at) * 1000).toLocaleString(language) };
      }, language);
      assert.ok(result.inside && !result.overflow && result.labels, `${width} ${language}`);
      assert.equal(result.timestamp, result.expected);
      const after = await page.evaluate(async () => {
        await lab.journal.show(2);
        const rect = lab.journal.shadowRoot.querySelector(".frame").getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      });
      assert.deepEqual(after, result.frame, "Missing media must not resize viewer");
      await page.evaluate(() => lab.journal.show(1));
    }
    await page.screenshot({ path: resolve(artifacts, `visitor-journal-${width}.png`) });
  }
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => !lab.journal.dialog.open && !lab.journal.url);
  assert.equal(await page.evaluate(() => lab.journal.url), "");
  const focus = await page.evaluate(async () => {
    lab.beforeFocusVisits = structuredClone(lab.visits);
    lab.focusedVisit = lab.journal.shadowRoot.querySelectorAll(".visit")[1];
    lab.focusedVisit.focus();
    lab.visits[1].outcome = "answered";
    await lab.journal.load();
    const unchanged = lab.journal.shadowRoot.activeElement === lab.focusedVisit;
    lab.visits.unshift({ ...lab.visits[0], id: "d".repeat(32), at: Date.now() / 1000 });
    await lab.journal.load();
    return { unchanged, reordered: lab.journal.shadowRoot.activeElement === lab.focusedVisit,
      sameNode: lab.journal.shadowRoot.querySelectorAll(".visit")[2] === lab.focusedVisit };
  });
  assert.deepEqual(focus, { unchanged: true, reordered: true, sameNode: true });
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => lab.journal.dialog.open && !!lab.journal.url);
  assert.equal(await page.evaluate(() => lab.journal.items[lab.journal.index].id), "b".repeat(32), "Reused row must not retain its old array index");
  assert.equal(await page.evaluate(async () => {
    const focused = lab.journal.shadowRoot.activeElement;
    await lab.journal.load();
    return lab.journal.shadowRoot.activeElement === focused;
  }), true, "List updates must not steal modal focus");
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => !lab.journal.dialog.open && !lab.journal.url);
  assert.equal(await page.evaluate(() => lab.journal.shadowRoot.activeElement === lab.focusedVisit), true);
  assert.equal(await page.evaluate(async () => {
    lab.visits = lab.visits.filter((item) => item.id !== "b".repeat(32));
    await lab.journal.load();
    return lab.journal.shadowRoot.activeElement === lab.journal.shadowRoot.querySelector("summary");
  }), true, "A removed focused visit returns focus to the journal summary");
  const pagination = await page.evaluate(async () => {
    const now = Date.now() / 1000;
    lab.visits = Array.from({ length: 25 }, (_, index) => ({ ...lab.visits[0], id: index.toString(16).padStart(32, "0"), at: now - index }));
    await lab.journal.load();
    const focused = lab.journal.shadowRoot.querySelectorAll(".visit")[19];
    focused.focus();
    lab.visits.unshift({ ...lab.visits[0], id: "e".repeat(32), at: now + 1 });
    await lab.journal.load();
    return { retained: lab.journal.shadowRoot.activeElement === focused, count: lab.journal.shadowRoot.querySelectorAll(".visit").length };
  });
  assert.deepEqual(pagination, { retained: true, count: 21 });
  await page.evaluate(async () => {
    lab.visits = lab.beforeFocusVisits;
    lab.journal.visible = 20;
    await lab.journal.load();
  });
  await page.evaluate(() => {
    lab.hass.fetchWithAuth = async () => new Promise((done) => { lab.finishMedia = done; });
    lab.journal.hass = lab.hass;
    lab.journal.dialog.showModal();
    void lab.journal.show(0);
  });
  await page.waitForFunction(() => !!lab.finishMedia);
  await page.evaluate(() => {
    lab.card.setConfig({ entity: lab.camera, show_visitor_journal: false });
    lab.card.hass = lab.hass;
    lab.finishMedia(new Response("stale", { headers: { "Content-Type": "image/jpeg" } }));
  });
  await page.waitForFunction(() => lab.journal.hidden);
  assert.deepEqual(await page.evaluate(() => [lab.journal.url, lab.journalListeners.size, lab.peers.size, lab.calls.length]), ["", 0, 0, 0]);
  await page.evaluate(() => {
    lab.hass.fetchWithAuth = lab.readJournal;
    lab.card.setConfig({ entity: lab.camera, show_visitor_journal: true });
    lab.card.hass = lab.hass;
  });
  await page.waitForFunction(() => lab.journal.items.length === 3);
  await page.evaluate(() => { lab.journal.dialog.showModal(); return lab.journal.show(0, "video"); });
  await page.waitForFunction(() => lab.journal.shadowRoot.querySelector("video").readyState >= 2);
  await page.evaluate(async () => {
    lab.closedVideo = lab.journal.shadowRoot.querySelector("video");
    await lab.closedVideo.play();
    lab.detachedUrl = lab.journal.url;
    lab.card.remove();
  });
  assert.equal(await page.evaluate(() => lab.closedVideo.paused && !lab.closedVideo.getAttribute("src")
    && !lab.journal.url && lab.revoked.includes(lab.detachedUrl) && lab.journalListeners.size === 0), true);
  await page.evaluate(() => document.querySelector("#mount").append(lab.card));
  await page.waitForFunction(() => lab.journal.items.length === 3);
  assert.equal(await page.evaluate(() => lab.journalListeners.size), 1);
  assert.deepEqual(await page.evaluate(() => [lab.peers.size, lab.calls.length]), [0, 0]);
  await page.evaluate(() => {
    lab.oldJournalListeners = lab.journalListeners;
    lab.oldJournalCallback = [...lab.journalListeners][0];
    lab.journalListeners = new Set();
    lab.hass = { ...lab.hass, connection: { ...lab.hass.connection } };
    lab.card.hass = lab.hass;
  });
  await page.waitForFunction(() => lab.journal.items.length === 3 && lab.journalListeners.size === 1 && !lab.journal.loading);
  assert.equal(await page.evaluate(() => lab.oldJournalListeners.size), 0);
  assert.equal(await page.evaluate(() => lab.journal.connection === lab.hass.connection), true);
  assert.equal(await page.evaluate(() => {
    const count = lab.fetches.length;
    lab.oldJournalCallback({ entry_id: "entry-one" });
    return lab.fetches.length === count;
  }), true);
  await page.evaluate(() => {
    for (const callback of lab.journalListeners) callback({ entry_id: "entry-one", closed: true });
  });
  assert.deepEqual(await page.evaluate(() => [lab.journal.active, lab.journalListeners.size, lab.journal.items.length]), [false, 0, 0]);
  // HA delivering state after entry reload must work even if the visible signature is identical.
  await page.evaluate(() => { lab.card.hass = { ...lab.hass }; });
  await page.waitForFunction(() => lab.journal.items.length === 3 && lab.journalListeners.size === 1);
  await page.evaluate(() => lab.card.remove());
  assert.deepEqual(errors, []);
  console.log("Visitor journal: opt-in, image/video, keyboard/swipe, bounds, four languages, cleanup, no device calls: PASS");
} finally {
  await browser?.close();
  await new Promise((done) => server.close(done));
}
