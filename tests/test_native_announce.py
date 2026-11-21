"""Announcements: the agent plays a sound file over the device speaker."""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import time
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from http.client import HTTPConnection
from pathlib import Path

import pytest

from native_agent.test.smoke import (
    TOKEN,
    free_tcp_ports,
    free_udp_port,
    send_udp_event,
    wait_for_health,
)

ROOT = Path(__file__).resolve().parents[1]
PATH = "/api/v1/announcements"
HEADERS = {"Authorization": "Bearer " + TOKEN}
# Stand-ins for the device's sound tools: the mixer keeps each control in a
# file, and every call is written to one log in order.
AMIXER = """#!/bin/sh
[ "$1" = -q ] && shift
name=$(printf %s "$2" | sed "s/^name='//; s/'$//; s/ /_/g")
if [ "$1" = cget ]; then
    echo "numid=1,iface=MIXER,name='x'"; echo "  : values=$(cat "$LAB/mixer/$name")"
else
    [ -f "$LAB/mixer/$name" ] || exit 1
    echo "$3" > "$LAB/mixer/$name"; echo "mixer $name=$3" >> "$LAB/log"
fi
"""
# Like the device's sound driver, the player's end sets the sound state to off.
APLAY = """#!/bin/sh
echo "aplay $*" >> "$LAB/log"
trap 'echo "aplay killed" >> "$LAB/log"; echo 0 > "$LAB/mixer/Zia_Aud_St"; exit 143' TERM
sleep "$(cat "$LAB/play-seconds")" &
wait $!
echo 0 > "$LAB/mixer/Zia_Aud_St"
exit "$(cat "$LAB/play-exit")"
"""
ZL_TOOL = """#!/bin/sh
echo "chip $*" >> "$LAB/log"
"""
SWITCH_ON = [
    "mixer Zia_Aud_St=9",
    "chip DOWNLOAD_CR {config} NOT_SAVE NOT_FORCE",
    "mixer ZL0_Mute_Rout=off",
    "mixer ZL0_Rout_Gain_Volume={gain}",
    "mixer TPA2028D1_Volume=9",
]
SWITCH_OFF = ["mixer ZL0_Mute_Rout=on", "mixer TPA2028D1_Volume=0", "mixer ZL0_Rout_Gain_Volume=85",
              "mixer Zia_Aud_St=0"]


def wav(seconds: float = 0.2, *, rate: int = 8000, channels: int = 1) -> bytes:
    data = io.BytesIO()
    with wave.open(data, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\0\0" * channels * int(rate * seconds))
    return data.getvalue()


@pytest.fixture(scope="module")
def binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build = tmp_path_factory.mktemp("announce-build")
    subprocess.run(["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}", "-j2", "all"],
                   check=True, capture_output=True, text=True)
    return build / "host/c300x-agent-native"


@dataclass
class Lab:
    port: int
    udp_port: int
    dir: Path

    def call(self, action: str = "", payload: dict | None = None, *, status: int = 200) -> dict:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET" if payload is None else "POST", PATH + action,
                         body=None if payload is None else json.dumps(payload), headers=HEADERS)
            result = conn.getresponse()
            body = json.loads(result.read())
        finally:
            conn.close()
        assert result.status == status, body
        return body

    def upload(self, sound: bytes, *, piece: int = 4500) -> None:
        for offset in range(0, len(sound), piece):
            self.call("/audio", {"offset": offset,
                                 "data": base64.b64encode(sound[offset:offset + piece]).decode()})

    def log(self) -> list[str]:
        path = self.dir / "log"
        return path.read_text().splitlines() if path.exists() else []

    def mixer(self, name: str, value: str | None = None) -> str:
        path = self.dir / "mixer" / name
        if value is not None:
            path.write_text(value + "\n")
        return path.read_text().strip()

    def wait_for(self, line: str) -> None:
        deadline = time.monotonic() + 5
        while not any(line in entry for entry in self.log()):
            assert time.monotonic() < deadline, self.log()
            time.sleep(0.01)

    def result(self) -> str:
        deadline = time.monotonic() + 8
        while True:
            body = self.call()
            if not body["playing"] and body["result"]:
                return body["result"]
            assert time.monotonic() < deadline, body
            time.sleep(0.02)


@pytest.fixture
def lab(binary: Path, tmp_path: Path) -> Iterator[Lab]:
    port, ui_port, own = free_tcp_ports(3)
    udp_port = free_udp_port()
    config = {
        "listen": {"host": "127.0.0.1", "apiPort": port, "uiPort": ui_port},
        "api": {"token": TOKEN},
        "openwebnet": {"host": "127.0.0.1", "port": own, "timeoutMs": 100},
        "activations": {"enabled": False, "autoDiscover": False},
        "events": {"udp": {"enabled": True, "group": "239.255.76.67", "port": udp_port}},
        "answeringMachine": {"messages": {"enabled": False}},
        "memos": {"enabled": False}, "systemMetrics": {"enabled": False},
        "video": {"enabled": False}, "displayBridge": {"enabled": False},
        "mqtt": {"enabled": False}, "mdns": {"enabled": False},
    }
    (tmp_path / "config.json").write_text(json.dumps(config))
    (tmp_path / "mixer").mkdir()
    for name, value in (("Zia_Aud_St", "0"), ("ZL0_Mute_Rout", "on"), ("ZL0_Rout_Gain_Volume", "85"),
                        ("TPA2028D1_Volume", "0")):
        (tmp_path / "mixer" / name).write_text(value + "\n")
    for name, text in (("amixer", AMIXER), ("aplay", APLAY), ("zl-tool", ZL_TOOL)):
        (tmp_path / name).write_text(text)
        (tmp_path / name).chmod(0o700)
    (tmp_path / "play.cr").write_text("config\n")
    (tmp_path / "pcm-status").write_text("closed\n")
    (tmp_path / "play-seconds").write_text("0\n")
    (tmp_path / "play-exit").write_text("0\n")
    env = {**os.environ, "LAB": str(tmp_path), "C300X_AMIXER": str(tmp_path / "amixer"),
           "C300X_APLAY": str(tmp_path / "aplay"), "C300X_ZL_TOOL": str(tmp_path / "zl-tool"),
           "C300X_ZL_PLAY_CONFIG": str(tmp_path / "play.cr"),
           "C300X_PCM_STATUS": str(tmp_path / "pcm-status"),
           "C300X_ANNOUNCE_FILE": str(tmp_path / "announce.wav")}
    with (tmp_path / "agent.log").open("w") as log:
        process = subprocess.Popen([str(binary), "--config", str(tmp_path / "config.json")],
                                   cwd=tmp_path, stdout=log, stderr=log, env=env)
        try:
            wait_for_health(port)
            yield Lab(port, udp_port, tmp_path)
        finally:
            process.terminate()
            process.wait(timeout=5)


def switch_on(lab: Lab, gain: int) -> list[str]:
    return [line.format(config=lab.dir / "play.cr", gain=gain) for line in SWITCH_ON]


def test_status_names_the_limit_and_nothing_playing(lab: Lab) -> None:
    assert lab.call() == {"ok": True, "supported": True, "playing": False, "result": "",
                          "duration_ms": 0, "max_bytes": 2 * 1024 * 1024}


def test_plays_a_sound_and_switches_the_speaker_on_only_for_it(lab: Lab) -> None:
    sound = wav(1.5)
    lab.upload(sound)
    assert (lab.dir / "announce.wav").read_bytes() == sound

    body = lab.call("/actions/play", {"volume": 100})

    assert (body["playing"], body["duration_ms"]) == (True, 1501)
    assert lab.result() == "played"
    # The device's own gain for full volume, its chip configuration only in
    # RAM, and a stop of its own one second after the sound's length.
    assert lab.log() == [*switch_on(lab, 74),
                         f"aplay -q -D plughw:0,0 -d 3 {lab.dir / 'announce.wav'}", *SWITCH_OFF]
    assert not (lab.dir / "announce.wav").exists()


def test_volume_follows_the_devices_own_table(lab: Lab) -> None:
    lab.upload(wav())
    lab.call("/actions/play", {"volume": 10})
    assert lab.result() == "played"
    assert "mixer ZL0_Rout_Gain_Volume=26" in lab.log()


@pytest.mark.parametrize("busy", ["state", "sound-device"])
def test_does_not_touch_a_device_that_is_using_its_speaker(lab: Lab, busy: str) -> None:
    if busy == "state":
        lab.mixer("Zia_Aud_St", "7")
    else:
        (lab.dir / "pcm-status").write_text("state: RUNNING\n")
    lab.upload(wav())
    lab.call("/actions/play", {"volume": 50})

    assert lab.result() == "device_busy"
    assert lab.log() == []


def test_a_door_call_takes_the_speaker_at_once_and_nothing_is_switched_back(lab: Lab) -> None:
    (lab.dir / "play-seconds").write_text("30\n")
    lab.upload(wav(30))
    lab.call("/actions/play", {"volume": 50})
    lab.wait_for("aplay -q")

    started = time.monotonic()
    send_udp_event(lab.udp_port, "*8*1#1#4#21*10##")
    lab.wait_for("aplay killed")

    assert time.monotonic() - started < 1
    assert lab.result() == "preempted"
    # The device switches its speaker for the call itself right now.
    assert lab.log()[-1] == "aplay killed"
    assert lab.mixer("ZL0_Mute_Rout") == "off"


def test_a_door_call_keeps_the_ring_state_the_device_had_already_set(lab: Lab) -> None:
    (lab.dir / "play-seconds").write_text("30\n")
    lab.upload(wav(30))
    lab.call("/actions/play", {"volume": 50})
    lab.wait_for("aplay -q")

    # The device was faster: its ring state is set while the sound still plays,
    # and the player's end would set it to off.
    lab.mixer("Zia_Aud_St", "7")
    send_udp_event(lab.udp_port, "*8*1#1#4#21*10##")

    assert lab.result() == "preempted"
    assert lab.log()[-2:] == ["aplay killed", "mixer Zia_Aud_St=7"]
    assert lab.mixer("Zia_Aud_St") == "7"


def test_other_bus_traffic_does_not_interrupt(lab: Lab) -> None:
    (lab.dir / "play-seconds").write_text("1\n")
    lab.upload(wav(1))
    lab.call("/actions/play", {"volume": 50})
    lab.wait_for("aplay -q")

    send_udp_event(lab.udp_port, "*1*1*21##")

    assert lab.result() == "played"


def test_stop_ends_the_sound_and_switches_the_speaker_off(lab: Lab) -> None:
    (lab.dir / "play-seconds").write_text("30\n")
    lab.upload(wav(30))
    lab.call("/actions/play", {"volume": 50})
    lab.wait_for("aplay -q")

    lab.call("/actions/stop", {})

    assert lab.result() == "stopped"
    assert lab.log()[-5:] == ["aplay killed", *SWITCH_OFF]


def test_a_failing_player_is_reported_and_the_speaker_is_off_again(lab: Lab) -> None:
    (lab.dir / "play-exit").write_text("1\n")
    lab.upload(wav())
    lab.call("/actions/play", {"volume": 50})

    assert lab.result() == "play_failed"
    assert lab.log()[-4:] == SWITCH_OFF


def test_a_second_sound_waits_until_the_first_is_over(lab: Lab) -> None:
    (lab.dir / "play-seconds").write_text("30\n")
    lab.upload(wav(30))
    lab.call("/actions/play", {"volume": 50})
    lab.wait_for("aplay -q")

    assert lab.call("/actions/play", {"volume": 50}, status=409)["error"] == "announcement_busy"
    assert lab.call("/audio", {"offset": 0, "data": "AAAA"}, status=409)["error"] == "announcement_busy"
    lab.call("/actions/stop", {})
    assert lab.result() == "stopped"


@pytest.mark.parametrize("sound", [wav(rate=16000), wav()[:20], b"no sound at all, only text" * 4,
                                   wav()[:-200]], ids=["16 kHz", "cut header", "no wav", "cut data"])
def test_refuses_a_sound_the_device_cannot_play(lab: Lab, sound: bytes) -> None:
    lab.upload(sound)

    assert lab.call("/actions/play", {"volume": 50}, status=400)["error"] == "announcement_invalid_audio"
    assert lab.log() == []


def test_refuses_pieces_out_of_order_a_bad_volume_and_too_much(lab: Lab) -> None:
    piece = base64.b64encode(b"x" * 100).decode()
    lab.call("/audio", {"offset": 0, "data": piece})

    assert lab.call("/audio", {"offset": 50, "data": piece}, status=400)["error"] == "announcement_invalid_audio"
    assert lab.call("/audio", {"offset": 2 * 1024 * 1024 - 50, "data": piece},
                    status=400)["error"] == "announcement_invalid_audio"
    assert lab.call("/audio", {"offset": 100, "data": "not base64!"},
                    status=400)["error"] == "announcement_invalid_audio"
    for volume in (0, 101):
        assert lab.call("/actions/play", {"volume": volume},
                        status=400)["error"] == "announcement_invalid_volume"


def test_does_not_write_through_a_link_someone_put_at_the_file_name(lab: Lab) -> None:
    target = lab.dir / "victim"
    target.write_text("keep")
    (lab.dir / "announce.wav").symlink_to(target)

    lab.upload(wav())

    assert target.read_text() == "keep"
    assert not (lab.dir / "announce.wav").is_symlink()


def test_a_device_without_the_sound_tools_offers_nothing(lab: Lab) -> None:
    (lab.dir / "zl-tool").unlink()

    assert lab.call()["supported"] is False
    assert lab.call("/actions/play", {"volume": 50}, status=409)["error"] == "announcement_unsupported"
    conn = HTTPConnection("127.0.0.1", lab.port, timeout=10)
    conn.request("GET", "/api/v1/capabilities", headers=HEADERS)
    assert json.loads(conn.getresponse().read())["capabilities"]["announcements"] == {"supported": False}
    conn.close()
