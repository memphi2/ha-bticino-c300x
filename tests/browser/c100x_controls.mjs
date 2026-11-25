import assert from "node:assert/strict";
import { resolve } from "node:path";

export async function checkC100xControls(page, artifacts) {
  await page.evaluate(() => {
    lab.savedCamera = lab.hass.states[lab.camera];
    lab.savedDevice = lab.hass.devices["device-one"];
    lab.savedConfig = { ...lab.card._config };
    lab.savedCallCount = lab.calls.length;
    lab.hass.devices["device-one"] = { config_entry_id: "entry-one", model: "C100X" };
    lab.microphoneRequests = 0;
    lab.savedGetUserMedia = navigator.mediaDevices.getUserMedia;
    navigator.mediaDevices.getUserMedia = async () => {
      lab.microphoneRequests++;
      throw new Error("Unexpected microphone request while C100X media is disabled");
    };
  });
  try {
    for (const width of [320, 1024]) {
      await page.setViewport({ width, height: 800 });
      for (const state of ["missing", "unavailable", "unknown"]) {
        await page.evaluate((state) => {
          if (state === "missing") delete lab.hass.states[lab.camera];
          else lab.hass.states[lab.camera] = { state, attributes: { media_primary_action: "refresh" } };
          lab.card.setConfig({ ...lab.savedConfig, mode: "auto", show_door_unlock: false, show_stair_light: false });
          lab.card.hass = { ...lab.hass };
        }, state);
        await page.evaluate(() => new Promise(requestAnimationFrame));
        assert.deepEqual(await page.evaluate(() => [
          lab.card._actionButtonEl.disabled, lab.card._homeActionButtonEl.disabled,
        ]), [true, true], `${width}px C100X ${state} media must be inert`);
        const before = await page.evaluate(() => lab.calls.length);
        await page.evaluate(async () => {
          lab.card._actionButtonEl.click();
          lab.card._homeActionButtonEl.click();
          await lab.card._startTalkback();
        });
        assert.deepEqual(await page.evaluate(() => ({
          calls: lab.calls.length, peers: lab.peers.size, microphone: lab.microphoneRequests,
        })), { calls: before, peers: 0, microphone: 0 });
      }
      await page.screenshot({ path: resolve(artifacts, `c100x-card-disabled-${width}.png`) });
      await page.evaluate(() => {
        lab.hass.states[lab.camera] = lab.savedCamera;
        lab.card.setConfig({ ...lab.savedConfig, mode: "auto" });
        lab.card.hass = { ...lab.hass };
      });
      await page.evaluate(() => new Promise(requestAnimationFrame));
      assert.deepEqual(await page.evaluate(() => [
        lab.card._actionButtonEl.disabled, lab.card._homeActionButtonEl.disabled,
      ]), [false, false], "Supported synthetic C100X media remains reachable");
      const before = await page.evaluate(() => lab.calls.length);
      await page.evaluate(() => lab.card.shadowRoot.querySelector(".door-action").click());
      assert.deepEqual(await page.evaluate(() => lab.calls.slice(-1)), [{
        domain: "button", service: "press", data: { entity_id: "button.synthetic_door" },
      }]);
      assert.equal(await page.evaluate(() => lab.calls.length), before + 1);
      await page.evaluate(() => {
        lab.hass.entities["button.synthetic_door"].device_id = "foreign-c300x";
        lab.card.hass = { ...lab.hass };
      });
      await page.evaluate(() => new Promise(requestAnimationFrame));
      assert.equal(await page.evaluate(() => lab.card.shadowRoot.querySelector(".door-action").disabled), true);
      await page.evaluate(() => lab.card.shadowRoot.querySelector(".door-action").click());
      assert.equal(await page.evaluate(() => lab.calls.length), before + 1, "No cross-model/device door action");
      await page.evaluate(() => {
        lab.hass.entities["button.synthetic_door"].device_id = "device-one";
        lab.card.hass = { ...lab.hass };
      });
      await page.evaluate(() => new Promise(requestAnimationFrame));
      await page.screenshot({ path: resolve(artifacts, `c100x-card-supported-${width}.png`) });
    }
  } finally {
    await page.evaluate(() => {
      navigator.mediaDevices.getUserMedia = lab.savedGetUserMedia;
      lab.hass.states[lab.camera] = lab.savedCamera;
      lab.hass.devices["device-one"] = lab.savedDevice;
      lab.hass.entities["button.synthetic_door"].device_id = "device-one";
      lab.card.setConfig(lab.savedConfig);
      lab.card.hass = { ...lab.hass };
      lab.calls.length = lab.savedCallCount;
    });
  }
}
