"""OpenWebNet exchanges of API requests run beside the HTTP loop, exactly once."""

from __future__ import annotations

import json
import signal
import socket
import socketserver
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.client import HTTPConnection
from pathlib import Path

import pytest

from native_agent.test.smoke import (
    TOKEN,
    api_get,
    free_tcp_ports,
    managed_tcp_server,
    read_frame,
    wait_for_health,
)

ROOT = Path(__file__).resolve().parents[1]
UNLOCK = "/api/v1/locks/default/actions/unlock"
PRESS = "*8*19*20##"
RELEASE = "*8*20*20##"


class BusHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        bus = self.server
        assert isinstance(bus, Bus)
        self.request.settimeout(10)
        try:
            self.request.sendall(b"*#*1##")
            if read_frame(self.request) != "*99*0##":
                return
            self.request.sendall(b"*#*1##")
            while frame := read_frame(self.request):
                bus.frames.append(frame)
                bus.seen.set()
                if frame in bus.held:
                    assert bus.gate.wait(8)
                if frame == "*#8**33##":
                    reply = "*#8**33*1##"
                elif frame == "*#8**41##":
                    reply = "*#8**41*30##"
                elif frame == "*#8**40##":
                    reply = "*#8**40*0*0##"
                else:
                    reply = "*#*1##"
                self.request.sendall(reply.encode())
        except OSError:
            return


class Bus(socketserver.ThreadingTCPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), BusHandler)
        self.frames: list[str] = []
        self.held: set[str] = set()
        self.gate = threading.Event()
        self.seen = threading.Event()

    def hold(self, *frames: str) -> None:
        self.held = set(frames)
        self.gate.clear()
        self.seen.clear()


@dataclass
class Lab:
    bus: Bus
    api_port: int
    process: subprocess.Popen[bytes]
    connections: list[HTTPConnection] = field(default_factory=list)

    def start(self, path: str, *, post: bool = False) -> HTTPConnection:
        conn = HTTPConnection("127.0.0.1", self.api_port, timeout=10)
        self.connections.append(conn)
        conn.request("POST" if post else "GET", path, body="{}" if post else None,
                     headers={"Authorization": "Bearer " + TOKEN})
        return conn

    def health_ms(self) -> float:
        started = time.monotonic()
        assert api_get(self.api_port, "/api/v1/health", authorized=False)["ok"] is True
        return (time.monotonic() - started) * 1000


def finish(conn: HTTPConnection, status: int = 200) -> dict:
    result = conn.getresponse()
    body = json.loads(result.read())
    assert result.status == status, body
    return body


@pytest.fixture(scope="module")
def binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("openwebnet-offload-build")
    subprocess.run(["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={directory}",
                    "-j2", "all"], check=True, capture_output=True, text=True)
    return directory / "host/c300x-agent-native"


@pytest.fixture
def lab(binary: Path, tmp_path: Path) -> Iterator[Lab]:
    with managed_tcp_server(Bus()) as bus:
        api, ui = free_tcp_ports(2)
        config = {
            "listen": {"host": "127.0.0.1", "apiPort": api, "uiPort": ui},
            "api": {"token": TOKEN},
            "openwebnet": {"host": "127.0.0.1", "port": bus.server_address[1], "timeoutMs": 9000},
            "locks": {"releaseDelayMs": 1, "items": {"default": {"name": "Door", "address": "20"}}},
            "maintenance": {"enabled": False},
            "activations": {"enabled": False, "autoDiscover": False},
            "events": {"udp": {"enabled": False}},
            "answeringMachine": {"messages": {"enabled": False}},
            "memos": {"enabled": False}, "systemMetrics": {"enabled": False},
            "video": {"enabled": False}, "displayBridge": {"enabled": False},
            "mqtt": {"enabled": False}, "mdns": {"enabled": False},
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        with (tmp_path / "agent.log").open("w") as log:
            process = subprocess.Popen([str(binary), "--config", str(config_path)],
                                       stdout=log, stderr=log, cwd=tmp_path)
            lab = Lab(bus, api, process)
            try:
                wait_for_health(api)
                bus.gate.set()
                bus.frames.clear()
                yield lab
            finally:
                bus.gate.set()
                for conn in lab.connections:
                    conn.close()
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def test_a_held_door_command_leaves_the_api_answering(lab: Lab) -> None:
    lab.bus.hold(PRESS)
    unlock = lab.start(UNLOCK, post=True)
    assert lab.bus.seen.wait(5)

    assert max(lab.health_ms() for _ in range(5)) < 500
    assert lab.bus.frames == [PRESS]

    lab.bus.gate.set()
    assert finish(unlock)["ok"] is True
    assert lab.bus.frames == [PRESS, RELEASE]


def test_requests_for_the_bus_run_one_after_the_other_and_once_each(lab: Lab) -> None:
    lab.bus.hold(PRESS)
    unlock = lab.start(UNLOCK, post=True)
    assert lab.bus.seen.wait(5)
    ringer = lab.start("/api/v1/ringer")
    answering = lab.start("/api/v1/answering-machine")
    lab.health_ms()
    assert lab.bus.frames == [PRESS]

    lab.bus.gate.set()
    assert finish(unlock)["ok"] is True
    status = finish(ringer)
    assert (status["muted"], status["volume"]) == (False, 3)
    assert finish(answering)["ok"] is True
    assert sorted(lab.bus.frames) == sorted(
        [PRESS, RELEASE, "*#8**33##", "*#8**41##", "*#8**40##"])
    assert lab.bus.frames[:2] == [PRESS, RELEASE]


def test_a_request_with_two_exchanges_sends_each_once(lab: Lab) -> None:
    lab.bus.hold("*#8**33##", "*#8**41##")
    ringer = lab.start("/api/v1/ringer")
    assert lab.bus.seen.wait(5)
    lab.health_ms()
    lab.bus.gate.set()

    assert finish(ringer)["volume"] == 3
    assert lab.bus.frames == ["*#8**33##", "*#8**41##"]


def test_a_caller_that_left_does_not_repeat_or_block_the_command(lab: Lab) -> None:
    lab.bus.hold(PRESS)
    unlock = lab.start(UNLOCK, post=True)
    assert lab.bus.seen.wait(5)
    unlock.close()
    lab.health_ms()
    lab.bus.gate.set()

    assert finish(lab.start("/api/v1/answering-machine"))["ok"] is True
    assert lab.bus.frames == [PRESS, RELEASE, "*#8**40##"]


def test_a_bus_error_is_reported_as_before(lab: Lab) -> None:
    lab.bus.shutdown()
    lab.bus.server_close()

    body = finish(lab.start(UNLOCK, post=True), 502)
    assert body == {"ok": False, "error": "openwebnet_connect_failed"}
    assert lab.health_ms() < 500


def test_shutdown_lets_a_pressed_lock_be_released(lab: Lab) -> None:
    lab.bus.hold(PRESS)
    lab.start(UNLOCK, post=True)
    assert lab.bus.seen.wait(5)

    lab.process.send_signal(signal.SIGTERM)
    time.sleep(0.2)
    lab.bus.gate.set()

    assert lab.process.wait(timeout=5) == 0
    assert lab.bus.frames == [PRESS, RELEASE]


def test_more_waiting_requests_than_allowed_are_answered_busy(lab: Lab) -> None:
    lab.bus.hold(PRESS)
    unlock = lab.start(UNLOCK, post=True)
    assert lab.bus.seen.wait(5)
    waiting = [lab.start("/api/v1/answering-machine") for _ in range(3)]
    lab.health_ms()

    # One more would start to use up the client slots of the API.
    assert finish(lab.start("/api/v1/answering-machine"), 502) == {
        "ok": False, "error": "openwebnet_busy"}
    assert lab.health_ms() < 500
    assert lab.bus.frames == [PRESS]

    lab.bus.gate.set()
    assert finish(unlock)["ok"] is True
    for conn in waiting:
        assert finish(conn)["ok"] is True
    assert lab.bus.frames == [PRESS, RELEASE, *["*#8**40##"] * 3]


def test_a_waiting_request_whose_caller_left_is_not_run(lab: Lab) -> None:
    lab.bus.hold("*#8**40##")
    first = lab.start("/api/v1/answering-machine")
    assert lab.bus.seen.wait(5)
    late = lab.start(UNLOCK, post=True)
    lab.health_ms()
    late.close()
    lab.health_ms()

    lab.bus.gate.set()
    assert finish(first)["ok"] is True
    assert finish(lab.start("/api/v1/answering-machine"))["ok"] is True
    # The door of a caller who gave up does not open afterwards.
    assert lab.bus.frames == ["*#8**40##", "*#8**40##"]


def test_a_refused_read_does_not_report_the_setting_as_unavailable(lab: Lab) -> None:
    lab.bus.hold(PRESS)
    unlock = lab.start(UNLOCK, post=True)
    assert lab.bus.seen.wait(5)
    waiting = [lab.start("/api/v1/answering-machine") for _ in range(3)]
    lab.health_ms()

    assert finish(lab.start("/api/v1/ringer"), 502) == {"ok": False, "error": "openwebnet_busy"}
    assert finish(lab.start("/api/v1/smartphone-forwarding"), 502)["error"] == "openwebnet_busy"

    lab.bus.gate.set()
    assert finish(unlock)["ok"] is True
    for conn in waiting:
        finish(conn)
    events = api_get(lab.api_port, "/api/v1/events/recent")["events"]
    assert [event["type"] for event in events
            if "ringer" in event["type"] or "forwarding" in event["type"]] == []


def test_waiting_requests_get_the_bus_in_the_order_they_arrived(lab: Lab) -> None:
    lab.bus.hold(PRESS)
    unlock = lab.start(UNLOCK, post=True)
    assert lab.bus.seen.wait(5)
    # A connection that only holds the client slot in front of the next request.
    idle = socket.create_connection(("127.0.0.1", lab.api_port), timeout=5)
    lab.health_ms()
    ringer = lab.start("/api/v1/ringer")
    lab.health_ms()
    idle.close()
    lab.health_ms()
    answering = lab.start("/api/v1/answering-machine")
    lab.health_ms()

    lab.bus.gate.set()
    assert finish(unlock)["ok"] is True
    finish(ringer)
    finish(answering)
    assert lab.bus.frames == [PRESS, RELEASE, "*#8**33##", "*#8**41##", "*#8**40##"]
