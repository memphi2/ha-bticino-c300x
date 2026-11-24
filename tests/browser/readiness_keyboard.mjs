import assert from "node:assert/strict";

// A blocked readiness opens Repairs from the keyboard like a button.
export async function checkReadinessKeyboard(page) {
  const prepare = (state) => page.evaluate(async (state) => {
    const id = "sensor.synthetic_media_readiness";
    lab.hass.entities[id] = { device_id: "device-one", platform: "bticino_c300x", translation_key: "media_readiness" };
    lab.hass.states[id] = { state, attributes: { failed_checks: state === "blocked" ? ["firewall"] : [] } };
    lab.card.hass = { ...lab.hass };
    await new Promise(requestAnimationFrame);
    lab.repairs = [];
    if (!lab.onRepairs) {
      lab.onRepairs = true;
      addEventListener("location-changed", () => {
        lab.repairs.push(location.pathname);
        history.replaceState(null, "", "/");
      });
    }
    const readiness = lab.card.shadowRoot.querySelector(".readiness");
    readiness.focus();
    return lab.card.shadowRoot.activeElement === readiness;
  }, state);
  assert.equal(await prepare("warning"), false, "a warning without repair took the focus");
  assert.equal(await prepare("blocked"), true, "the Repairs control cannot take the focus");
  for (const key of ["Enter", "Space"]) {
    await page.keyboard.press(key);
  }
  assert.deepEqual(await page.evaluate(() => lab.repairs), ["/config/repairs", "/config/repairs"]);
  await page.evaluate(() => {
    delete lab.hass.entities["sensor.synthetic_media_readiness"];
    delete lab.hass.states["sensor.synthetic_media_readiness"];
    lab.card.hass = { ...lab.hass };
  });
}
