import assert from "node:assert/strict";
import puppeteer from "puppeteer-core";

// The browser's own autoplay policy, and media started from script without a
// user gesture (CDP userGesture: false), as a notification answer on iOS does.
const START = `(async (homeCall) => {
  for (let i = 0; i < 200 && !window.lab; i++) await new Promise((done) => setTimeout(done, 20));
  lab.sound = soundState;
  lab.withAudio = true;
  // The fixture's tone source would wait for a gesture too; it is not under test.
  const resume = AudioContext.prototype.resume;
  AudioContext.prototype.resume = function () { resume.call(this).catch(() => {}); return Promise.resolve(); };
  navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("Denied", "NotAllowedError"));
  const card = homeCall ? lab.mount({ mode: "home_call" }) : lab.card;
  lab.card = card;
  if (homeCall) await card._actions.startHomeCallAudio();
  else await card._startTalkback();
  // The "microphone unavailable" notice shows first for two seconds.
  for (let i = 0; i < 100 && !(lab.sound(homeCall).hint && (homeCall || !lab.sound(homeCall).paused)); i++) {
    await new Promise((done) => setTimeout(done, 50));
  }
  return JSON.stringify(lab.sound(homeCall));
})`;

function soundState(homeCall) {
  const card = lab.card;
  const element = homeCall ? card._audioEl : card._videoEl;
  const secondary = card.shadowRoot.querySelector(".secondary");
  return {
    gesture: navigator.userActivation.hasBeenActive,
    paused: element.paused,
    muted: element.muted,
    hint: secondary.textContent === card._label("tap_for_sound") && secondary.classList.contains("notice"),
  };
}

export async function checkBlockedSound(origin) {
  const browser = await puppeteer.launch({
    executablePath: process.env.CHROME_BIN || "/usr/bin/google-chrome", headless: true,
    args: ["--disable-background-networking", "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream", ...(process.env.CI ? ["--no-sandbox"] : [])],
  });
  try {
    for (const homeCall of [false, true]) {
      const page = await browser.newPage();
      await page.goto(origin);
      // page.evaluate would count as a gesture; everything before the tap goes through CDP.
      const cdp = await page.createCDPSession();
      const { result, exceptionDetails } = await cdp.send("Runtime.evaluate", {
        expression: `${soundState}; ${START}(${homeCall})`,
        awaitPromise: true, returnByValue: true, userGesture: false,
      });
      assert.equal(exceptionDetails, undefined, JSON.stringify(exceptionDetails));
      const label = homeCall ? "Home Call" : "doorstation";
      // The picture runs muted and the card asks for a tap. Chrome refuses
      // even a muted audio-only element, so Home Call waits for the tap.
      const before = JSON.parse(result.value);
      if (homeCall) delete before.paused;
      assert.deepEqual(before, { gesture: false, muted: true, hint: true, ...(homeCall ? {} : { paused: false }) },
        `${label} without a gesture`);
      const title = await page.evaluateHandle(() => lab.card.shadowRoot.querySelector(".title"));
      await title.click();
      await page.waitForFunction((homeCall) => !lab.sound(homeCall).muted, { timeout: 5000 }, homeCall)
        .catch(() => {});
      await page.evaluate(() => new Promise(requestAnimationFrame));
      assert.deepEqual(await page.evaluate((homeCall) => lab.sound(homeCall), homeCall),
        { gesture: true, paused: false, muted: false, hint: false }, `${label} after a tap`);
      await page.close();
    }
  } finally {
    await browser.close();
  }
}
