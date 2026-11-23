"""Exercise the card's real custom element and range inputs in a browser."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_picture_sliders_submit_on_release_and_ignore_late_response(tmp_path: Path):
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        pytest.skip("Chrome or Chromium unavailable")
    frontend = ROOT / "custom_components/bticino_c300x/frontend"
    for name in ("c300x-picture-controls.js", "c300x-media-translations.js"):
        shutil.copy(frontend / name, tmp_path)
    page = tmp_path / "test.html"
    page.write_text("""<!doctype html><c300x-picture-controls></c300x-picture-controls>
<script type="module">
import "./c300x-picture-controls.js";
const el = document.querySelector("c300x-picture-controls");
const sent = [];
let reply;
const hass = {language:"de", callWS(msg) { sent.push(msg); return new Promise(r => {reply=r}); }};
const check = test => { if (!test) throw Error("picture control check failed"); };
el.configure(hass,"entry","ring");
check(!sent.length);
el.button.click();
check(sent.length === 1 && sent[0].service === "camera_picture" && sent[0].service_data.entry_id === "entry");
reply({response:{brightness:30,contrast:40,saturation:50}});
await Promise.resolve();
const range = el.shadowRoot.querySelector("[data-key=contrast]");
check(!range.disabled && range.value === "40");
range.value="20"; range.dispatchEvent(new Event("input"));
check(sent.length === 1);
range.dispatchEvent(new Event("change"));
check(sent[1].service_data.control === "contrast" && sent[1].service_data.value === 20 && range.disabled);
el.configure(hass,"entry","on_demand");
reply({response:{brightness:50,contrast:20,saturation:10}});
await Promise.resolve();
check(!el.hidden && el.panel.hidden && sent.length === 2);
el.button.click();
check(sent.length === 3 && sent[2].service === "camera_picture");
el.configure(hass,"entry",null);
reply({response:{brightness:50,contrast:20,saturation:10}});
await Promise.resolve();
check(el.hidden && el.panel.hidden);
document.documentElement.dataset.testResult="passed";
</script>""", encoding="utf-8")
    run = subprocess.run([chrome, "--headless", "--disable-gpu", "--disable-dev-shm-usage",
                          "--allow-file-access-from-files", f"--user-data-dir={tmp_path / 'profile'}",
                          "--virtual-time-budget=1500", "--dump-dom", page.as_uri()],
                         capture_output=True, text=True, timeout=30, check=True)
    assert 'data-test-result="passed"' in run.stdout
