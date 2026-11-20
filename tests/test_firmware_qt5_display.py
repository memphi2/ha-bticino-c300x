"""Firmware 3.0.x: a Qt 5 display, recognised by its library, not by a missing folder."""

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
    binary = folder / "probe"
    curl = os.environ.get("CURL_INCLUDE_DIR", "")
    sources = [str(path) for path in sorted((NATIVE / "src").glob("*.c")) if path.name != "main.c"]
    subprocess.run(
        [
            "gcc", "-std=c11", "-O1", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
            *([f"-idirafter{curl}"] if curl else []),
            f"-DC300X_QT5_DISPLAY_MARKER={json.dumps(str(marker))}",
            str(NATIVE / "test/qt5_display_test.c"), *sources,
            "-o", str(binary), "-pthread", "-ldl",
        ],
        check=True, capture_output=True, text=True,
    )

    def run(
        *, qt5: bool, high_resolution: bool | None, display_patch: bool = False,
        save: bool | None = None,
    ) -> dict:
        marker.unlink(missing_ok=True)
        if qt5:
            marker.write_bytes(b"")
        config = json.loads((NATIVE / "config.example.json").read_text(encoding="utf-8"))
        config["video"]["av"].pop("highResolution", None)
        if high_resolution is not None:
            config["video"]["av"]["highResolution"] = high_resolution
        if display_patch:
            config["maintenance"]["adminToken"] = "admin"
            config["maintenance"]["qmlPatch"] = {"enabled": True, "script": "/data/qml_patch.sh"}
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


def test_the_agent_offers_the_camera_resolution_except_on_a_qt5_display():
    http = (NATIVE / "src/http.c").read_text(encoding="utf-8")
    capabilities = (NATIVE / "src/capabilities.c").read_text(encoding="utf-8")
    assert ".camera_resolution_fixed = c300x_device_display_is_qt5()," in http
    assert '\\"camera_resolution\\":%s}' in capabilities
    assert "config->video_enabled && !context->camera_resolution_fixed" in capabilities


def test_the_agent_offers_no_display_patch_on_a_qt5_display(config_probe):
    # The installer enables the Display patch; a Qt 5 display has nothing to patch,
    # so the agent neither offers it nor its repairs.
    assert config_probe(qt5=False, high_resolution=None, display_patch=True)["display_patch"] == 1
    assert config_probe(qt5=True, high_resolution=None, display_patch=True)["display_patch"] == 0


def test_the_agent_skips_the_display_label_only_on_a_qt5_display():
    http = (NATIVE / "src/http.c").read_text(encoding="utf-8")
    assert "if (!c300x_device_display_is_qt5()) {" in http
    # Nor does it ask the Display patch for the label status there.
    assert "&& !c300x_device_display_is_qt5()\n        && access(config->maintenance_qml_patch_script, X_OK) == 0" in http
    assert "skins/default" not in http
    assert "skins/default" not in (NATIVE / "src/config.c").read_text(encoding="utf-8")


class _Device:
    def __init__(self, *, qt5: bool) -> None:
        self.qt5 = qt5
        self.commands: list[str] = []

    def run(self, command: str) -> str:
        self.commands.append(command)
        if "libQt5Core" in command:
            return "yes\n" if self.qt5 else "no\n"
        return json.dumps({"ok": True, "core_patched": True, "gui_running": True, "patched": True})


def test_the_installer_recognises_the_qt5_display_by_its_library():
    device = _Device(qt5=True)
    assert installer._device_display_is_qt5(device) is True
    assert device.commands == ["test -e /usr/lib/libQt5Core.so.5 && echo yes || echo no"]
    assert installer._device_display_is_qt5(_Device(qt5=False)) is False


def test_the_display_patch_is_skipped_on_a_qt5_display_and_runs_on_a_qt4_one():
    qt5 = _Device(qt5=True)
    installer._apply_qml_patch_sync(qt5, "/data/agent", "apply")
    assert not any("qml_patch.sh" in command for command in qt5.commands)

    # On a Qt 4 device the patch runs.
    qt4 = _Device(qt5=False)
    installer._apply_qml_patch_sync(qt4, "/data/agent", "apply")
    assert any("qml_patch.sh" in command for command in qt4.commands)


def test_the_installer_fixes_the_low_resolution_only_on_a_qt5_display():
    unset = json.dumps({"video": {"av": {}}}).encode()
    low = json.loads(installer._apply_qt5_low_res_video_default(_Device(qt5=True), unset))
    assert low["video"]["av"]["highResolution"] is False
    assert installer._apply_qt5_low_res_video_default(_Device(qt5=False), unset) == unset
    pinned = json.dumps({"video": {"av": {"highResolution": True}}}).encode()
    fixed = json.loads(installer._apply_qt5_low_res_video_default(_Device(qt5=True), pinned))
    assert fixed["video"]["av"]["highResolution"] is False
    assert installer._apply_qt5_low_res_video_default(_Device(qt5=False), pinned) == pinned
