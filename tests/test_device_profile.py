"""The station's profile on the Home Assistant side."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x import device_profile
from custom_components.bticino_c300x.device_profile import (
    DeviceProfile,
    entry_profile,
    setup_profile,
    station_profile,
)
from custom_components.bticino_c300x.display_activation import (
    display_is_qt5,
    gui_reload_kwargs,
)
from custom_components.bticino_c300x.display_support import (
    entry_is_c100x,
    setup_is_c100x,
)

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "bticino_c300x"

C300X_QT4 = DeviceProfile("C300X", "qt4_ondisk", "high_res")
C300X_QT5 = DeviceProfile("C300X", "qt5_rcc", "fixed")
C100X = DeviceProfile("C100X", "qt5_ondisk", "fixed")


def _entry(info, status=None):
    return SimpleNamespace(runtime_data=SimpleNamespace(agent_info=info, qml_patch_status=status))


@pytest.mark.parametrize(("device", "profile"), [
    ({"model": "C300X", "display_kind": "qt4_ondisk", "camera": "high_res"}, C300X_QT4),
    ({"model": "C300X", "display_kind": "qt5_rcc", "camera": "fixed"}, C300X_QT5),
    ({"model": "C100X", "display_kind": "qt5_ondisk", "camera": "fixed"}, C100X),
    # Either fact names the C100X.
    ({"model": "C100X"}, C100X),
    ({"model": "C300X", "display_kind": "qt5_ondisk"}, C100X),
    # Without a camera answer the camera follows the display.
    ({"model": "C300X", "display_kind": "qt5_rcc"}, C300X_QT5),
    ({"model": "C300X", "display_kind": "qt4_ondisk", "camera": "?"}, C300X_QT4),
])
def test_the_profile_is_read_from_the_agents_answer(device, profile):
    assert setup_profile(device) == profile
    assert entry_profile(_entry(device)) == profile
    assert setup_is_c100x(device) is entry_is_c100x(_entry(device)) is profile.is_c100x
    assert profile.has_display_patch is (profile.display != "qt5_ondisk")
    assert profile.camera_fixed is (profile.display != "qt4_ondisk")


@pytest.mark.parametrize("info", [None, {}, {"model": None, "display_kind": None}, {"model": "C300X"}])
def test_an_agent_without_a_display_answer_is_judged_by_the_display_status(info):
    # As in 2.10.0: only the Qt 5 display of firmware 3.0.x reports its overlay.
    assert entry_profile(_entry(info)) == C300X_QT4
    assert entry_profile(_entry(info, {"qt5_overlay": None, "patched": True})) == C300X_QT4
    for overlay in ("active", "off", "failed"):
        entry = _entry(info, {"qt5_overlay": overlay})
        assert entry_profile(entry) == C300X_QT5
        assert display_is_qt5(entry) and gui_reload_kwargs(entry) == {"display_restart": True}
    assert gui_reload_kwargs(_entry(info)) == {}
    assert entry_profile(SimpleNamespace()) == C300X_QT4


def test_a_mismatch_the_agent_reports_is_kept():
    # The agent answers with what its display program says and reports the disagreement.
    mismatch = setup_profile({"model": "C300X", "display_kind": "qt4_ondisk", "model_check": "mismatch"})
    assert mismatch == DeviceProfile("C300X", "qt4_ondisk", "high_res", False)
    assert not mismatch.has_display_patch
    mismatch = setup_profile({"model": "C100X", "display_kind": "qt5_ondisk", "model_check": "mismatch"})
    assert mismatch == DeviceProfile("C100X", "qt5_ondisk", "fixed", False)
    assert not mismatch.has_display_patch and C300X_QT4.has_display_patch
    for check in ("ok", "unread", None):
        assert setup_profile({"model": "C300X", "display_kind": "qt4_ondisk", "model_check": check}) == C300X_QT4


def test_the_agents_answer_decides_before_the_display_status():
    c100x = _entry({"model": "C100X", "display_kind": "qt5_ondisk"}, {"qt5_overlay": "active"})
    assert entry_profile(c100x) == C100X and not display_is_qt5(c100x)
    qt4 = _entry({"model": "C300X", "display_kind": "qt4_ondisk"}, {"qt5_overlay": "active"})
    assert not display_is_qt5(qt4)
    qt5 = _entry({"model": "C300X", "display_kind": "qt5_rcc"})
    assert display_is_qt5(qt5) and gui_reload_kwargs(qt5) == {"display_restart": True}


@pytest.mark.parametrize(("answer", "profile"), [
    ("qt4\nc300x\nnamed-C300X\n", C300X_QT4),
    ("qt5\nc300x\nnamed-C300X\n", C300X_QT5),
    ("qt5\nc100x\nnamed-C100X\n", C100X),
    # The station names no model: its display program decides.
    ("qt4\nc300x\n", C300X_QT4),
    ("qt5\nc300x\n", C300X_QT5),
    ("qt5\nc100x\n", C100X),
    ("qt4\nc100x\n", C100X),
    ("", C300X_QT4),
    # They disagree: the display program decides, unconfirmed, and no Display patch.
    ("qt5\nc100x\nnamed-C300X\n", DeviceProfile("C100X", "qt5_ondisk", "fixed", False)),
    ("qt4\nc300x\nnamed-C100X\n", DeviceProfile("C300X", "qt4_ondisk", "high_res", False)),
    ("qt5\nc300x\nnamed-C100X\n", DeviceProfile("C300X", "qt5_rcc", "fixed", False)),
])
def test_the_installer_probe_reads_the_same_profile_on_the_station(answer, profile):
    commands = []

    def run(command):
        commands.append(command)
        return answer

    assert station_profile(run, lambda text: f"'{text}'") == profile
    assert not profile.has_display_patch or profile in (C300X_QT4, C300X_QT5)
    assert len(commands) == 1
    for path in ("/usr/lib/libQt5Core.so.5", "/home/bticino/bin/gui/BtClass100", "/home/bticino/sp/dbfiles_ws.xml"):
        assert f"'{path}'" in commands[0]


def test_the_installer_probe_command_reads_the_firmware_files(tmp_path):
    """The probe's own shell command, run against the model files of the firmwares."""

    work = Path(os.environ.get("C300X_FIRMWARE_WORK", ROOT.parent / "c300x-fwpatch/work"))
    for firmware, profile in (("1.7.19", C300X_QT4), ("2.0.2", C300X_QT4), ("3.0.6", C300X_QT5),
                              ("c100x-1.5.8", C100X)):
        root = work / f"rootfs-{firmware}"
        if not root.is_dir():
            pytest.skip("Private firmware files unavailable")

        def run(command, root=root):
            for path in ("/usr/lib/libQt5Core.so.5", "/home/bticino/bin/gui/BtClass100",
                         "/home/bticino/sp/dbfiles_ws.xml"):
                command = command.replace(f"'{path}'", shlex.quote(str(root) + path))
            return subprocess.run(["sh", "-c", command], capture_output=True, text=True, check=True).stdout

        assert station_profile(run, lambda text: f"'{text}'") == profile, firmware


def test_the_profile_names_match_the_agent():
    detect = (ROOT / "native_agent/src/device_detect.c").read_text(encoding="utf-8")
    capabilities = (ROOT / "native_agent/src/capabilities.c").read_text(encoding="utf-8")
    for name in (device_profile.QT4_ONDISK, device_profile.QT5_RCC, device_profile.QT5_ONDISK,
                 device_profile.C300X, device_profile.C100X):
        assert f'"{name}"' in detect
    assert '"fixed" : "high_res"' in capabilities
    for marker in (device_profile._QT5_DISPLAY_MARKER, device_profile._C100X_DISPLAY_MARKER,
                   device_profile._MODEL_FILE):
        assert f'"{marker}"' in detect


def test_only_the_profile_tells_the_stations_apart():
    """No other module tests the markers, the model name or the overlay status for that."""

    # Places that name a model without asking what the station is: texts and
    # login names chosen from a model string, discovery types, the profile itself.
    naming = {"device_profile.py", "model_names.py", "factory_login.py", "discovery.py"}
    pattern = re.compile(
        r"""libQt5Core|BtClass100|==\s*["']C100X["']|!=\s*["']C100X["']"""
        r"""|["']display_kind["']\)\s*[!=]=|qt5_overlay["']\)\s+is\s+not\s+None"""
    )
    found = sorted(
        f"{path.relative_to(COMPONENT)}:{number}"
        for path in COMPONENT.rglob("*.py") if path.name not in naming
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        # The switch only passes the status field on as an attribute.
        if pattern.search(line) and '**({"qt5_overlay": status["qt5_overlay"]}' not in line
    )
    assert found == []


def _stored(model, info=None, *, runtime=True):
    entry = SimpleNamespace(data={device_profile.STATION_MODEL: model} if model else {})
    if runtime:
        entry.runtime_data = SimpleNamespace(agent_info=info, qml_patch_status=None)
    return entry


OFFLINE = {"model": None, "display_kind": None, "capabilities": {}, "offline_error": "down"}


@pytest.mark.parametrize("runtime", [True, False])
def test_an_entry_whose_agent_did_not_answer_stays_the_station_it_named(runtime):
    # An offline start, and an entry without runtime data after a failed setup.
    assert entry_profile(_stored("C100X", OFFLINE, runtime=runtime)) == C100X
    assert entry_is_c100x(_stored("C100X", OFFLINE, runtime=runtime))
    # Reauth, options and reconfigure name the model and offer its fields by it.
    from custom_components.bticino_c300x.model_names import entry_model

    assert entry_model(_stored("C100X", OFFLINE, runtime=runtime)) == "C100X"
    assert entry_profile(_stored("C300X", OFFLINE, runtime=runtime)) == C300X_QT4
    # Without a kept model the entry behaves as before it was kept.
    assert entry_profile(_stored(None, OFFLINE, runtime=runtime)) == C300X_QT4


def test_the_live_answer_wins_over_the_kept_model():
    assert entry_profile(_stored("C100X", {"model": "C300X", "display_kind": "qt5_rcc"})) == C300X_QT5
    assert entry_profile(_stored("C300X", {"model": "C100X", "display_kind": "qt5_ondisk"})) == C100X
    kept = _stored("C300X", OFFLINE)
    kept.runtime_data.qml_patch_status = {"qt5_overlay": "active"}
    assert entry_profile(kept) == C300X_QT5


def test_the_entry_keeps_the_model_the_agent_names_and_follows_a_change():
    updates = []

    def update(target, *, data):
        updates.append(data)
        target.data = data

    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))
    entry = SimpleNamespace(data={"host": "station"})
    for setup in (OFFLINE, None, {}, {"model": "C100X", "display_kind": "qt5_ondisk"},
                  {"model": "C100X"}, OFFLINE, {"model": "C300X", "display_kind": "qt4_ondisk"}):
        device_profile.remember_station_model(hass, entry, setup)
    assert updates == [
        {"host": "station", device_profile.STATION_MODEL: "C100X"},
        {"host": "station", device_profile.STATION_MODEL: "C300X"},
    ]
    assert device_profile.station_model_data({"display_kind": "qt5_ondisk"}) == {
        device_profile.STATION_MODEL: "C100X"}
    assert device_profile.station_model_data(OFFLINE) == {}
