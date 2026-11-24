"""The display pages on the Qt 5 display of firmware 3.0.x, run with the vendor's own components.

Optional and local: it needs a Qt 5.15 ``qmlscene`` and the display files of a
3.0.6 BtClass, extracted outside the repository (they are firmware files and
never belong in it). Without them the test skips.

    C300X_QT5_QMLSCENE   qmlscene, or a wrapper that also adds $EXTRA_QML to
                         the import path (offscreen platform)
    C300X_QT5_SKIN       the skins/default folder that
                         scripts/extract_btclass_resources.py BtClass OUT writes
    C300X_QT5_SHOTS      optional folder for screenshots of every step

The vendor files the Display patch changes go through the same steps as on the
device: qt5-import, core-apply, apply, then QtQuick 1.1 -> 2.7 as when packing.
The vendor's C++ objects are stand-ins (tests/qt5_runtime), and a stand-in
agent on 127.0.0.1:8090 answers with data from the integration's own builders.
A warning counts unless the unpatched vendor file gives the same one.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import zlib
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.test_qml_patch_script import _run_qml_patch

ROOT = Path(__file__).resolve().parents[1]
STUBS = Path(__file__).resolve().parent / "qt5_runtime"
VENDOR_FILES = (
    "EventManager.qml",
    "HomePage.qml",
    "MainApp.qml",
    "MemoPage.qml",
    "Settings.qml",
    "Components/Settings/GeneralsChoice.qml",
    "Components/Settings/CallBlockPopup.qml",
)
AGENT_PORT = 8090
HOME_BUTTONS = {"stock": "1", "side_by_side": "0"}
STATION_BUTTONS = ("answerButton", "intercomButton", "cameraButton", "activationsButton", "memoButton",
                   "settingsButton")
STATIONS = {
    "all-buttons": ("", ("alarmButton", "haButton", *STATION_BUTTONS)),
    "quick-actions": ('harness.find(page, "mediaModel").count = 1', ("alarmButton", "haButton", *STATION_BUTTONS)),
    "memo-settings": ("harness.emptyModels(page); intercomPageModel.count = 0; cameraPageModel.count = 0; "
                      "actuatorPageModel.count = 0; global.guiSettings.answeringMachineVisible = false",
                      ("alarmButton", "haButton", "memoButton", "settingsButton")),
}
_IGNORED = (
    "Implicitly defined onFoo properties in Connections are deprecated",
    "@@@@ don't make scan",
)
_LINE = re.compile(r":\d+(?::\d+)?:")

pytestmark = pytest.mark.skipif(
    not (os.environ.get("C300X_QT5_QMLSCENE") and os.environ.get("C300X_QT5_SKIN")),
    reason="Optional Qt 5 runtime requires C300X_QT5_QMLSCENE and C300X_QT5_SKIN",
)


def _agent_data() -> dict[str, object]:
    sys.path.insert(0, str(ROOT / "tests"))
    from test_executor import FakeEntry, FakeHass, FakeState, FakeStates, run

    from custom_components.bticino_c300x import dashboard
    from custom_components.bticino_c300x.const import (
        CONF_ALARM_ENTITY_ID,
        CONF_DASHBOARD_ENTITIES,
        CONF_DEVICE_UI_ENABLED,
        CONF_WEATHER_ENTITY_ID,
    )

    states = {
        "light.kitchen": FakeState("on", attributes={
            "friendly_name": "Küche", "brightness": 180, "supported_color_modes": ["brightness"]}),
        "switch.garden_pump": FakeState("off", attributes={"friendly_name": "Gartenpumpe"}),
        "sensor.outdoor": FakeState("12.4", attributes={
            "friendly_name": "Außen", "unit_of_measurement": "°C", "device_class": "temperature"}),
        "binary_sensor.front_door": FakeState("off", attributes={"friendly_name": "Haustür", "device_class": "door"}),
        "cover.living": FakeState("open", attributes={
            "friendly_name": "Rollladen Wohnzimmer", "current_position": 60, "supported_features": 15}),
        "climate.bath": FakeState("heat", attributes={
            "friendly_name": "Bad", "current_temperature": 21.5, "temperature": 22,
            "hvac_modes": ["off", "heat"], "min_temp": 7, "max_temp": 30}),
        "lock.garage": FakeState("locked", attributes={"friendly_name": "Garage"}),
        "alarm_control_panel.home": FakeState("disarmed", attributes={
            "friendly_name": "Alarm", "code_arm_required": False, "supported_features": 63}),
        "weather.home": FakeState("sunny", attributes={
            "friendly_name": "Wetter", "temperature": 14, "humidity": 60, "temperature_unit": "°C"}),
    }
    hass = FakeHass(states=FakeStates(states))
    entry = FakeEntry(data={CONF_DEVICE_UI_ENABLED: True}, options={
        CONF_DASHBOARD_ENTITIES: [entity for entity in states if not entity.startswith(("weather.", "alarm_"))],
        CONF_WEATHER_ENTITY_ID: "weather.home",
        CONF_ALARM_ENTITY_ID: "alarm_control_panel.home",
    })
    payload = run(dashboard.async_dashboard_payload(hass, entry))
    payload["data"]["pages"][1]["items"].append({
        "kind": "image", "source": f"http://127.0.0.1:{AGENT_PORT}/ui/test-picture.png",
        "caption": "Haustür", "width": 220, "height": 120,
    })
    return {"status": run(dashboard.async_status(hass, entry)), "dashboard": payload}


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    rows = b"".join(b"\0" + bytes((40, 120, 200)) * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


@pytest.fixture(scope="module")
def agent() -> Iterator[list[str]]:
    data = _agent_data()
    requests: list[str] = []

    class Agent(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def _reply(self, body: object, status: int = 200) -> None:
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            requests.append(self.path)
            if url.path == "/ui/test-picture.png":
                picture = _png(220, 120)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(picture)))
                self.end_headers()
                self.wfile.write(picture)
            elif url.path == "/homeassistant":
                self._reply(data["dashboard"] if not url.query else {"ok": True})
            elif url.path in ("/ui/state", "/ui/alarm/status"):
                self._reply(data["status"])
            elif url.path == "/ui/alarm/command":
                self._reply({"ok": True})
            elif url.path == "/ui/memos":
                self._reply({"memos": [], "unread": 2})
            elif url.path == "/ui/answering-machine/messages":
                self._reply({"messages": [], "unread": 1})
            elif url.path in ("/ui/events/next", "/ui/alerts/next", "/ui/ringer/next"):
                time.sleep(5)
                self._reply({"ok": True, "revision": 1, "events": []})
            else:
                self._reply({"ok": False, "error": "not_found"}, 404)

        do_POST = do_GET

    try:
        server = ThreadingHTTPServer(("127.0.0.1", AGENT_PORT), Agent)
    except OSError:
        pytest.skip(f"127.0.0.1:{AGENT_PORT}, where the display pages reach the agent, is in use")
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _patched_skin(root: Path, home_buttons: str) -> Path:
    vendor = Path(os.environ["C300X_QT5_SKIN"])
    gui, backup, import_dir = root / "gui", root / "backup", root / "import"
    shutil.copytree(vendor, gui)
    for rel in VENDOR_FILES:
        (import_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(vendor / rel, import_dir / rel)
        (gui / rel).unlink()
    assert _run_qml_patch(root, gui, backup, "qt5-import", extra_args=[str(import_dir)])["ok"] is True
    _run_qml_patch(root, gui, backup, "core-apply")
    layout = {"C300X_QML_DYNAMIC_HOME_PAGE": HOME_BUTTONS[home_buttons]}
    applied = _run_qml_patch(root, gui, backup, "apply", env_overrides=layout)
    status = _run_qml_patch(root, gui, backup, "status")
    assert (applied["patched"], applied["home_buttons"]) == (True, home_buttons)
    assert (status["state"], status["patched"], status["home_buttons"]) == ("patched", True, home_buttons)
    for path in gui.rglob("*.qml"):
        text = path.read_text()
        if text.startswith("import QtQuick 1.1\n"):
            path.write_text("import QtQuick 2.7\n" + text[len("import QtQuick 1.1\n"):])
    shutil.copyfile(vendor / "HomePage.qml", gui / "HomePageVendor.qml")
    shutil.copyfile(vendor / "Components/Settings/GeneralsChoice.qml",
                    gui / "Components/Settings/GeneralsChoiceVendor.qml")
    return gui


@pytest.fixture(scope="module")
def skin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _patched_skin(tmp_path_factory.mktemp("qt5-runtime"), "stock")


@pytest.fixture(scope="module")
def side_by_side_skin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _patched_skin(tmp_path_factory.mktemp("qt5-runtime-side-by-side"), "side_by_side")


def _run(skin: Path, qml: str, name: str) -> list[str]:
    path = skin / f"{name}.qml"
    path.write_text(qml)
    env = {
        **os.environ,
        "EXTRA_QML": f"{STUBS}:{skin}",
        "QML2_IMPORT_PATH": f"{STUBS}:{skin}",
        "QT_QPA_PLATFORM": "offscreen",
        "QML_DISABLE_DISK_CACHE": "1",
    }
    log = skin / f"{name}.log"
    with log.open("w") as output:
        result = subprocess.run([os.environ["C300X_QT5_QMLSCENE"], str(path)], env=env, stdout=output,
                                stderr=subprocess.STDOUT, timeout=120, check=False)
    lines = [line.replace(f"file://{skin}/", "") for line in log.read_text().splitlines() if line.strip()]
    assert result.returncode == 0, "\n".join(lines)
    return [line for line in lines if not any(text in line for text in _IGNORED)]


def _page(skin: Path, page: str, name: str, steps: str = "") -> list[str]:
    template = (STUBS / "Harness.qml.in").read_text()
    return _run(skin, template.replace("@PAGE@", page).replace("@STEPS@", steps)
                .replace("@SHOTS@", os.environ.get("C300X_QT5_SHOTS", "")), name)


def _split(lines: list[str]) -> tuple[list[str], list[str]]:
    checks = [line.split("qml: CHECK ", 1)[1] for line in lines if "qml: CHECK " in line]
    return checks, [line for line in lines if "qml: CHECK " not in line]


def _new_warnings(patched: list[str], vendor: list[str], vendor_name: str, name: str) -> list[str]:
    known = {_LINE.sub(":", line.replace(vendor_name, name)) for line in vendor}
    return [line for line in patched if _LINE.sub(":", line) not in known]


@pytest.mark.parametrize("page", ["Alarm", "HomeAssistant", "C300XEnergy", "C300XRingerControl", "C300XAlerts"])
def test_a_display_page_loads_without_warnings(skin: Path, agent: list[str], page: str) -> None:
    checks, warnings = _split(_page(skin, f"{page}.qml", f"run-{page}", '        if (n === 2) { shot("' + page + '") }\n        return n < 3'))
    assert checks == ["loaded true"]
    assert warnings == []


def test_the_dashboard_shows_its_tiles_and_a_detail(skin: Path, agent: list[str]) -> None:
    steps = """
        if (n === 1) { console.log("CHECK pages " + page.pageCount); shot("ha-start") }
        if (n === 2) { harness.navigation(page).selected(1) }
        if (n === 3) { console.log("CHECK page " + page.currentPageIndex + " picture " + harness.pictureReady(page, "test-picture")); shot("ha-tiles") }
        if (n === 4) { page.openDetails(page.dashboardPages[1].items[0]) }
        if (n === 5) { shot("ha-detail") }
        return n < 6
"""
    checks, warnings = _split(_page(skin, "HomeAssistant.qml", "run-ha-steps", steps))
    assert checks == ["loaded true", "pages 2", "page 1 picture true"]
    assert warnings == []
    assert "/homeassistant" in agent
    assert "/ui/test-picture.png" in agent


def test_the_alarm_page_reads_the_state_and_offers_the_modes(skin: Path, agent: list[str]) -> None:
    steps = """
        if (n === 2) { console.log("CHECK commands " + page.alarmCommands.length); shot("alarm") }
        return n < 3
"""
    checks, warnings = _split(_page(skin, "Alarm.qml", "run-alarm-steps", steps))
    assert checks == ["loaded true", "commands 5"]
    assert warnings == []
    assert "/ui/state" in agent


@pytest.mark.parametrize("station", sorted(STATIONS))
@pytest.mark.parametrize("home_buttons", sorted(HOME_BUTTONS))
def test_the_home_page_adds_both_buttons_and_the_agents_message_counts(
    request: pytest.FixtureRequest, agent: list[str], home_buttons: str, station: str,
) -> None:
    skin = request.getfixturevalue("skin" if home_buttons == "stock" else "side_by_side_skin")
    names = json.dumps(["alarmButton", "haButton", *STATION_BUTTONS])
    setup, expected = STATIONS[station]
    quick = f"        if (n === 0) {{ {setup} }}\n" if setup else ""
    name = f"home-{home_buttons}-{station}"
    steps = quick + f"""
        if (n === 2) {{
            console.log("CHECK buttons " + harness.onScreen(harness.find(page, "alarmButton")) + " " + harness.onScreen(harness.find(page, "haButton")))
            console.log("CHECK unread " + page.unreadMessagesCount() + " " + page.unreadMemosCount())
            var shown = [], off = [], overlaps = [], names = {names};
            names.forEach(function(name) {{
                var item = harness.find(page, name)
                if (!item || !item.visible) return
                if (!harness.onScreen(item)) off.push(name)
                var p = item.mapToItem(harness, 0, 0)
                shown.forEach(function(other) {{
                    if (p.x < other.x + other.w && other.x < p.x + item.width && p.y < other.y + other.h && other.y < p.y + item.height)
                        overlaps.push(other.name + "/" + name)
                }})
                shown.push({{name: name, x: p.x, y: p.y, w: item.width, h: item.height}})
            }})
            console.log("CHECK layout shown " + shown.map(function(b) {{ return b.name }}).join(",") + " off [" + off.join(",") + "] overlaps [" + overlaps.join(",") + "]")
            shot("{name}")
        }}
        if (n === 3) {{
            harness.find(page, "alarmButton").touched()
            harness.find(page, "haButton").touched()
        }}
        return n < 4
"""
    checks, patched = _split(_page(skin, "HomePage.qml", f"run-{name}", steps))
    assert checks[:3] == ["loaded true", "buttons true true", "unread 1 2"]
    assert checks[3] == f"layout shown {','.join(expected)} off [] overlaps []"
    assert checks[4:] == ["activated alarmPage", "activated haPage"]
    _, vendor = _split(_page(skin, "HomePageVendor.qml", f"run-{name}-vendor", quick + "        return n < 4"))
    assert _new_warnings(patched, vendor, "HomePageVendor.qml", "HomePage.qml") == []


def test_the_general_settings_keep_the_touch_tone_and_add_the_feedback_switch(skin: Path, agent: list[str]) -> None:
    steps = '        if (n === 1) { shot("generals") }\n        return n < 2'
    checks, patched = _split(_page(skin, "Components/Settings/GeneralsChoice.qml", "run-generals", steps))
    assert checks == ["loaded true"]
    _, vendor = _split(_page(skin, "Components/Settings/GeneralsChoiceVendor.qml", "run-generals-vendor",
                             "        return n < 2"))
    assert _new_warnings(patched, vendor, "GeneralsChoiceVendor.qml", "GeneralsChoice.qml") == []


def test_every_layout_case_runs_without_warnings(skin: Path, agent: list[str]) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import check_display_layout as layout

    shots = os.environ.get("C300X_QT5_SHOTS", "")
    failures = {}
    for index, fixture in enumerate(layout.fixtures()):
        name = f'{fixture["component"]}-{fixture["name"]}'
        qml = layout.frame_qml(fixture, layout.VIEWPORTS["native"]).replace("import QtQuick 2.15", "import QtQuick 2.7", 1)
        save = f'r.saveToFile("{shots}/{name}.png"); ' if shots else ""
        qml = qml.rstrip()[:-1] + (
            "    Timer { interval: 800; running: true; onTriggered: frame.grabToImage(function(r) { "
            f"{save}Qt.quit() }}) }}\n}}\n"
        )
        warnings = _run(skin, qml, f"frame-{index}")
        if warnings:
            failures[name] = warnings
    assert failures == {}
