"""Announcements: the agent plays a sound file over the device speaker."""

from __future__ import annotations

import base64
import io
import json
import os
import secrets
import subprocess
import time
import wave
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from http.client import HTTPConnection
from pathlib import Path

import pytest
from native_build import default_host_agent

from native_agent.test.smoke import (
    HEALTH_READY_TIMEOUT,
    free_tcp_ports,
    free_udp_port,
    send_udp_event,
)

ROOT = Path(__file__).resolve().parents[1]
PATH = "/api/v1/announcements"
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
# Like the device's sound driver, the player's own end sets the sound state to
# off. A player that is killed cannot do that here.
APLAY = """#!/bin/sh
echo $$ > "$LAB/aplay.pid.new" && mv "$LAB/aplay.pid.new" "$LAB/aplay.pid"
echo "aplay $*" >> "$LAB/log"
sleep "$(cat "$LAB/play-seconds")"
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
SWITCH_OFF = ["mixer ZL0_Mute_Rout=on", "mixer TPA2028D1_Volume=0", "mixer ZL0_Rout_Gain_Volume=85"]
# The player was killed, so the sound state is still the one of playing.
SWITCH_OFF_AFTER_KILL = [*SWITCH_OFF, "mixer Zia_Aud_St=0"]
RING = "*8*1#1#4#21*10##"
# Seconds the agent leaves the speaker to the device after a ring, in the tests.
RING_HOLD = 5
CAMERA_VIEW = "*8*1#5#4#21*10##"
# Looks at the device before a switching off gives up and starts again, in the tests.
IDLE_CHECKS = 10
CALL_END = "*8*3#1#4*21##"


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
    return default_host_agent(tmp_path_factory)


def _udp_sockets_on(port: int) -> int:
    """How many sockets of this machine are bound to the UDP port."""

    count = 0
    for table in ("/proc/net/udp", "/proc/net/udp6"):
        try:
            lines = Path(table).read_text().splitlines()[1:]
        except FileNotFoundError:
            continue
        count += sum(1 for line in lines if int(line.split()[1].rsplit(":", 1)[1], 16) == port)
    return count


@dataclass
class Lab:
    port: int
    udp_port: int
    dir: Path
    # The lab's own token: an agent of another test on a reused port refuses it.
    token: str = ""
    process: subprocess.Popen[bytes] | None = None
    start: Callable[[], subprocess.Popen[bytes]] | None = None
    new_ports: Callable[[], None] | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self.token}

    def restart(self) -> None:
        """Start the agent again, as the device does after it ended.

        The ports were free when chosen, but another test running beside this
        one may bind one of them before this agent does. The agent then ends
        or shares its event port; it is started again on other ports.
        """

        assert self.start is not None and self.new_ports is not None
        for _ in range(5):
            log_start = (self.dir / "agent.log").stat().st_size if (self.dir / "agent.log").exists() else 0
            self.process = self.start()
            if self._serving(log_start):
                return
            self.new_ports()
        raise AssertionError("no free ports for the agent after five tries")

    def _serving(self, log_start: int) -> bool:
        assert self.process is not None
        deadline = time.monotonic() + HEALTH_READY_TIMEOUT
        while True:
            if self.process.poll() is not None:
                log = (self.dir / "agent.log").read_bytes()[log_start:].decode(errors="replace")
                assert "bind_failed" in log, log
                return False
            try:
                code, _ = self.request()
            except (OSError, ValueError):
                code = 0
            if code == 200:
                break
            assert time.monotonic() < deadline, f"the agent did not answer on port {self.port}"
            time.sleep(0.05)
        if _udp_sockets_on(self.udp_port) > 1:
            self.process.terminate()
            self.process.wait(timeout=30)
            return False
        return True

    def request(self, action: str = "", payload: dict | None = None) -> tuple[int, dict]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET" if payload is None else "POST", PATH + action,
                         body=None if payload is None else json.dumps(payload), headers=self.headers)
            result = conn.getresponse()
            return result.status, json.loads(result.read())
        finally:
            conn.close()

    def call(self, action: str = "", payload: dict | None = None, *, status: int = 200) -> dict:
        code, body = self.request(action, payload)
        assert code == status, body
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

    def wait_for(self, line: str, seconds: float = 5) -> None:
        deadline = time.monotonic() + seconds
        while not any(line in entry for entry in self.log()):
            assert time.monotonic() < deadline, self.log()
            time.sleep(0.01)

    def result(self) -> str:
        """How the sound ended, once the speaker is switched off again."""

        deadline = time.monotonic() + 10
        while True:
            body = self.call()
            if not body["busy"] and body["result"]:
                return body["result"]
            assert time.monotonic() < deadline, body
            time.sleep(0.02)

    def player_alive(self) -> bool:
        """Whether the player runs; one killed but not yet collected has ended."""

        pid = int((self.dir / "aplay.pid").read_text())
        try:
            os.kill(pid, 0)
            status = Path(f"/proc/{pid}/status").read_text()
        except (ProcessLookupError, FileNotFoundError):
            return False
        return status.split("State:")[1].split()[0] != "Z"

    def wait_player_gone(self, seconds: float = 10) -> None:
        """A killed player ends once the kernel has run it; it plays 30 s otherwise."""

        deadline = time.monotonic() + seconds
        while self.player_alive():
            assert time.monotonic() < deadline, "the player still runs"
            time.sleep(0.01)

    def wait_free(self, seconds: float = 5) -> None:
        deadline = time.monotonic() + seconds
        while self.call()["busy"]:
            assert time.monotonic() < deadline
            time.sleep(0.02)

    def upload_when_free(self, sound: bytes) -> None:
        self.wait_free()
        self.upload(sound)

    def start_long_sound(self) -> None:
        (self.dir / "play-seconds").write_text("30\n")
        self.upload(wav(30))
        self.call("/actions/play", {"volume": 50})
        self.wait_for("aplay -q")


@pytest.fixture
def lab(binary: Path, tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Lab]:
    lab = Lab(0, 0, tmp_path, token=secrets.token_hex(16))

    def new_ports() -> None:
        lab.port, ui_port, own = free_tcp_ports(3)
        lab.udp_port = free_udp_port()
        config = {
            "listen": {"host": "127.0.0.1", "apiPort": lab.port, "uiPort": ui_port},
            "api": {"token": lab.token},
            "openwebnet": {"host": "127.0.0.1", "port": own, "timeoutMs": 100},
            "activations": {"enabled": False, "autoDiscover": False},
            "events": {"udp": {"enabled": getattr(request, "param", True), "group": "239.255.76.67",
                               "port": lab.udp_port}},
            "answeringMachine": {"messages": {"enabled": False}},
            "memos": {"enabled": False}, "systemMetrics": {"enabled": False},
            "video": {"enabled": False}, "displayBridge": {"enabled": False},
            "mqtt": {"enabled": False}, "mdns": {"enabled": False},
        }
        (tmp_path / "config.json").write_text(json.dumps(config))

    new_ports()
    lab.new_ports = new_ports
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
           "C300X_ANNOUNCE_FILE": str(tmp_path / "announce.wav"),
           # Short stand-ins for the minute after a ring and the switch-off's look at the device.
           "C300X_ANNOUNCE_RING_HOLD": str(RING_HOLD), "C300X_ANNOUNCE_IDLE_POLL": "0.2",
           "C300X_ANNOUNCE_IDLE_CHECKS": str(IDLE_CHECKS)}
    with (tmp_path / "agent.log").open("w") as log:
        def start() -> subprocess.Popen[bytes]:
            return subprocess.Popen([str(binary), "--config", str(tmp_path / "config.json")],
                                    cwd=tmp_path, stdout=log, stderr=log, env=env)

        lab.start = start
        try:
            lab.restart()
            yield lab
        finally:
            if lab.process is not None and lab.process.poll() is None:
                lab.process.terminate()
                lab.process.wait(timeout=5)


def switch_on(lab: Lab, gain: int) -> list[str]:
    return [line.format(config=lab.dir / "play.cr", gain=gain) for line in SWITCH_ON]


def test_status_names_the_limit_and_nothing_playing(lab: Lab) -> None:
    assert lab.call() == {"ok": True, "supported": True, "playing": False, "started": False, "busy": False,
                          "result": "", "duration_ms": 0, "max_bytes": 2 * 1024 * 1024}


def test_plays_a_sound_and_switches_the_speaker_on_only_for_it(lab: Lab) -> None:
    sound = wav(1.5)
    lab.upload(sound)
    assert (lab.dir / "announce.wav").read_bytes() == sound

    body = lab.call("/actions/play", {"volume": 100})

    assert (body["playing"], body["busy"], body["duration_ms"]) == (True, True, 1501)
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


def test_says_when_the_device_let_it_have_the_speaker(lab: Lab) -> None:
    lab.start_long_sound()

    deadline = time.monotonic() + 2
    while not (body := lab.call())["started"]:
        assert time.monotonic() < deadline, body
        time.sleep(0.02)
    assert body["playing"] is True
    lab.call("/actions/stop", {})
    assert lab.result() == "stopped"
    assert lab.call()["started"] is False


def test_a_sound_that_cannot_be_switched_on_never_counts_as_started(lab: Lab) -> None:
    tool = lab.dir / "zl-tool"
    tool.write_text("#!/bin/sh\nsleep 1\nexit 1\n")
    tool.chmod(0o755)
    lab.upload(wav())
    lab.call("/actions/play", {"volume": 50})

    seen = []
    while (body := lab.call())["playing"]:
        seen.append(body["started"])
        time.sleep(0.05)
    assert seen and not any(seen)
    assert lab.result() == "sound_path_failed"


def test_a_sound_state_left_behind_with_the_sound_device_closed_does_not_block(lab: Lab) -> None:
    # State 9 without anything playing: left by a switching off that could not finish.
    lab.mixer("Zia_Aud_St", "9")
    lab.upload(wav())
    lab.call("/actions/play", {"volume": 50})

    assert lab.result() == "played"
    assert lab.mixer("Zia_Aud_St") == "0"


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


@pytest.mark.parametrize("frame", [RING, "*8*2#1#4*21##", CAMERA_VIEW], ids=["ring", "answer", "camera view"])
def test_a_door_call_takes_the_speaker_at_once_and_the_device_keeps_it(lab: Lab, frame: str) -> None:
    lab.start_long_sound()

    started = time.monotonic()
    send_udp_event(lab.udp_port, frame)
    while lab.player_alive():
        assert time.monotonic() - started < 1
        time.sleep(0.01)
    # The device sets its own state for the call; from then on the speaker is its.
    lab.mixer("Zia_Aud_St", "7")

    body = lab.call()
    assert (body["playing"], body["busy"], body["result"]) == (False, True, "preempted")
    assert lab.call("/actions/play", {"volume": 50}, status=409)["error"] == "announcement_device_busy"
    # Long after the wait for the device, the call still has the speaker.
    time.sleep(RING_HOLD + 2)
    assert lab.call()["busy"] is True
    assert lab.log()[-1].startswith("aplay -q")
    assert lab.mixer("ZL0_Mute_Rout") == "off"

    # The call is over: the device is idle again and the speaker is switched off.
    lab.mixer("Zia_Aud_St", "0")
    assert lab.result() == "preempted"
    assert lab.log()[-3:] == SWITCH_OFF


def test_after_a_door_frame_without_a_call_the_speaker_is_switched_off(lab: Lab) -> None:
    lab.start_long_sound()

    send_udp_event(lab.udp_port, CAMERA_VIEW)

    started = time.monotonic()
    assert lab.result() == "preempted"
    # The device had three seconds to take its speaker.
    assert time.monotonic() - started > 2.5
    assert lab.log()[-4:] == SWITCH_OFF_AFTER_KILL


def test_a_switching_off_that_gave_up_waiting_for_the_device_starts_again(lab: Lab) -> None:
    lab.start_long_sound()
    # The door call keeps the device busy longer than one switching off waits.
    lab.mixer("Zia_Aud_St", "3")
    send_udp_event(lab.udp_port, CAMERA_VIEW)
    time.sleep(3 + 2 * IDLE_CHECKS * 0.2 + 1)
    assert "mixer ZL0_Mute_Rout=on" not in lab.log()[-4:]

    # The call is over; the sound state of the killed player is left.
    lab.mixer("Zia_Aud_St", "9")
    lab.wait_for("mixer Zia_Aud_St=0", seconds=IDLE_CHECKS * 0.2 + 3)
    assert lab.log()[-4:] == SWITCH_OFF_AFTER_KILL
    assert lab.result() == "preempted"


def test_after_a_ring_the_speaker_is_left_to_the_device_for_its_pauses(lab: Lab) -> None:
    lab.start_long_sound()
    send_udp_event(lab.udp_port, RING)
    started = time.monotonic()
    while lab.player_alive():
        time.sleep(0.01)

    # In a pause of the ring tone the device is idle for a moment.
    time.sleep(RING_HOLD - 1)
    assert lab.call()["busy"] is True
    assert lab.log()[-1].startswith("aplay -q")

    assert lab.result() == "preempted"
    assert time.monotonic() - started > RING_HOLD
    assert lab.log()[-4:] == SWITCH_OFF_AFTER_KILL


def test_no_sound_is_taken_for_a_while_after_a_ring(lab: Lab) -> None:
    lab.upload(wav())
    send_udp_event(lab.udp_port, RING)
    # The agent hears the frame at once; the pause only orders it before the request.
    time.sleep(0.3)

    assert lab.call("/actions/play", {"volume": 50}, status=409)["error"] == "announcement_device_busy"
    assert lab.call("/audio", {"offset": 0, "data": "AAAA"}, status=409)["error"] == "announcement_device_busy"
    assert lab.log() == []

    # An end frame does not end the hold early: the hold starts again with it.
    send_udp_event(lab.udp_port, CALL_END)
    time.sleep(0.3)
    assert lab.call("/actions/play", {"volume": 50}, status=409)["error"] == "announcement_device_busy"

    time.sleep(RING_HOLD + 1)
    lab.call("/actions/play", {"volume": 50})
    assert lab.result() == "played"


def test_the_frames_of_a_rings_call_keep_the_speaker_the_devices(lab: Lab) -> None:
    lab.upload(wav())
    send_udp_event(lab.udp_port, RING)
    # The answering machine starts after the ring, a light is switched: only
    # the first belongs to the call and holds the speaker longer.
    time.sleep(RING_HOLD - 3)
    answering = time.monotonic()
    send_udp_event(lab.udp_port, "*8*80#6#2*11##")
    time.sleep(2.5)
    light = time.monotonic()
    send_udp_event(lab.udp_port, "*8*20*20##")

    # Ask until the agent takes the sound and bound that moment by the frames'
    # own times, so a slow runner shifts the moment but not the verdict.
    while True:
        status, body = lab.request("/actions/play", {"volume": 50})
        taken = time.monotonic()
        if status != 409:
            break
        assert body["error"] == "announcement_device_busy"
        assert taken < light + RING_HOLD + 2, "the speaker never became free"
        time.sleep(0.05)
    assert status == 200, body
    # The hold the answering machine started again, not the ring's own, which
    # ended 2 s earlier (1 ms for the agent's whole-millisecond clock) ...
    assert taken > answering + RING_HOLD - 0.01
    # ... and not one the light would have started.
    assert taken < light + RING_HOLD - 0.01
    assert lab.result() == "played"


def test_a_frame_of_the_call_moves_a_waiting_switching_off(lab: Lab) -> None:
    lab.start_long_sound()
    send_udp_event(lab.udp_port, RING)
    rang = time.monotonic()
    while lab.player_alive():
        time.sleep(0.01)
    time.sleep(RING_HOLD - 1.5)
    # The answering machine starts while the switching off sleeps.
    send_udp_event(lab.udp_port, "*8*80#6#2*11##")

    assert lab.result() == "preempted"
    assert time.monotonic() - rang > 2 * RING_HOLD - 1.5
    assert lab.log()[-4:] == SWITCH_OFF_AFTER_KILL
    assert lab.log().count("mixer ZL0_Mute_Rout=on") == 1


def test_a_restarted_agent_keeps_the_hold_of_a_ring(lab: Lab) -> None:
    send_udp_event(lab.udp_port, RING)
    time.sleep(0.3)
    assert lab.process is not None
    lab.process.terminate()
    lab.process.wait(timeout=5)
    restarted = time.monotonic()
    lab.restart()

    assert lab.call("/actions/play", {"volume": 50}, status=409)["error"] == "announcement_device_busy"
    lab.wait_for("mixer ZL0_Mute_Rout=on", seconds=RING_HOLD + 5)
    # The whole hold again: the new agent does not know when the ring was.
    assert time.monotonic() - restarted > RING_HOLD
    lab.upload_when_free(wav())
    lab.call("/actions/play", {"volume": 50})
    assert lab.result() == "played"


def test_frames_of_a_call_without_a_ring_start_no_hold(lab: Lab) -> None:
    lab.upload(wav())
    send_udp_event(lab.udp_port, "*8*80#6#2*11##")
    send_udp_event(lab.udp_port, CALL_END)
    time.sleep(0.3)

    lab.call("/actions/play", {"volume": 50})
    assert lab.result() == "played"


def test_a_device_without_the_sound_tools_is_not_touched_after_a_ring(lab: Lab) -> None:
    (lab.dir / "zl-tool").unlink()
    send_udp_event(lab.udp_port, RING)
    time.sleep(0.3)
    assert lab.process is not None
    lab.process.terminate()
    lab.process.wait(timeout=5)
    lab.restart()

    time.sleep(RING_HOLD + 3)
    assert lab.log() == []


def test_an_agent_that_ends_after_a_ring_still_switches_the_speaker_off(lab: Lab) -> None:
    lab.start_long_sound()
    send_udp_event(lab.udp_port, RING)
    while lab.player_alive():
        time.sleep(0.01)

    assert lab.process is not None
    lab.process.terminate()
    lab.process.wait(timeout=5)

    lab.wait_for("mixer Zia_Aud_St=0", seconds=RING_HOLD + 5)
    assert lab.log()[-4:] == SWITCH_OFF_AFTER_KILL


def test_a_stop_right_after_a_door_frame_still_leaves_the_speaker_to_the_device(lab: Lab) -> None:
    lab.start_long_sound()

    send_udp_event(lab.udp_port, CAMERA_VIEW)
    lab.call("/actions/stop", {})

    assert lab.result() == "preempted"


@pytest.mark.parametrize("frame", ["*1*1*21##", "*8*19*20##", "*8*20*20##", "*8*21*16##", "*8*91##",
                                   CALL_END, "*7*0*##", "*7*300#127#0#0#1#5#2*##", "*7*301#127#0#0#1##"])
def test_locks_lights_and_the_end_of_a_call_do_not_interrupt(lab: Lab, frame: str) -> None:
    (lab.dir / "play-seconds").write_text("1\n")
    lab.upload(wav(1))
    lab.call("/actions/play", {"volume": 50})
    lab.wait_for("aplay -q")

    send_udp_event(lab.udp_port, frame)

    assert lab.result() == "played"


def test_stop_ends_the_sound_and_switches_the_speaker_off(lab: Lab) -> None:
    lab.start_long_sound()

    lab.call("/actions/stop", {})

    assert lab.result() == "stopped"
    lab.wait_player_gone()
    assert lab.log()[-4:] == SWITCH_OFF_AFTER_KILL


def test_a_failing_player_is_reported_and_the_speaker_is_off_again(lab: Lab) -> None:
    (lab.dir / "play-exit").write_text("1\n")
    lab.upload(wav())
    lab.call("/actions/play", {"volume": 50})

    assert lab.result() == "play_failed"
    assert lab.log()[-3:] == SWITCH_OFF


def test_a_second_sound_is_refused_while_one_plays(lab: Lab) -> None:
    lab.start_long_sound()

    assert lab.call("/actions/play", {"volume": 50}, status=409)["error"] == "announcement_busy"
    assert lab.call("/audio", {"offset": 0, "data": "AAAA"}, status=409)["error"] == "announcement_busy"
    lab.call("/actions/stop", {})
    assert lab.result() == "stopped"


def test_an_agent_that_ends_while_playing_switches_the_speaker_off(lab: Lab) -> None:
    lab.start_long_sound()

    assert lab.process is not None
    lab.process.terminate()
    lab.process.wait(timeout=5)

    lab.wait_player_gone()
    lab.wait_for("mixer Zia_Aud_St=0")
    assert lab.log()[-4:] == SWITCH_OFF_AFTER_KILL
    assert not (lab.dir / "announce.wav").exists()


def test_a_restarted_agent_ends_the_sound_of_one_that_was_killed(lab: Lab) -> None:
    lab.start_long_sound()

    assert lab.process is not None
    lab.process.kill()
    lab.process.wait(timeout=5)
    assert lab.player_alive()
    lab.restart()

    lab.wait_player_gone()
    # What the old agent knew is gone: the new one acts as after a door frame.
    assert lab.call("/actions/play", {"volume": 50}, status=409)["error"] == "announcement_device_busy"
    lab.wait_for("mixer Zia_Aud_St=0", seconds=RING_HOLD + 5)
    assert lab.log()[-3:] == ["mixer ZL0_Mute_Rout=on", "mixer TPA2028D1_Volume=0", "mixer Zia_Aud_St=0"]
    # The last mixer call has written its line; the agent is free once it has collected that call.
    lab.wait_free(30)


def test_a_second_agent_leaves_the_sound_of_the_running_one_alone(lab: Lab) -> None:
    lab.start_long_sound()

    assert lab.start is not None
    second = lab.start()
    # The API port is taken: it ends without having touched anything.
    assert second.wait(timeout=10) == 2

    assert lab.player_alive()
    time.sleep(RING_HOLD + 2)
    assert lab.player_alive()
    assert "mixer ZL0_Mute_Rout=on" not in lab.log()
    lab.call("/actions/stop", {})
    assert lab.result() == "stopped"


def test_a_second_agent_leaves_the_upload_of_the_running_one_alone(lab: Lab) -> None:
    lab.upload(wav())

    assert lab.start is not None
    assert lab.start().wait(timeout=10) == 2

    lab.call("/actions/play", {"volume": 50})
    assert lab.result() == "played"


def test_a_sound_that_outlived_a_killed_agent_is_switched_off_by_the_next(lab: Lab) -> None:
    (lab.dir / "play-seconds").write_text("1\n")
    lab.upload(wav(1))
    lab.call("/actions/play", {"volume": 50})
    lab.wait_for("aplay -q")
    assert lab.process is not None
    lab.process.kill()
    lab.process.wait(timeout=5)
    # Nobody is there when the player ends by itself: the speaker stays on.
    while lab.player_alive():
        time.sleep(0.01)
    time.sleep(0.3)
    assert lab.mixer("ZL0_Mute_Rout") == "off"

    restarted = time.monotonic()
    lab.restart()

    assert lab.call("/actions/play", {"volume": 50}, status=409)["error"] == "announcement_device_busy"
    lab.wait_for("mixer TPA2028D1_Volume=0", seconds=RING_HOLD + 5)
    assert time.monotonic() - restarted > RING_HOLD
    assert lab.mixer("ZL0_Mute_Rout") == "on"


def test_a_sound_uploaded_to_a_killed_agent_is_not_played(lab: Lab) -> None:
    lab.upload(wav())
    assert lab.process is not None
    lab.process.kill()
    lab.process.wait(timeout=5)
    lab.restart()

    lab.wait_for("mixer TPA2028D1_Volume=0", seconds=RING_HOLD + 5)
    lab.wait_free()
    assert lab.call("/actions/play", {"volume": 50}, status=400)["error"] == "announcement_invalid_audio"


def test_a_gain_already_set_back_is_not_written_again(lab: Lab) -> None:
    lab.upload(wav())
    lab.call("/actions/play", {"volume": 50})
    assert lab.result() == "played"
    # The device's software has set another gain since.
    lab.mixer("ZL0_Rout_Gain_Volume", "60")

    send_udp_event(lab.udp_port, RING)
    time.sleep(0.3)
    assert lab.process is not None
    lab.process.terminate()
    lab.process.wait(timeout=5)
    lab.restart()
    deadline = time.monotonic() + RING_HOLD + 5
    while lab.log().count("mixer TPA2028D1_Volume=0") < 2:
        assert time.monotonic() < deadline, lab.log()
        time.sleep(0.05)
    lab.wait_free()

    assert lab.mixer("ZL0_Rout_Gain_Volume") == "60"


def test_a_sound_uploaded_before_a_restart_is_not_played(lab: Lab) -> None:
    lab.upload(wav())
    assert lab.process is not None
    lab.process.terminate()
    lab.process.wait(timeout=5)
    lab.restart()

    assert lab.call("/actions/play", {"volume": 50}, status=400)["error"] == "announcement_invalid_audio"
    assert lab.log() == []


def test_a_restarted_agent_takes_over_the_switching_off_of_the_one_before(lab: Lab) -> None:
    lab.start_long_sound()
    send_udp_event(lab.udp_port, CAMERA_VIEW)
    while lab.player_alive():
        time.sleep(0.01)
    time.sleep(0.5)

    assert lab.process is not None
    lab.process.terminate()
    lab.process.wait(timeout=5)
    lab.restart()

    assert lab.call("/actions/play", {"volume": 50}, status=409)["error"] == "announcement_device_busy"
    lab.wait_for("mixer Zia_Aud_St=0", seconds=RING_HOLD + 5)
    time.sleep(1)
    # Switched off once, by the new agent, with the gain from before the sound.
    assert lab.log()[-4:] == SWITCH_OFF_AFTER_KILL
    assert lab.log().count("mixer ZL0_Mute_Rout=on") == 1


def _chunk(name: bytes, size: int, payload: bytes = b"") -> bytes:
    return name + size.to_bytes(4, "little") + payload


# Chunk sizes near 4 GiB wrapped the 32-bit position on the device.
WRAPPING = b"RIFF" + (28).to_bytes(4, "little") + b"WAVE" + _chunk(b"LIST", 0xFFFFFFF8) + b"\0" * 8


@pytest.mark.parametrize("sound", [wav(rate=16000), wav()[:20], b"no sound at all, only text" * 4,
                                   wav()[:-200], WRAPPING],
                         ids=["16 kHz", "cut header", "no wav", "cut data", "wrapping chunk size"])
def test_refuses_a_sound_the_device_cannot_play(lab: Lab, sound: bytes) -> None:
    lab.upload(sound)

    assert lab.call("/actions/play", {"volume": 50}, status=400)["error"] == "announcement_invalid_audio"
    assert lab.log() == []


def test_plays_stereo_and_a_sound_with_a_chunk_before_its_data(lab: Lab) -> None:
    sound = wav(channels=2)
    info = _chunk(b"LIST", 5, b"INFO!") + b"\0"
    lab.upload(sound[:36] + info + sound[36:])

    assert lab.call("/actions/play", {"volume": 50})["duration_ms"] == 201
    assert lab.result() == "played"


def test_refuses_pieces_out_of_order_a_bad_volume_and_cut_base64(lab: Lab) -> None:
    piece = base64.b64encode(b"x" * 100).decode()
    lab.call("/audio", {"offset": 0, "data": piece})

    assert lab.call("/audio", {"offset": 50, "data": piece}, status=400)["error"] == "announcement_invalid_audio"
    assert lab.call("/audio", {"offset": 100, "data": "not base64!"},
                    status=400)["error"] == "announcement_invalid_audio"
    # The shared decoder stops at some characters; such a piece is not stored cut.
    assert lab.call("/audio", {"offset": 100, "data": "QUJD;QUJD"},
                    status=400)["error"] == "announcement_invalid_audio"
    assert (lab.dir / "announce.wav").stat().st_size == 100
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


def test_does_not_append_to_a_file_with_a_second_name(lab: Lab) -> None:
    lab.call("/audio", {"offset": 0, "data": base64.b64encode(b"x" * 4).decode()})
    target = lab.dir / "victim"
    target.write_text("keep")
    (lab.dir / "announce.wav").unlink()
    os.link(target, lab.dir / "announce.wav")

    assert lab.call("/audio", {"offset": 4, "data": "AAAA"}, status=500)["error"] == "announcement_write_failed"
    assert target.read_text() == "keep"


def test_a_device_without_the_sound_tools_offers_nothing(lab: Lab) -> None:
    (lab.dir / "zl-tool").unlink()

    assert lab.call()["supported"] is False
    assert lab.call("/actions/play", {"volume": 50}, status=409)["error"] == "announcement_unsupported"
    conn = HTTPConnection("127.0.0.1", lab.port, timeout=10)
    conn.request("GET", "/api/v1/capabilities", headers=lab.headers)
    assert json.loads(conn.getresponse().read())["capabilities"]["announcements"] == {"supported": False}
    conn.close()


@pytest.mark.parametrize("lab", [False], indirect=True, ids=["without door events"])
def test_without_door_events_nothing_is_offered(lab: Lab) -> None:
    # A sound could not give way to a door call.
    assert lab.call()["supported"] is False
    assert lab.call("/actions/play", {"volume": 50}, status=409)["error"] == "announcement_unsupported"
