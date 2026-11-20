"""Bit rate and frame rate of the camera stream, kept in a settings file of the device."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
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

    def started_long_ago(self) -> None:
        """As after a device restart: the file is older than the running system."""
        os.utime(self.settings, (1_500_000_000, 1_500_000_000))


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
        "video": {"enabled": False}, "displayBridge": {"enabled": False},
        "mqtt": {"enabled": False}, "mdns": {"enabled": False},
    }
    (tmp_path / "config.json").write_text(json.dumps(config))
    env = {**os.environ, "C300X_CAMERA_QUALITY_FILE": str(settings),
           "C300X_AUDIO_BACKUP_DIR": str(tmp_path / "backups"), "C300X_AUDIO_NO_REMOUNT": "1"}
    with (tmp_path / "agent.log").open("w") as log:
        process = subprocess.Popen([str(binary), "--config", str(tmp_path / "config.json")],
                                   cwd=tmp_path, stdout=log, stderr=log, env=env)
        try:
            wait_for_health(port)
            yield Lab(port, settings, tmp_path / "backups" / "bt_answering_machine", env, binary)
        finally:
            process.terminate()
            process.wait(timeout=5)


def test_reads_the_values_of_the_high_resolution_stream(lab: Lab) -> None:
    lab.started_long_ago()
    assert lab.call() == {
        "ok": True, "supported": True, "bitrate_kbps": 800, "fps": 15,
        "bitrate_min": 300, "bitrate_max": 3000, "fps_min": 5, "fps_max": 25,
        "restart_required": False, "changed": False, "remount_ro_failed": False,
    }


def test_writes_only_the_two_values_of_its_section_and_keeps_the_original(lab: Lab) -> None:
    lab.started_long_ago()
    mode = lab.settings.stat().st_mode
    body = lab.call({**CONFIRM, "bitrate_kbps": 3000, "fps": 25})

    assert (body["bitrate_kbps"], body["fps"], body["changed"]) == (3000, 25, True)
    # The device reads the file when it starts.
    assert body["restart_required"] is True
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
    lab.started_long_ago()
    body = lab.call({**CONFIRM, "bitrate_kbps": 800, "fps": 15})
    assert body["changed"] is False and body["restart_required"] is False
    assert not lab.backup.exists()


@pytest.mark.parametrize("payload", [
    {"bitrate_kbps": 299}, {"bitrate_kbps": 3001}, {"fps": 4}, {"fps": 26},
    {"bitrate_kbps": 0}, {"fps": -1}, {"fps": "25"}, {},
])
def test_values_outside_the_range_are_refused(lab: Lab, payload: dict) -> None:
    body = lab.call({**CONFIRM, **payload}, status=400)
    assert body == {"ok": False, "error": "camera_quality_out_of_range"}
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
