import assert from "node:assert/strict";

export async function checkPictureControls(page) {
  await page.reload();
  await page.waitForFunction(() => window.lab?.listeners.size);
  await page.evaluate(() => {
    const values = { brightness: 50, contrast: 50, saturation: 50 };
    const original = lab.hass.callWS;
    lab.pictureWrites = [];
    lab.hass.callWS = async message => {
      if (message.service !== "camera_picture") return original(message);
      const { control, value } = message.service_data;
      if (control) {
        lab.pictureWrites.push([control, value]);
        values[control] = value;
      }
      return { response: { ...values } };
    };
    lab.picture = lab.card.shadowRoot.querySelector("c300x-picture-controls");
    lab.deliverPicture = (state, supported, scope) => {
      const entity = { state: "streaming", attributes: { media_state: state,
        picture_controls_supported: supported, picture_controls_scope: scope } };
      for (const notify of lab.listeners) notify({data: {entity_id: lab.camera, new_state: entity}});
    };
    lab.deliverPicture("ring_answering", true);
  });
  await page.waitForFunction(() => !lab.picture.hidden);
  await (await page.evaluateHandle(() => lab.picture.button)).click();
  await page.waitForFunction(() => !lab.picture.inputs[0].disabled);
  // No picture plays: the panel must hide the empty text and toolbar under it.
  assert.deepEqual(await page.evaluate(() => [lab.picture.hasAttribute("live"),
    getComputedStyle(lab.picture.panel).backgroundColor]), [false, "rgb(32, 33, 36)"]);
  for (const [width, fraction] of [[180, 0.8], [200, 0.2], [640, 0.7]]) {
    await page.evaluate(w => { document.querySelector("#mount").style.width = w + "px"; }, width);
    for (const key of ["brightness", "contrast", "saturation"]) {
      const point = await page.evaluate(({ key, fraction }) => {
        const input = lab.picture.inputs.find(node => node.dataset.key === key);
        const media = lab.card._mediaEl.getBoundingClientRect();
        const panel = lab.picture.panel.getBoundingClientRect();
        if (panel.left < media.left || panel.right > media.right || panel.top < media.top || panel.bottom > media.bottom) {
          throw Error("Picture panel clipped by media");
        }
        input.scrollIntoView({ block: "nearest" });
        const r = input.getBoundingClientRect(), x = r.left + fraction * r.width, y = r.top + r.height / 2;
        if (lab.picture.shadowRoot.elementFromPoint(x, y) !== input) throw Error("Slider not reachable: " + key);
        return { x, y, count: lab.pictureWrites.length };
      }, { key, fraction });
      await page.mouse.click(point.x, point.y);
      await page.waitForFunction(n => lab.pictureWrites.length === n + 1, {}, point.count);
      assert.equal(await page.evaluate(() => lab.pictureWrites.at(-1)[0]), key);
    }
  }
  // Only capability/scope changes; there is no hass setter call or media-state transition to force a render.
  await page.evaluate(() => lab.deliverPicture("ring_answering", false));
  await page.waitForFunction(() => lab.picture.hidden && lab.picture.panel.hidden);
  await page.evaluate(() => {
    lab.card._webrtc._remoteStream = lab.source.captureStream();
    lab.deliverPicture("on_demand_active", true, "ring");
  });
  assert.ok(await page.evaluate(() => lab.picture.hidden));
  await page.evaluate(() => lab.deliverPicture("on_demand_active", true, "ring_and_on_demand"));
  await page.waitForFunction(() => !lab.picture.hidden);
  await (await page.evaluateHandle(() => lab.picture.button)).click();
  await page.waitForFunction(() => !lab.picture.panel.hidden);
  await page.waitForFunction(() => lab.picture.hasAttribute("live")
    && getComputedStyle(lab.picture.panel).backgroundColor === "rgba(32, 33, 36, 0.5)");
  await page.evaluate(() => {
    lab.deliverPicture("on_demand_active", true, "ring");
    lab.deliverPicture("on_demand_active", true, "ring_and_on_demand");
  });
  await page.waitForFunction(() => !lab.picture.hidden && lab.picture.panel.hidden);
  await page.reload();
  await page.waitForFunction(() => !!window.lab);
  console.log("Picture controls: all sliders reachable at 180/200/640px; subscription revocation passed");
}
