"""Exercise the card's real custom element and range inputs in a browser."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run_page(tmp_path: Path, script: str) -> None:
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        pytest.skip("Chrome or Chromium unavailable")
    frontend = ROOT / "custom_components/bticino_c300x/frontend"
    for name in ("c300x-picture-controls.js", "c300x-media-translations.js"):
        shutil.copy(frontend / name, tmp_path)
    page = tmp_path / "test.html"
    page.write_text(script, encoding="utf-8")
    run = subprocess.run([chrome, "--headless", "--disable-gpu", "--disable-dev-shm-usage",
                          "--allow-file-access-from-files", f"--user-data-dir={tmp_path / 'profile'}",
                          "--virtual-time-budget=1500", "--dump-dom", page.as_uri()],
                         capture_output=True, text=True, timeout=30, check=True)
    assert 'data-test-result="passed"' in run.stdout


def test_picture_errors_are_told_apart(tmp_path: Path):
    _run_page(tmp_path, """<!doctype html><c300x-picture-controls></c300x-picture-controls>
<script type="module">
import "./c300x-picture-controls.js";
import { C300X_MEDIA_TRANSLATIONS as T } from "./c300x-media-translations.js";
const el = document.querySelector("c300x-picture-controls");
const replies = [];
const hass = {language:"de", callWS() { return new Promise((ok, fail) => replies.push({ok, fail})); }};
const check = (test, name) => { if (!test) throw Error("picture error check failed: " + name); };
const settle = () => new Promise(r => setTimeout(r));
const agent = code => ({code:"home_assistant_error",
  message:"C300X picture controls: device agent returned HTTP 409: " + code});
const status = () => el.shadowRoot.querySelector("p").textContent;
const ranges = () => [...el.shadowRoot.querySelectorAll("input")];
const shown = () => ranges().every(r => !r.parentElement.hidden && !r.disabled);
for (const lang of Object.keys(T))
  for (const key of ["picture_not_applied", "picture_busy", "picture_unavailable"]) check(T[lang][key], lang + key);
el.configure(hass,"entry","on_demand");
el.button.click();
replies.shift().ok({response:{brightness:40,contrast:50,saturation:60}});
await settle();
const brightness = el.shadowRoot.querySelector("[data-key=brightness]");
brightness.value = "90"; brightness.dispatchEvent(new Event("change"));
replies.shift().fail(agent("picture_not_applied"));
await settle();
check(status() === T.de.picture_not_applied && shown() && brightness.value === "40", "not applied");
brightness.value = "70"; brightness.dispatchEvent(new Event("change"));
replies.shift().fail(agent("media_busy"));
await settle();
check(status() === T.de.picture_busy && shown() && brightness.value === "40", "busy");
brightness.value = "70"; brightness.dispatchEvent(new Event("change"));
replies.shift().fail(agent("picture_controls_unavailable"));
await settle();
check(status() === T.de.picture_unavailable && ranges().every(r => r.parentElement.hidden), "unavailable");
el.button.click(); el.button.click();
replies.shift().fail(agent("media_busy"));
await settle();
check(status() === T.de.picture_busy && ranges().every(r => r.parentElement.hidden), "busy without values");
el.button.click(); el.button.click();
replies.shift().fail(new Error("socket closed"));
await settle();
check(status() === T.de.picture_unavailable && ranges().every(r => r.parentElement.hidden), "other error");
document.documentElement.dataset.testResult="passed";
</script>""")


def test_picture_sliders_submit_on_release_and_ignore_late_response(tmp_path: Path):
    _run_page(tmp_path, """<!doctype html><c300x-picture-controls></c300x-picture-controls>
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
</script>""")


def _check_panel_surface(tmp_path: Path, live: bool) -> None:
    attribute = " live" if live else ""
    expected = ("Number(alpha) > 0 && Number(alpha) <= 0.6 && style.textShadow !== 'none'" if live
                else "alpha === '1' && style.backgroundColor === 'rgb(32, 33, 36)' && style.textShadow === 'none'")
    _run_page(tmp_path, f"""<!doctype html><c300x-picture-controls{attribute}></c300x-picture-controls>
<script type="module">
import "./c300x-picture-controls.js";
const el = document.querySelector("c300x-picture-controls");
el.configure({{language:"en", callWS: async () => ({{response:{{brightness:50,contrast:50,saturation:50}}}})}},"entry","ring");
el.button.click();
await new Promise(r => setTimeout(r));
const style = getComputedStyle(el.panel);
const alpha = (/rgba?\\(([^)]*)\\)/.exec(style.backgroundColor)?.[1].split(/[\\s,/]+/).filter(Boolean)[3]) ?? "1";
const check = (test, name) => {{ if (!test) throw Error("picture panel check failed: " + name + " " + style.backgroundColor); }};
check(!el.panel.hidden, "open");
check({expected}, "surface");
document.documentElement.dataset.testResult="passed";
</script>""")


def test_picture_panel_stays_opaque_without_a_live_picture(tmp_path: Path):
    # A ring session can show the panel over the empty text or the media toolbar.
    _check_panel_surface(tmp_path, live=False)


def test_picture_panel_lets_the_live_picture_show_through(tmp_path: Path):
    _check_panel_surface(tmp_path, live=True)
