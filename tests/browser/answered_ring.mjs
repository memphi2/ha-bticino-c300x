import assert from "node:assert/strict";

// The same instant as HA writes it into state objects and into state events.
const RING = ["2026-11-24T10:00:00.123456+00:00", "2026-11-24T10:00:00.123Z"];
const NEXT_RING = "2026-11-24T10:05:00.000Z";

async function setUp(page, { reload = true } = {}) {
  if (reload) {
    await page.reload();
    await page.waitForFunction(() => !!window.lab);
  }
  await page.evaluate(() => {
    sessionStorage.clear();
    lab.card._ensureDoorbellPreview = async () => {};
    lab.offers = 0;
    const subscribe = lab.hass.connection.subscribeMessage;
    lab.hass.connection.subscribeMessage = (callback, message) => {
      lab.offers++;
      lab.provider = callback;
      return subscribe(callback, message);
    };
    lab.ring = (media_state, media_primary_action, last_changed) => {
      lab.hass.states[lab.camera] = { entity_id: lab.camera, state: "streaming", last_changed,
        attributes: { friendly_name: "Door", media_state, media_primary_action } };
      lab.card.hass = { ...lab.hass };
      return new Promise(requestAnimationFrame);
    };
    lab.button = () => {
      const button = lab.card.shadowRoot.querySelector(".row-action");
      return { label: button.getAttribute("aria-label"), disabled: button.disabled };
    };
    lab.hangUp = { label: lab.card._label("hang_up"), disabled: false };
    lab.busy = { label: lab.card._label("busy"), disabled: true };
    lab.stored = () => sessionStorage.getItem(`c300x_answered_ring:${lab.camera}`);
  });
}

async function answer(page) {
  await page.evaluate(async (ring) => {
    await lab.ring("ring_pending", "answer_ring", ring[0]);
    await lab.card._actions.handlePrimaryAction();
    await lab.ring("ring_active", "hangup", ring[1]);
  }, RING);
  await page.waitForFunction(() => lab.card._webrtc.running && lab.card._videoEl.readyState >= 2);
}

// The fixture page starts idle, which would end the ring; mount the card on
// the reloaded page with the ring state HA would have.
async function reloadDuringRing(page, lastChanged) {
  const stored = await page.evaluate(() => lab.stored());
  await page.reload();
  await page.waitForFunction(() => !!window.lab);
  await setUp(page, { reload: false });
  return page.evaluate(async ({ stored, lastChanged }) => {
    if (stored) sessionStorage.setItem(`c300x_answered_ring:${lab.camera}`, stored);
    lab.hass.states[lab.camera] = { entity_id: lab.camera, state: "streaming", last_changed: lastChanged,
      attributes: { friendly_name: "Door", media_state: "ring_active", media_primary_action: "hangup" } };
    lab.card = lab.mount();
    lab.card._ensureDoorbellPreview = async () => {};
    await new Promise(requestAnimationFrame);
    return { stored: lab.stored() === stored };
  }, { stored, lastChanged });
}

const settle = (page) => page.evaluate(() => new Promise((done) => setTimeout(done, 300)));

export async function checkAnsweredRing(page) {
  // A dropped peer keeps the hang-up and connects once more.
  await setUp(page);
  await answer(page);
  assert.deepEqual(await page.evaluate(() => lab.button()), await page.evaluate(() => lab.hangUp));
  await page.evaluate(() => lab.provider({ type: "closed", reason: "closed" }));
  await settle(page);
  assert.deepEqual(await page.evaluate(() => lab.button()), await page.evaluate(() => lab.hangUp),
    "first drop");
  await page.waitForFunction(() => lab.offers === 2 && lab.card._webrtc.running
    && lab.card._lifecycle.doorbellAnswered);
  assert.ok(await page.evaluate(() => !!lab.stored()), "answered ring was not remembered");
  await page.evaluate(() => lab.provider({ type: "closed", reason: "closed" }));
  await settle(page);
  const afterSecondDrop = await page.evaluate(() => ({ offers: lab.offers, running: lab.card._webrtc.running,
    button: lab.button() }));
  assert.deepEqual(afterSecondDrop, { offers: 2, running: false,
    button: await page.evaluate(() => lab.hangUp) }, "second drop");
  await page.evaluate(() => { lab.calls.length = 0; lab.card.shadowRoot.querySelector(".row-action").click(); });
  await page.waitForFunction(() => lab.calls.some((call) => call.service === "hangup_doorbell_call"));

  // A reload within the same ring finds the answered call again.
  await setUp(page);
  await answer(page);
  const reloaded = await reloadDuringRing(page, RING[1]);
  assert.equal(reloaded.stored, true, "answered ring not kept over the reload");
  await page.waitForFunction(() => lab.offers === 1 && lab.card._webrtc.running);
  assert.deepEqual(await page.evaluate(() => lab.button()), await page.evaluate(() => lab.hangUp));

  // The stored answer is for that ring only: the next ring answered elsewhere is busy here.
  await reloadDuringRing(page, NEXT_RING);
  await settle(page);
  assert.deepEqual(await page.evaluate(() => ({ offers: lab.offers, button: lab.button() })),
    { offers: 0, button: await page.evaluate(() => lab.busy) }, "next ring");

  // The ring end forgets the answer.
  assert.equal(await page.evaluate(() => {
    lab.hass.states[lab.camera] = { entity_id: lab.camera, state: "idle",
      attributes: { friendly_name: "Door", media_state: "idle", media_primary_action: "start_stream" } };
    lab.card.hass = { ...lab.hass };
    return sessionStorage.getItem(`c300x_answered_ring:${lab.camera}`);
  }), null);

  // A ring another client answered stays busy and cannot be hung up here.
  await setUp(page);
  const elsewhere = await page.evaluate(async (ring) => {
    await lab.ring("ring_pending", "answer_ring", ring[0]);
    await lab.ring("ring_active", "hangup", ring[1]);
    lab.calls.length = 0;
    await lab.card._actions.handlePrimaryAction();
    return { button: lab.button(), calls: lab.calls.length, stored: lab.stored() };
  }, RING);
  assert.deepEqual(elsewhere, { button: await page.evaluate(() => lab.busy), calls: 0, stored: null });
  await page.evaluate(() => sessionStorage.clear());
  await page.reload();
  await page.waitForFunction(() => !!window.lab);
}
