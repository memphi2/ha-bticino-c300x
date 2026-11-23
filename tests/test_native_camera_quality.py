"""Bit rate and frame rate of the camera stream, kept in a settings file of the device."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from http.client import HTTPConnection
from pathlib import Path

import pytest

from native_agent.test.smoke import TOKEN, free_tcp_ports, wait_for_health

ROOT = Path(__file__).resolve().parents[1]
PATH = "/api/v1/maintenance/camera-quality"
HEADERS = {"Authorization": "Bearer " + TOKEN,
           "X-Bticino-C300X-Maintenance-Token": "maintenance-token"}
SETTINGS = (
    "[General Parameters]\nBitrateRtpH=1\n\n"
    "[Answering Machine]\nBitrate=2500\nWidth=800\nHeight=480\nBitrateRtpH=800\nFpsRtpH=15\n"
    "BitrateRtpL=180\nFpsRtpL=10\nWidthLow=400\nHeightLow=288\nLcdDelay=600\n\n"
    "[Audio]\nFpsRtpH=1\nBitrate=250\n"
    "[Netatmo]\nWidth=432\nHeight=240\n"
)
CONFIRM = {"confirm": "apply_camera_quality"}
ROUTING_STOCK = b"isolated stock routing fixture\n"
# The device's stack_open.xml as far as the cut goes; the rest stays as it is.
STACK = (
    "<?xml version=\"1.0\"?>\n<stack>\n<video>\n<crop>\n<left>16</left>\n<top>48</top>\n"
    "<width>688</width>\n<height>480</height>\n</crop>\n<brightness>\n<min>30</min>\n"
    "</brightness>\n</video>\n</stack>\n"
)
WHOLE_PICTURE = STACK.replace("<left>16</left>\n<top>48</top>\n<width>688</width>\n<height>480</height>",
                              "<left>8</left>\n<top>0</top>\n<width>704</width>\n<height>576</height>")


@pytest.fixture(scope="module")
def binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build = tmp_path_factory.mktemp("camera-quality-build")
    # Restarts and the Qt 5 mark stay inside the test directory.
    flags = ("-std=c11 -O2 -Wall -Wextra -Werror -pedantic -D_DEFAULT_SOURCE -D_POSIX_C_SOURCE=200809L "
             '-DC300X_NATIVE_AGENT_VERSION=\\"test\\" -DC300X_REBOOT_PROGRAM=\\"./reboot-test.sh\\" '
             '-DC300X_QT5_DISPLAY_MARKER=\\"./qt5-mark\\" '
             f'-DC300X_DEVICE_PATCH_STOCK_SHA256=\\"{hashlib.sha256(ROUTING_STOCK).hexdigest()}\\"')
    subprocess.run(["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}", f"CFLAGS={flags}",
                    "-j2", "all"], check=True, capture_output=True, text=True)
    return build / "host/c300x-agent-native"


@dataclass
class Lab:
    port: int
    settings: Path
    backup: Path
    stack: Path
    env: dict[str, str]
    binary: Path
    start: Callable[[], subprocess.Popen[bytes]]
    process: subprocess.Popen[bytes] | None = None

    def restart_agent(self) -> None:
        """The agent starts again while the device keeps running."""
        assert self.process is not None
        self.process.terminate()
        self.process.wait(timeout=5)
        self.process = self.start()

    def call(self, payload: dict | None = None, *, status: int = 200, headers: dict | None = None) -> dict:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET" if payload is None else "POST", PATH,
                         body=None if payload is None else json.dumps(payload),
                         headers=HEADERS if headers is None else headers)
            result = conn.getresponse()
            body = json.loads(result.read())
        finally:
            conn.close()
        assert result.status == status, body
        return body



@pytest.fixture
def reboot() -> bool:
    """Whether reboot maintenance is on; a test turns it on by parametrizing."""
    return False


@pytest.fixture
def qt5() -> bool:
    """Whether the device is firmware 3.0.x, which sends only the low stream."""
    return False


@pytest.fixture
def lab(binary: Path, tmp_path: Path, reboot: bool, qt5: bool) -> Iterator[Lab]:
    port, ui_port, own = free_tcp_ports(3)
    settings = tmp_path / "bt_answering_machine"
    settings.write_text(SETTINGS)
    settings.chmod(0o664)
    routing = tmp_path / "vendor-bin"
    routing.mkdir()
    (routing / "bt_answering_machine").write_bytes(ROUTING_STOCK)
    stack = tmp_path / "stack_open.xml"
    stack.write_text(STACK)
    config = {
        "listen": {"host": "127.0.0.1", "apiPort": port, "uiPort": ui_port},
        "api": {"token": TOKEN},
        "openwebnet": {"host": "127.0.0.1", "port": own, "timeoutMs": 100},
        "maintenance": {"enabled": True, "adminToken": "maintenance-token",
                        "reboot": {"enabled": reboot, "delayMs": 10}},
        "activations": {"enabled": False, "autoDiscover": False},
        "events": {"udp": {"enabled": False}},
        "answeringMachine": {"messages": {"enabled": False}},
        "memos": {"enabled": False}, "systemMetrics": {"enabled": False},
        "video": {"enabled": True}, "displayBridge": {"enabled": False},
        "mqtt": {"enabled": False}, "mdns": {"enabled": False},
    }
    (tmp_path / "config.json").write_text(json.dumps(config))
    (tmp_path / "boot_id").write_text("boot-1\n")
    (tmp_path / "reboot-test.sh").write_text("#!/bin/sh\ntouch reboot-done\n")
    (tmp_path / "reboot-test.sh").chmod(0o700)
    if qt5:
        (tmp_path / "qt5-mark").touch()
    env = {**os.environ, "C300X_CAMERA_QUALITY_FILE": str(settings), "C300X_CAMERA_CROP_FILE": str(stack),
           "C300X_BOOT_ID_FILE": str(tmp_path / "boot_id"),
           "C300X_CAMERA_RUNNING_NOTE": str(tmp_path / "camera-running"),
           "C300X_ROUTING_TARGET_DIR": str(routing),
           "C300X_ROUTING_BACKUP_DIR": str(tmp_path / "routing-backups"),
           "C300X_DEVICE_PATCH_NO_REMOUNT": "1",
           "C300X_AUDIO_BACKUP_DIR": str(tmp_path / "backups"), "C300X_AUDIO_NO_REMOUNT": "1"}
    log = (tmp_path / "agent.log").open("w")

    def start() -> subprocess.Popen[bytes]:
        process = subprocess.Popen([str(binary), "--config", str(tmp_path / "config.json")],
                                   cwd=tmp_path, stdout=log, stderr=log, env=env)
        wait_for_health(port)
        return process

    lab = Lab(port, settings, tmp_path / "backups" / "bt_answering_machine", stack, env, binary, start)
    try:
        lab.process = start()
        yield lab
    finally:
        if lab.process is not None:
            lab.process.terminate()
            lab.process.wait(timeout=5)
        log.close()


def test_reads_the_values_of_the_high_resolution_stream(lab: Lab) -> None:
    assert lab.call() == {
        "ok": True, "supported": True, "stream": "high", "bitrate_kbps": 800, "fps": 15,
        "size": "688x480", "bitrate_min": 300, "bitrate_max": 3000, "fps_min": 5, "fps_max": 24,
        "sizes": ["688x480", "704x576"],
        "running_bitrate_kbps": 800, "running_fps": 15, "running_size": "688x480",
        "restart_required": False, "changed": False, "remount_ro_failed": False, "rebooting": False,
    }


def test_writes_only_the_two_values_of_its_section_and_keeps_the_original(lab: Lab) -> None:
    mode = lab.settings.stat().st_mode
    body = lab.call({**CONFIRM, "bitrate_kbps": 3000, "fps": 24})

    assert (body["bitrate_kbps"], body["fps"], body["changed"]) == (3000, 24, True)
    # The device reads the file when it starts; reboot maintenance is off here.
    assert (body["running_bitrate_kbps"], body["running_fps"]) == (800, 15)
    assert body["restart_required"] is True and body["rebooting"] is False
    assert lab.settings.read_text() == SETTINGS.replace(
        "BitrateRtpH=800\nFpsRtpH=15", "BitrateRtpH=3000\nFpsRtpH=24")
    assert lab.settings.stat().st_mode == mode
    assert lab.backup.read_text() == SETTINGS
    assert lab.call()["restart_required"] is True


def test_one_value_alone_keeps_the_other(lab: Lab) -> None:
    assert lab.call({**CONFIRM, "fps": 20})["bitrate_kbps"] == 800
    assert lab.call({**CONFIRM, "bitrate_kbps": 1500})["fps"] == 20
    assert "BitrateRtpH=1500\nFpsRtpH=20\n" in lab.settings.read_text()
    # The backup stays the original, not the first change.
    assert lab.backup.read_text() == SETTINGS


def test_the_same_values_write_nothing(lab: Lab) -> None:
    body = lab.call({**CONFIRM, "bitrate_kbps": 800, "fps": 15})
    assert body["changed"] is False and body["restart_required"] is False
    assert not lab.backup.exists()


@pytest.mark.parametrize(("payload", "error"), [
    ({"bitrate_kbps": 299}, "out_of_range"), ({"bitrate_kbps": 3001}, "out_of_range"),
    ({"fps": 4}, "out_of_range"), ({"fps": 25}, "out_of_range"),
    ({"bitrate_kbps": 0}, "out_of_range"), ({"fps": -1}, "out_of_range"),
    ({"fps": "25"}, "invalid_fps"), ({}, "value_required"),
    # A value that is not a whole number is refused, also beside a good one.
    ({"bitrate_kbps": 1000, "fps": 20.5}, "invalid_fps"),
    ({"bitrate_kbps": 1000, "fps": None}, "invalid_fps"),
    ({"bitrate_kbps": True, "fps": 20}, "invalid_bitrate"),
    ({"bitrate_kbps": 99999999999, "fps": 20}, "invalid_bitrate"),
])
def test_values_outside_the_range_are_refused(lab: Lab, payload: dict, error: str) -> None:
    body = lab.call({**CONFIRM, **payload}, status=400)
    assert body == {"ok": False, "error": "camera_quality_" + error}
    assert lab.settings.read_text() == SETTINGS


def test_a_write_needs_the_maintenance_token_and_the_confirmation(lab: Lab) -> None:
    lab.call({"bitrate_kbps": 1000}, status=400)
    lab.call({**CONFIRM, "bitrate_kbps": 1000}, status=403,
             headers={"Authorization": "Bearer " + TOKEN})
    lab.call(status=403, headers={"Authorization": "Bearer " + TOKEN})
    assert lab.settings.read_text() == SETTINGS


@pytest.mark.parametrize("damage", ["missing", "modified", "symlink"])
def test_removal_refuses_unverified_routing_before_camera_restore(lab: Lab, damage: str) -> None:
    lab.call({**CONFIRM, "bitrate_kbps": 3000, "fps": 24})
    settings = lab.settings.read_bytes()
    backup = lab.backup.read_bytes()
    routing = Path(lab.env["C300X_ROUTING_TARGET_DIR"]) / "bt_answering_machine"
    routing.unlink()
    if damage == "modified":
        routing.write_bytes(b"unknown routing executable\n")
    elif damage == "symlink":
        original = routing.with_name("original")
        original.write_bytes(ROUTING_STOCK)
        routing.symlink_to(original)
    result = subprocess.run([str(lab.binary), "--restore-media-patches"], env=lab.env,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode != 0
    assert "Failed to restore device routing" in result.stderr
    assert lab.settings.read_bytes() == settings
    assert lab.backup.read_bytes() == backup


@pytest.mark.parametrize("content", [
    "", "[Answering Machine]\nBitrateRtpH=800\n", "[Other]\nBitrateRtpH=800\nFpsRtpH=15\n",
    "[Answering Machine]\nBitrateRtpH=abc\nFpsRtpH=15\n",
    "[Answering Machine]\nBitrateRtpH=800 \nFpsRtpH=15\n",
    # Each value must be there exactly once, so no copy is left unchanged.
    "[Answering Machine]\nBitrateRtpH=800\nFpsRtpH=15\nBitrateRtpH=900\n",
    "[Answering Machine]\nBitrateRtpH=800\nFpsRtpH=15\n[Answering Machine]\nFpsRtpH=10\n",
])
def test_a_file_without_the_values_is_reported_and_left_alone(lab: Lab, content: str) -> None:
    lab.settings.write_text(content)
    assert lab.call()["supported"] is False
    body = lab.call({**CONFIRM, "bitrate_kbps": 1000}, status=409)
    assert body["error"] == "camera_quality_unsupported"
    assert lab.settings.read_text() == content


def test_removing_the_agent_puts_the_original_values_back(lab: Lab) -> None:
    lab.call({**CONFIRM, "bitrate_kbps": 3000, "fps": 24})
    # The device changed another value of the file meanwhile; that one stays.
    lab.settings.write_text(lab.settings.read_text().replace("LcdDelay=600", "LcdDelay=700"))

    for _ in range(2):
        result = subprocess.run([str(lab.binary), "--restore-media-patches"], env=lab.env,
                                capture_output=True, text=True, timeout=10, check=False)
        assert result.returncode == 0, result.stderr
        assert lab.settings.read_text() == SETTINGS.replace("LcdDelay=600", "LcdDelay=700")


def test_restart_required_compares_the_values_with_what_the_device_started_with(lab: Lab) -> None:
    assert lab.call({**CONFIRM, "bitrate_kbps": 3000})["restart_required"] is True
    # Back to what runs: nothing is waiting for a restart.
    assert lab.call({**CONFIRM, "bitrate_kbps": 800})["restart_required"] is False
    # Another value of the file does not count.
    lab.settings.write_text(lab.settings.read_text().replace("LcdDelay=600", "LcdDelay=700"))
    assert lab.call()["restart_required"] is False


def test_an_agent_that_restarts_without_the_device_keeps_what_the_device_runs(lab: Lab) -> None:
    lab.call({**CONFIRM, "bitrate_kbps": 3000, "fps": 24})
    lab.restart_agent()
    body = lab.call()
    assert (body["running_bitrate_kbps"], body["running_fps"]) == (800, 15)
    assert body["restart_required"] is True
    # A note of an older agent, without the size or the cut, is not trusted.
    note = lab.settings.parent / "camera-running"
    for old in ("boot-1 800 15\n", "boot-1 800 15 800 480\n"):
        note.write_text(old)
        lab.restart_agent()
        assert lab.call()["running_fps"] == 24
    note.write_text("boot-1 800 15 800 480 16 48 688 480\n")
    lab.restart_agent()
    assert lab.call()["running_fps"] == 15
    # A new boot of the device runs what the file has.
    lab.process.terminate()
    lab.process.wait(timeout=5)
    (lab.settings.parent / "boot_id").write_text("boot-2\n")
    lab.process = lab.start()
    body = lab.call()
    assert (body["running_bitrate_kbps"], body["running_fps"], body["restart_required"]) == (3000, 24, False)


@pytest.mark.parametrize("content", [
    "[Answering Machine]\nLcdDelay=600\n",
    "[Answering Machine]\nBitrateRtpH=3000\nFpsRtpH=24\nBitrateRtpH=900\n",
])
def test_removal_leaves_a_file_alone_that_lost_its_values(lab: Lab, content: str) -> None:
    lab.call({**CONFIRM, "bitrate_kbps": 3000, "fps": 24})
    lab.settings.write_text(content)
    result = subprocess.run([str(lab.binary), "--restore-media-patches"], env=lab.env,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    assert lab.settings.read_text() == content


def test_removal_puts_back_an_original_value_outside_the_offered_range(lab: Lab) -> None:
    original = SETTINGS.replace("FpsRtpH=15", "FpsRtpH=30")
    lab.settings.write_text(original)
    lab.call({**CONFIRM, "bitrate_kbps": 1000, "fps": 20})
    result = subprocess.run([str(lab.binary), "--restore-media-patches"], env=lab.env,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    assert lab.settings.read_text() == original


def wait_for(path: Path) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return False


@pytest.mark.parametrize("reboot", [True])
def test_a_change_restarts_the_device_like_the_codec_switch(lab: Lab) -> None:
    done = lab.settings.parent / "reboot-done"
    assert lab.call({**CONFIRM, "fps": 20, "reboot": False})["rebooting"] is False
    assert not done.exists()
    body = lab.call({**CONFIRM, "fps": 24})
    assert body["rebooting"] is True and body["restart_required"] is True
    assert wait_for(done)


@pytest.mark.parametrize("reboot", [True])
def test_values_the_device_already_runs_restart_nothing(lab: Lab) -> None:
    body = lab.call({**CONFIRM, "bitrate_kbps": 800, "fps": 15})
    assert body["rebooting"] is False and body["changed"] is False
    time.sleep(0.3)  # a scheduled restart runs after 10 ms
    assert not (lab.settings.parent / "reboot-done").exists()


@pytest.mark.parametrize("reboot", [True])
def test_a_change_restarts_also_when_the_running_values_are_unknown(lab: Lab) -> None:
    # The file had no values when the agent started, so it cannot tell what runs.
    lab.settings.write_text("[Answering Machine]\nWidth=800\n")
    (lab.settings.parent / "camera-running").unlink(missing_ok=True)
    lab.restart_agent()
    lab.settings.write_text(SETTINGS)
    assert lab.call()["running_fps"] == 0
    body = lab.call({**CONFIRM, "fps": 20})
    assert body["rebooting"] is True and body["restart_required"] is True
    assert wait_for(lab.settings.parent / "reboot-done")


def test_a_change_with_unknown_running_values_stays_pending_until_a_restart(lab: Lab) -> None:
    lab.settings.write_text("[Answering Machine]\nWidth=800\n")
    (lab.settings.parent / "camera-running").unlink(missing_ok=True)
    lab.restart_agent()
    lab.settings.write_text(SETTINGS)
    assert lab.call({**CONFIRM, "fps": 20})["restart_required"] is True
    body = lab.call()
    assert (body["running_fps"], body["restart_required"]) == (15, True)
    # An agent restart within the same boot keeps it pending.
    lab.restart_agent()
    body = lab.call()
    assert (body["running_fps"], body["restart_required"]) == (15, True)


def test_disabled_reboot_maintenance_saves_without_a_restart(lab: Lab) -> None:
    body = lab.call({**CONFIRM, "fps": 24})
    assert body["rebooting"] is False and body["restart_required"] is True
    assert "FpsRtpH=24" in lab.settings.read_text()


@pytest.mark.parametrize("qt5", [True])
def test_firmware_3_sets_the_low_stream_its_only_stream(lab: Lab) -> None:
    body = lab.call()
    assert (body["stream"], body["bitrate_kbps"], body["fps"], body["size"]) == ("low", 180, 10, "400x288")
    assert body["sizes"] == ["352x288", "400x288", "640x480", "704x576", "720x576"]
    assert body["running_size"] == "400x288"
    assert (body["bitrate_min"], body["bitrate_max"], body["fps_max"]) == (100, 2000, 25)
    body = lab.call({**CONFIRM, "bitrate_kbps": 600, "fps": 25, "size": "720x576"})
    assert body["changed"] is True and body["restart_required"] is True
    assert lab.settings.read_text() == SETTINGS.replace(
        "BitrateRtpL=180\nFpsRtpL=10\nWidthLow=400\nHeightLow=288",
        "BitrateRtpL=600\nFpsRtpL=25\nWidthLow=720\nHeightLow=576")
    assert lab.call({**CONFIRM, "bitrate_kbps": 2001}, status=400)["error"] == "camera_quality_out_of_range"
    assert lab.call({**CONFIRM, "size": "688x480"}, status=400)["error"] == "camera_quality_invalid_size"
    result = subprocess.run([str(lab.binary), "--restore-media-patches"], env=lab.env, cwd=lab.settings.parent,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    assert lab.settings.read_text() == SETTINGS


@pytest.mark.parametrize("qt5", [True])
def test_firmware_3_without_the_values_still_names_its_low_stream(lab: Lab) -> None:
    lab.settings.write_text("[Answering Machine]\nWidth=800\n")
    body = lab.call()
    assert (body["supported"], body["stream"], body["bitrate_max"]) == (False, "low", 2000)


def test_the_whole_camera_picture_is_chosen_by_the_cut(lab: Lab) -> None:
    body = lab.call({**CONFIRM, "size": "704x576"})
    assert (body["size"], body["running_size"], body["restart_required"]) == ("704x576", "688x480", True)
    # Width and Height stay: the display keeps showing the picture over its whole width.
    assert lab.settings.read_text() == SETTINGS
    assert lab.stack.read_text() == WHOLE_PICTURE
    assert (lab.backup.parent / "stack_open.xml.camera").read_text() == STACK
    # The audio codec switch keeps its own backup of the same file.
    assert not (lab.backup.parent / "stack_open.xml").exists()
    assert lab.call({**CONFIRM, "size": "688x480"})["restart_required"] is False
    assert lab.stack.read_text() == STACK
    for size in ("720x576", "800x600", 720):
        assert lab.call({**CONFIRM, "size": size}, status=400)["error"] == "camera_quality_invalid_size"
    assert (lab.settings.read_text(), lab.stack.read_text()) == (SETTINGS, STACK)


def test_a_device_set_to_the_whole_picture_by_width_and_height_gets_the_cut(lab: Lab) -> None:
    lab.settings.write_text(SETTINGS.replace("Width=800\nHeight=480\nBitrate", "Width=720\nHeight=480\nBitrate"))
    assert lab.call()["size"] == "720x576"
    lab.call({**CONFIRM, "size": "704x576"})
    assert (lab.settings.read_text(), lab.stack.read_text()) == (SETTINGS, WHOLE_PICTURE)


@pytest.mark.parametrize("stack", [
    "", "<crop>\n<left>16</left>\n<top>48</top>\n<width>688</width>\n</crop>\n",
    STACK.replace("<top>48</top>", "<top>48 </top>"), STACK + STACK,
])
def test_a_cut_file_without_its_four_numbers_is_reported_and_left_alone(lab: Lab, stack: str) -> None:
    lab.stack.write_text(stack)
    assert lab.call()["supported"] is False
    assert lab.call({**CONFIRM, "size": "704x576"}, status=409)["error"] == "camera_quality_unsupported"
    assert lab.stack.read_text() == stack


@pytest.mark.parametrize("qt5", [True])
def test_firmware_3_leaves_the_cut_file_alone(lab: Lab) -> None:
    lab.stack.write_text("no cut here")
    assert lab.call({**CONFIRM, "size": "704x576"})["size"] == "704x576"
    assert lab.stack.read_text() == "no cut here"


def test_a_size_the_file_already_gives_keeps_its_width_and_height(lab: Lab) -> None:
    lab.settings.write_text(SETTINGS.replace("Width=800\nHeight=480\nBitrate", "Width=704\nHeight=576\nBitrate"))
    body = lab.call({**CONFIRM, "size": "720x576", "fps": 20})
    assert body["size"] == "720x576"
    assert "Width=704\nHeight=576\n" in lab.settings.read_text()


def test_removal_puts_back_the_original_size(lab: Lab) -> None:
    lab.call({**CONFIRM, "size": "704x576", "bitrate_kbps": 3000, "fps": 24})
    # The device changed another part of the cut file meanwhile; that one stays.
    lab.stack.write_text(lab.stack.read_text().replace("<min>30</min>", "<min>40</min>"))
    for _ in range(2):
        result = subprocess.run([str(lab.binary), "--restore-media-patches"], env=lab.env,
                                capture_output=True, text=True, timeout=10, check=False)
        assert result.returncode == 0, result.stderr
        assert lab.settings.read_text() == SETTINGS
        assert lab.stack.read_text() == STACK.replace("<min>30</min>", "<min>40</min>")


def test_a_failed_backup_leaves_the_file_unchanged(lab: Lab) -> None:
    lab.backup.parent.parent.mkdir(parents=True, exist_ok=True)
    lab.backup.parent.write_text("not a directory")
    assert lab.call({**CONFIRM, "fps": 24}, status=500)["error"] == "camera_quality_backup_failed"
    assert lab.settings.read_text() == SETTINGS


def test_a_value_outside_the_range_in_the_file_does_not_block_the_other(lab: Lab) -> None:
    lab.settings.write_text(SETTINGS.replace("FpsRtpH=15", "FpsRtpH=30"))
    body = lab.call({**CONFIRM, "bitrate_kbps": 1200})
    assert (body["bitrate_kbps"], body["fps"]) == (1200, 30)
    assert lab.call({**CONFIRM, "fps": 25}, status=400)["error"] == "camera_quality_out_of_range"
