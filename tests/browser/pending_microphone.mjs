import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { dirname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { checkRingEndStart } from "./ring_end_start.mjs";

export async function checkPendingMicrophone(page) {
  const cases = [
    { state: "unavailable", update: "hass" },
    { state: "unknown", update: "hass" },
    { state: "missing", update: "hass" },
    { state: "unavailable", update: "event" },
    { state: "missing", update: "event" },
    { state: "unavailable", update: "hass", recover: true },
    { state: "unavailable", update: "hass", reject: true },
    // Exercise the post-await check independently of HA's state notification.
    { state: "unavailable", update: "cached" },
    { state: "unavailable", update: "cached", reject: true },
  ];
  for (const mode of ["doorstation", "home_call", "answered_preview"]) {
    for (const scenario of cases) {
      await page.reload();
      await page.waitForFunction(() => !!window.lab);
      const result = await page.evaluate(async ({ mode, ...scenario }) => {
        const card = lab.card;
        let resolvePermission, rejectPermission, offers = 0;
        navigator.mediaDevices.getUserMedia = () => new Promise((resolve, reject) => {
          resolvePermission = resolve;
          rejectPermission = reject;
        });
        const subscribe = lab.hass.connection.subscribeMessage;
        lab.hass.connection.subscribeMessage = (...args) => {
          offers++;
          return subscribe(...args);
        };
        const audio = new AudioContext();
        const stream = audio.createMediaStreamDestination().stream;
        if (mode === "answered_preview") card._lifecycle.answeringDoorbell = true;
        if (mode === "home_call") {
          card.setConfig({ entity: lab.camera, mode: "home_call", ringback_tone: false });
          card.hass = lab.hass;
        }
        const generation = card._mediaGeneration;
        const start = mode === "answered_preview" ? card._startAnsweredDoorbellStream()
          : mode === "home_call" ? card._actions.startHomeCallAudio() : card._startTalkback();
        const original = lab.hass.states[lab.camera];
        const changed = scenario.state === "missing" ? null
          : { state: scenario.state, attributes: { media_state: "idle" } };
        if (scenario.update === "cached") {
          original.state = scenario.state;
        } else if (scenario.update === "event") {
          // HA's state_changed callback may arrive before the next hass setter.
          card._handleStateChanged({ data: { entity_id: lab.camera, new_state: changed } });
        } else {
          if (changed) lab.hass.states[lab.camera] = changed;
          else delete lab.hass.states[lab.camera];
          card.hass = { ...lab.hass };
        }
        if (scenario.recover) {
          lab.hass.states[lab.camera] = original;
          card.hass = { ...lab.hass };
        }
        if (scenario.reject) rejectPermission(new DOMException("Denied", "NotAllowedError"));
        else resolvePermission(stream);
        await start;
        const result = {
          offers, calls: lab.calls.length, peers: lab.peers.size,
          invalidated: card._mediaGeneration > generation,
          retainedMic: !!card._micStream,
          trackStopped: scenario.reject || stream.getAudioTracks()[0].readyState === "ended",
          starting: !!(card._talkbackStarting || card._lifecycle.startingCall
            || card._lifecycle.answeringDoorbell),
        };
        stream.getTracks().forEach(track => track.stop());
        card._closePeer(true);
        await audio.close();
        return result;
      }, { mode, ...scenario });
      assert.deepEqual(result, {
        offers: 0, calls: 0, peers: 0, invalidated: true,
        retainedMic: false, trackStopped: true, starting: false,
      }, JSON.stringify({ mode, ...scenario }));
    }
  }

  // A late result from the cancelled generation must not close its successor.
  for (const denied of [false, true]) {
    await page.reload();
    await page.waitForFunction(() => !!window.lab);
    const result = await page.evaluate(async (denied) => {
      const audio = new AudioContext();
      const oldStream = audio.createMediaStreamDestination().stream;
      const newStream = audio.createMediaStreamDestination().stream;
      let resolveOld, rejectOld;
      navigator.mediaDevices.getUserMedia = () => new Promise((resolve, reject) => {
        resolveOld = resolve;
        rejectOld = reject;
      });
      const first = lab.card._startTalkback();
      const original = lab.hass.states[lab.camera];
      lab.hass.states[lab.camera] = { state: "unavailable", attributes: {} };
      lab.card.hass = { ...lab.hass };
      lab.hass.states[lab.camera] = original;
      lab.card.hass = { ...lab.hass };
      navigator.mediaDevices.getUserMedia = async () => newStream;
      const second = await lab.card._startTalkback();
      if (denied) rejectOld(new DOMException("Denied", "NotAllowedError"));
      else resolveOld(oldStream);
      const result = { first: await first, second, peers: lab.peers.size,
        microphone: lab.card._micStream === newStream,
        newTrack: newStream.getAudioTracks()[0].readyState,
        oldStopped: denied || oldStream.getAudioTracks()[0].readyState === "ended" };
      lab.card._closePeer(true);
      oldStream.getTracks().forEach(track => track.stop());
      await audio.close();
      return result;
    }, denied);
    assert.deepEqual(result, { first: false, second: true, peers: 1,
      microphone: true, newTrack: "live", oldStopped: true });
  }

  // Permission denial on an available camera still permits receive-only media.
  for (const denied of [false, true]) {
    await page.reload();
    await page.waitForFunction(() => !!window.lab);
    const result = await page.evaluate(async (denied) => {
      const audio = new AudioContext();
      const stream = audio.createMediaStreamDestination().stream;
      navigator.mediaDevices.getUserMedia = async () => {
        if (denied) throw new DOMException("Denied", "NotAllowedError");
        return stream;
      };
      const started = await lab.card._startTalkback();
      const result = { started, peers: lab.peers.size, microphone: !!lab.card._micStream };
      lab.card._closePeer(true);
      stream.getTracks().forEach(track => track.stop());
      await audio.close();
      return result;
    }, denied);
    assert.deepEqual(result, { started: true, peers: 1, microphone: !denied });
  }
  await page.reload();
  await page.waitForFunction(() => !!window.lab);
}

// Standalone focused runner; smoke also invokes the same regression checks.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const here = dirname(fileURLToPath(import.meta.url));
  const frontend = resolve(here, "../../custom_components/bticino_c300x/frontend");
  const server = createServer(async (request, response) => {
    const name = new URL(request.url, "http://localhost").pathname;
    let path;
    if (name === "/") path = resolve(here, "fixture.html");
    else if (name === "/fixture.mjs") path = resolve(here, "fixture.mjs");
    else if (name.startsWith("/frontend/")) {
      path = resolve(frontend, name.slice(10));
      if (!path.startsWith(frontend + sep) || !path.endsWith(".js")) path = null;
    }
    if (!path) { response.writeHead(404).end(); return; }
    try {
      response.setHeader("Content-Type", path.endsWith("html") ? "text/html" : "text/javascript");
      response.end(await readFile(path));
    } catch { response.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  let browser;
  try {
    browser = await puppeteer.launch({
      executablePath: process.env.CHROME_BIN || "/usr/bin/google-chrome", headless: true,
      args: ["--disable-background-networking", "--autoplay-policy=no-user-gesture-required",
        ...(process.env.CI ? ["--no-sandbox"] : [])],
    });
    const page = await browser.newPage();
    await page.setRequestInterception(true);
    page.on("request", request => new URL(request.url()).origin === origin
      ? request.continue() : request.abort());
    await page.goto(origin);
    await checkPendingMicrophone(page);
    await checkRingEndStart(page);
    console.log("Pending microphone: 27 cancellations, 2 successor races and 2 available-camera controls passed");
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
}
