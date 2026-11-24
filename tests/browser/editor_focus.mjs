import assert from "node:assert/strict";

// The real editor in a stand-in for HA's dialog: every config-changed goes
// back into setConfig, and the stand-in ha-form keeps its inputs like Lit does.
export async function checkEditorFocus(page) {
  await page.evaluate(() => {
    if (!customElements.get("ha-form")) {
      customElements.define("ha-form", class extends HTMLElement {
        set data(data) {
          this._data = data;
          this.render();
        }
        get data() { return this._data; }
        connectedCallback() { this.render(); }
        render() {
          if (!this.isConnected || !this._data) return;
          if (!this.nameInput) {
            this.nameInput = Object.assign(document.createElement("input"), { className: "name" });
            this.doorToggle = Object.assign(document.createElement("input"), { type: "checkbox", className: "door" });
            const send = (patch) => this.dispatchEvent(new CustomEvent("value-changed",
              { detail: { value: { ...this._data, ...patch } } }));
            this.nameInput.addEventListener("input", () => send({ name: this.nameInput.value }));
            this.doorToggle.addEventListener("change", () => send({ show_door_unlock: this.doorToggle.checked }));
            this.append(this.nameInput, this.doorToggle);
          }
          if (this.nameInput.value !== (this._data.name || "")) this.nameInput.value = this._data.name || "";
          this.doorToggle.checked = this._data.show_door_unlock !== false;
        }
      });
    }
    const editor = document.createElement("c300x-doorbell-call-card-editor");
    editor.hass = { ...lab.hass };
    editor.setConfig({ type: "custom:c300x-doorbell-call-card", entity: lab.camera });
    lab.editorConfigs = [];
    editor.addEventListener("config-changed", (event) => {
      lab.editorConfigs.push(event.detail.config);
      editor.setConfig(event.detail.config);
    });
    document.body.append(editor);
    lab.editor = editor;
  });
  const focused = () => page.evaluate(() => {
    const form = lab.editor.shadowRoot.querySelector("ha-form");
    return document.activeElement === lab.editor && form.contains(lab.editor.shadowRoot.activeElement)
      ? lab.editor.shadowRoot.activeElement.className : document.activeElement?.tagName;
  });
  await page.evaluate(() => lab.editor.shadowRoot.querySelector("ha-form").nameInput.focus());
  await page.keyboard.type("Front");
  assert.equal(await focused(), "name", "typing lost the focus");
  assert.equal(await page.evaluate(() => lab.editorConfigs.at(-1).name), "Front");
  await page.keyboard.press("Tab");
  assert.equal(await focused(), "door");
  await page.keyboard.press("Space");
  assert.equal(await focused(), "door", "the keyboard toggle lost the focus");
  assert.equal(await page.evaluate(() => lab.editorConfigs.at(-1).show_door_unlock), false);
  await page.keyboard.press("Space");
  assert.equal(await page.evaluate(() => lab.editorConfigs.at(-1).show_door_unlock), undefined);
  await page.evaluate(() => { lab.editor.remove(); delete lab.editor; });
}
