"""Bit rate and frame rate of the camera stream, kept in a settings file of the device."""

from __future__ import annotations

import json
import os
import subprocess
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
    "[Answering Machine]\nBitrate=2500\nWidth=800\nBitrateRtpH=800\nFpsRtpH=15\n"
    "BitrateRtpL=180\nFpsRtpL=10\nLcdDelay=600\n\n"
    "[Audio]\nFpsRtpH=1\nBitrate=250\n"
)
CONFIRM = {"confirm": "apply_camera_quality"}


@pytest.fixture(scope="module")
def binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build = tmp_path_factory.mktemp("camera-quality-build")
    subprocess.run(["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}", "-j2", "all"],
                   check=True, capture_output=True, text=True)
    return build / "host/c300x-agent-native"


@dataclass
class Lab:
    port: int
    settings: Path
    backup: Path
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
def lab(binary: Path, tmp_path: Path) -> Iterator[Lab]:
    port, ui_port, own = free_tcp_ports(3)
    settings = tmp_path / "bt_answering_machine"
    settings.write_text(SETTINGS)
    settings.chmod(0o664)
    config = {
        "listen": {"host": "127.0.0.1", "apiPort": port, "uiPort": ui_port},
        "api": {"token": TOKEN},
        "openwebnet": {"host": "127.0.0.1", "port": own, "timeoutMs": 100},
        "maintenance": {"enabled": True, "adminToken": "maintenance-token"},
        "activations": {"enabled": False, "autoDiscover": False},
        "events": {"udp": {"enabled": False}},
        "answeringMachine": {"messages": {"enabled": False}},
        "memos": {"enabled": False}, "systemMetrics": {"enabled": False},
        "video": {"enabled": True}, "displayBridge": {"enabled": False},
        "mqtt": {"enabled": False}, "mdns": {"enabled": False},
    }
    (tmp_path / "config.json").write_text(json.dumps(config))
    (tmp_path / "boot_id").write_text("boot-1\n")
    env = {**os.environ, "C300X_CAMERA_QUALITY_FILE": str(settings),
           "C300X_BOOT_ID_FILE": str(tmp_path / "boot_id"),
           "C300X_CAMERA_RUNNING_NOTE": str(tmp_path / "camera-running"),
           "C300X_AUDIO_BACKUP_DIR": str(tmp_path / "backups"), "C300X_AUDIO_NO_REMOUNT": "1"}
    log = (tmp_path / "agent.log").open("w")

    def start() -> subprocess.Popen[bytes]:
        process = subprocess.Popen([str(binary), "--config", str(tmp_path / "config.json")],
                                   cwd=tmp_path, stdout=log, stderr=log, env=env)
        wait_for_health(port)
        return process

    lab = Lab(port, settings, tmp_path / "backups" / "bt_answering_machine", env, binary, start)
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
        "ok": True, "supported": True, "bitrate_kbps": 800, "fps": 15,
        "bitrate_min": 300, "bitrate_max": 3000, "fps_min": 5, "fps_max": 25,
        "running_bitrate_kbps": 800, "running_fps": 15,
        "restart_required": False, "changed": False, "remount_ro_failed": False, "rebooting": False,
    }


def test_writes_only_the_two_values_of_its_section_and_keeps_the_original(lab: Lab) -> None:
    mode = lab.settings.stat().st_mode
    body = lab.call({**CONFIRM, "bitrate_kbps": 3000, "fps": 25})

    assert (body["bitrate_kbps"], body["fps"], body["changed"]) == (3000, 25, True)
    # The device reads the file when it starts; reboot maintenance is off here.
    assert (body["running_bitrate_kbps"], body["running_fps"]) == (800, 15)
    assert body["restart_required"] is True and body["rebooting"] is False
    assert lab.settings.read_text() == SETTINGS.replace(
        "BitrateRtpH=800\nFpsRtpH=15", "BitrateRtpH=3000\nFpsRtpH=25")
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
    ({"fps": 4}, "out_of_range"), ({"fps": 26}, "out_of_range"),
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
    lab.call({**CONFIRM, "bitrate_kbps": 3000, "fps": 25})
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
    lab.call({**CONFIRM, "bitrate_kbps": 3000, "fps": 25})
    lab.restart_agent()
    body = lab.call()
    assert (body["running_bitrate_kbps"], body["running_fps"]) == (800, 15)
    assert body["restart_required"] is True
    # A new boot of the device runs what the file has.
    lab.process.terminate()
    lab.process.wait(timeout=5)
    (lab.settings.parent / "boot_id").write_text("boot-2\n")
    lab.process = lab.start()
    body = lab.call()
    assert (body["running_bitrate_kbps"], body["running_fps"], body["restart_required"]) == (3000, 25, False)


@pytest.mark.parametrize("content", [
    "[Answering Machine]\nLcdDelay=600\n",
    "[Answering Machine]\nBitrateRtpH=3000\nFpsRtpH=25\nBitrateRtpH=900\n",
])
def test_removal_leaves_a_file_alone_that_lost_its_values(lab: Lab, content: str) -> None:
    lab.call({**CONFIRM, "bitrate_kbps": 3000, "fps": 25})
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


def test_the_route_restarts_the_device_like_the_codec_switch() -> None:
    route = (ROOT / "native_agent/src/http_camera_quality.c").read_text()
    assert ("if (reboot && config->maintenance_reboot_enabled && quality->restart_required) {\n"
            "        c300x_http_service_reboot(owner, fd, config, schedule, reply_quality, quality, free);") in route
    http = (ROOT / "native_agent/src/http.c").read_text()
    assert "c300x_device_display_is_qt5(), request, run_detached_command)" in http
    assert "    c300x_camera_quality_note_running();\n" in http
