"""Device detection: model and display kind, and the Qt 5 firmwares that follow from them."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from custom_components.bticino_c300x import device_installer as installer

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native_agent"


@pytest.fixture(scope="module")
def config_probe(tmp_path_factory):
    folder = tmp_path_factory.mktemp("qt5")
    marker = folder / "libQt5Core.so.5"
    c100x = folder / "BtClass100"
    binary = folder / "probe"
    curl = os.environ.get("CURL_INCLUDE_DIR", "")
    sources = [str(path) for path in sorted((NATIVE / "src").glob("*.c")) if path.name != "main.c"]
    subprocess.run(
        [
            "gcc", "-std=c11", "-O1", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
            *([f"-idirafter{curl}"] if curl else []),
            f"-DC300X_QT5_DISPLAY_MARKER={json.dumps(str(marker))}",
            f"-DC300X_C100X_DISPLAY_MARKER={json.dumps(str(c100x))}",
            str(NATIVE / "test/qt5_display_test.c"), *sources,
            "-o", str(binary), "-pthread", "-ldl",
        ],
        check=True, capture_output=True, text=True,
    )

    def run(
        *, qt5: bool, high_resolution: bool | None = None, display_patch: bool = False,
        save: bool | None = None, c100x_display: bool = False,
    ) -> dict:
        marker.unlink(missing_ok=True)
        c100x.unlink(missing_ok=True)
        if qt5:
            marker.write_bytes(b"")
        if c100x_display:
            c100x.write_bytes(b"")
        config = json.loads((NATIVE / "config.example.json").read_text(encoding="utf-8"))
        config["video"]["av"].pop("highResolution", None)
        if high_resolution is not None:
            config["video"]["av"]["highResolution"] = high_resolution
        if display_patch:
            config["maintenance"]["adminToken"] = "admin"
            config["maintenance"]["qmlPatch"] = {"enabled": True, "script": "/data/qml_patch.sh"}
            config["maintenance"]["guiReload"] = {"enabled": True, "script": "/data/qml_patch.sh"}
        path = folder / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        command = [str(binary), str(path)] + ([] if save is None else [str(int(save))])
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        answer = json.loads(result.stdout)
        answer["stored"] = json.loads(path.read_text(encoding="utf-8"))["video"]["av"].get("highResolution")
        return answer

    return run


def test_the_agent_fixes_the_low_resolution_stream_on_a_qt5_display(config_probe):
    assert config_probe(qt5=False, high_resolution=None)["high_resolution"] == 1
    assert config_probe(qt5=False, high_resolution=False)["high_resolution"] == 0
    # 3.0.x sends only the low-resolution stream on to other receivers,
    # so the agent uses it whatever the config says.
    assert config_probe(qt5=True, high_resolution=None)["high_resolution"] == 0
    assert config_probe(qt5=True, high_resolution=True)["high_resolution"] == 0


def test_the_camera_resolution_is_saved_and_refused_high_on_a_qt5_display(config_probe):
    low = config_probe(qt5=False, high_resolution=True, save=False)
    assert (low["saved"], low["changed"], low["high_resolution"], low["stored"]) == (1, 1, 0, False)
    high = config_probe(qt5=False, high_resolution=False, save=True)
    assert (high["saved"], high["changed"], high["high_resolution"], high["stored"]) == (1, 1, 1, True)
    same = config_probe(qt5=False, high_resolution=True, save=True)
    assert (same["saved"], same["changed"]) == (1, 0)
    refused = config_probe(qt5=True, high_resolution=None, save=True)
    assert (refused["saved"], refused["high_resolution"], refused["stored"]) == (0, 0, None)
    assert config_probe(qt5=True, high_resolution=None, save=False)["saved"] == 1


@pytest.mark.parametrize(("qt5", "c100x_display", "model", "kind"), [
    (False, False, "C300X", "qt4_ondisk"),
    (True, False, "C300X", "qt5_rcc"),
    (True, True, "C100X", "qt5_ondisk"),
    (False, True, "C100X", "qt5_ondisk"),
], ids=["c300x-1.7-2.0", "c300x-3.0", "c100x-1.5", "c100x-no-library-marker"])
def test_the_agent_names_the_model_and_display_of_each_firmware(config_probe, qt5, c100x_display, model, kind):
    answer = config_probe(qt5=qt5, c100x_display=c100x_display, display_patch=True)
    assert (answer["model"], answer["display_kind"]) == (model, kind)
    # Every C300X gets the Display patch, the C100X its own activation; the
    # Qt 5 firmwares send only the low stream.
    qt4 = kind == "qt4_ondisk"
    assert answer["files_patchable"] == answer["display_patch"] == int(model == "C300X")
    # The display program is restarted on every C300X, never on the C100X.
    assert answer["restartable"] == answer["gui_reload"] == int(model == "C300X")
    assert answer["resolution_fixed"] == int(not qt4)
    assert answer["high_resolution"] == int(qt4)


def test_a_c100x_keeps_the_low_stream_whatever_its_libraries(config_probe):
    # Its bt_av_media builds no high-resolution branch on the C100X board.
    answer = config_probe(qt5=False, c100x_display=True, high_resolution=True)
    assert (answer["model"], answer["resolution_fixed"], answer["high_resolution"]) == ("C100X", 1, 0)


def test_the_agent_offers_the_camera_resolution_except_on_a_qt5_display():
    http = (NATIVE / "src/http.c").read_text(encoding="utf-8")
    capabilities = (NATIVE / "src/capabilities.c").read_text(encoding="utf-8")
    assert ".camera_resolution_fixed = c300x_device_camera_resolution_fixed()," in http
    assert ".display_kind = c300x_display_kind_name(c300x_device_display_kind())," in http
    assert '\\"camera_resolution\\":%s,\\"camera_quality\\":%s}' in capabilities
    assert "config->video_enabled && !context->camera_resolution_fixed" in capabilities


def test_the_agent_offers_the_display_patch_on_both_displays(config_probe):
    # On a Qt 5 display the patch script works through the preloaded resource file.
    assert config_probe(qt5=False, high_resolution=None, display_patch=True)["display_patch"] == 1
    assert config_probe(qt5=True, high_resolution=None, display_patch=True)["display_patch"] == 1


def test_the_agent_asks_the_patch_script_for_the_label_on_both_displays():
    routes = (NATIVE / "src/http_device_user.c").read_text(encoding="utf-8")
    assert "c300x_device_display_is_qt5()" not in routes
    # Creation, deletion and routing restoration skip the label on a C100X only.
    assert routes.count("c300x_device_display_files_patchable()") == 3


class _Device:
    def __init__(self, *, qt5: bool, c100x: bool = False) -> None:
        self.qt5 = qt5
        self.c100x = c100x
        self.commands: list[str] = []

    def run(self, command: str) -> str:
        self.commands.append(command)
        if "libQt5Core" in command:
            return ("qt5" if self.qt5 else "qt4") + "\n" + ("c100x" if self.c100x else "c300x") + "\n"
        return json.dumps({"ok": True, "core_patched": True, "gui_running": True, "patched": True})


def test_the_installer_names_the_display_like_the_agent():
    device = _Device(qt5=True)
    assert installer._device_display_kind(device) == "qt5_rcc"
    assert device.commands == [
        "test -e /usr/lib/libQt5Core.so.5 && echo qt5 || echo qt4; "
        "test -e /home/bticino/bin/gui/BtClass100 && echo c100x || echo c300x"
    ]
    assert installer._device_display_kind(_Device(qt5=False)) == "qt4_ondisk"
    assert installer._device_display_kind(_Device(qt5=True, c100x=True)) == "qt5_ondisk"


class _Mute(_Device):
    def run(self, command: str) -> str:
        self.commands.append(command)
        return ""


def test_an_unreadable_display_answer_counts_as_the_qt4_display():
    assert installer._device_display_kind(_Mute(qt5=True)) == "qt4_ondisk"


@pytest.mark.parametrize("qt5", [False, True])
def test_a_c100x_gets_no_display_patch_and_the_low_stream_for_now(qt5):
    c100x = _Device(qt5=qt5, c100x=True)
    assert installer._apply_display_step_sync(c100x, "/data/agent", "apply", qt5=False) is False
    assert not any("qml_patch.sh" in command for command in c100x.commands)
    unset = json.dumps({"video": {"av": {}}}).encode()
    low = json.loads(installer._apply_qt5_low_res_video_default(installer._device_display_kind(c100x), unset))
    assert low["video"]["av"]["highResolution"] is False


def test_the_display_patch_runs_on_both_displays():
    for qt5 in (True, False):
        device = _Device(qt5=qt5)
        installer._apply_qml_patch_sync(device, "/data/agent", "apply")
        assert any("qml_patch.sh" in command for command in device.commands)


def test_the_installer_fixes_the_low_resolution_only_on_a_qt5_display():
    unset = json.dumps({"video": {"av": {}}}).encode()
    low = json.loads(installer._apply_qt5_low_res_video_default("qt5_rcc", unset))
    assert low["video"]["av"]["highResolution"] is False
    assert installer._apply_qt5_low_res_video_default("qt4_ondisk", unset) == unset
    pinned = json.dumps({"video": {"av": {"highResolution": True}}}).encode()
    fixed = json.loads(installer._apply_qt5_low_res_video_default("qt5_rcc", pinned))
    assert fixed["video"]["av"]["highResolution"] is False
    assert installer._apply_qt5_low_res_video_default("qt4_ondisk", pinned) == pinned
