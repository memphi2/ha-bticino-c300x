"""Media operations of API requests run beside the HTTP loop, one at a time."""

from __future__ import annotations

import json
import select
import signal
import socket
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.client import HTTPConnection
from pathlib import Path

import pytest
from test_native_openwebnet_offload import PRESS, RELEASE, UNLOCK, Bus

from native_agent.test.smoke import (
    TOKEN,
    api_get,
    free_tcp_ports,
    free_udp_port,
    managed_tcp_server,
    send_udp_event,
    wait_for_health,
)

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
ACTIVATE = "/api/v1/video/doorbell/actions/activate"
STOP = "/api/v1/video/doorbell/actions/stop"
HOME_START = "/api/v1/calls/home/actions/start"
HOME_STOP = "/api/v1/calls/home/actions/stop"


@dataclass
class Lab:
    root: Path
    bus: Bus
    api_port: int
    process: subprocess.Popen[bytes]
    connections: list[HTTPConnection] = field(default_factory=list)

    def post(self, path: str, body: dict | None = None, *, method: str = "POST") -> HTTPConnection:
        conn = HTTPConnection("127.0.0.1", self.api_port, timeout=10)
        self.connections.append(conn)
        conn.request(method, path, body=json.dumps(body or {}) if method == "POST" else None,
                     headers={"Authorization": "Bearer " + TOKEN})
        return conn

    def log(self) -> list[str]:
        path = self.root / "media.log"
        return path.read_text().splitlines() if path.exists() else []

    def hold(self) -> None:
        (self.root / "hold").write_text("")

    def release(self) -> None:
        for name in ("hold", "hold-activate"):
            (self.root / name).unlink(missing_ok=True)

    def held_stop(self, path: str = STOP) -> HTTPConnection:
        self.hold()
        conn = self.post(path)
        self.wait_for("stop begin")
        return conn

    def wait_for(self, line: str, count: int = 1) -> None:
        deadline = time.monotonic() + 5
        while self.log().count(line) < count:
            assert time.monotonic() < deadline, self.log()
            time.sleep(0.01)

    def health_ms(self) -> float:
        started = time.monotonic()
        assert api_get(self.api_port, "/api/v1/health", authorized=False)["ok"] is True
        return (time.monotonic() - started) * 1000


def finish(conn: HTTPConnection, status: int = 200) -> dict:
    result = conn.getresponse()
    body = json.loads(result.read())
    assert result.status == status, body
    return body


@pytest.mark.parametrize("ready", [False, True])
@pytest.mark.parametrize("path", ["/api/v1/calls/doorbell", "/api/v1/calls/doorbell/status"])
def test_call_status_has_peer_readiness(lab: Lab, ready: bool, path: str) -> None:
    if ready:
        (lab.root / "talkback-ready").touch()
    status = api_get(lab.api_port, path)
    assert status["talkback_ready"] is ready


@pytest.fixture(scope="module")
def binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("media-control-build")
    subprocess.run(["make", "-C", str(NATIVE), f"BUILD_DIR={directory}", "-j2", "all"],
                   check=True, capture_output=True, text=True)
    objects = [str(path) for path in sorted((directory / "host").glob("*.o"))
               if path.name != "media_bridge.o"]
    target = directory / "agent-with-held-media"
    subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
                    str(NATIVE / "test/media_bridge_hold_stub.c"), *objects,
                    "-pthread", "-ldl", "-o", str(target)],
                   check=True, capture_output=True, text=True)
    return target


@pytest.fixture
def lab(binary: Path, tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Lab]:
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
            "video": {"enabled": True}, "displayBridge": {"enabled": False},
            "mqtt": {"enabled": False}, "mdns": {"enabled": False},
        }
        config.update(getattr(request, "param", {}))
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        with (tmp_path / "agent.log").open("w") as log:
            process = subprocess.Popen([str(binary), "--config", str(config_path)],
                                       stdout=log, stderr=log, cwd=tmp_path)
            lab = Lab(tmp_path, bus, api, process)
            try:
                wait_for_health(api)
                bus.gate.set()
                bus.frames.clear()
                yield lab
            finally:
                bus.gate.set()
                lab.release()
                for conn in lab.connections:
                    conn.close()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


def test_a_held_stop_leaves_the_api_answering(lab: Lab) -> None:
    stop = lab.held_stop()

    assert max(lab.health_ms() for _ in range(5)) < 500
    assert lab.log() == ["stop begin"]

    lab.release()
    assert finish(stop) == {"ok": True}
    assert lab.log() == ["stop begin", "stop end"]


def test_operations_run_one_after_the_other_and_once_each(lab: Lab) -> None:
    stop = lab.held_stop()
    home = lab.post(HOME_START, {"duration_seconds": 7})
    home_stop = lab.post(HOME_STOP)
    lab.health_ms()
    assert lab.log() == ["stop begin"]

    lab.release()
    assert finish(stop) == {"ok": True}
    assert finish(home) == {"ok": True, "duration_seconds": 7}
    assert finish(home_stop) == {"ok": True}
    assert lab.log() == ["stop begin", "stop end", "home_start 7", "home_stop"]
    lab.health_ms()
    assert lab.log() == ["stop begin", "stop end", "home_start 7", "home_stop"]


EVENT_PORT = free_udp_port()


@pytest.mark.parametrize(
    "lab", [{"events": {"udp": {"enabled": True, "group": "239.255.76.67", "port": EVENT_PORT}}}],
    indirect=True,
)
def test_an_activation_answers_with_its_own_result(lab: Lab) -> None:
    send_udp_event(EVENT_PORT, "*8*1#1#4#21*11##")
    deadline = time.monotonic() + 5
    while (call_id := api_get(lab.api_port, "/api/v1/calls")["current_call_id"]) is None:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    hangup = lab.held_stop(f"/api/v1/calls/{call_id}/actions/hangup")
    activate = lab.post(ACTIVATE, {"audio": False})
    lab.health_ms()

    lab.release()
    assert finish(hangup) == {"ok": True}
    assert finish(activate) == {"ok": True, "audio": False}
    assert lab.log() == ["stop begin", "stop end", "activate"]


def test_a_stop_whose_caller_left_ends_and_frees_the_worker(lab: Lab) -> None:
    stop = lab.held_stop()
    stop.close()
    lab.health_ms()

    lab.release()
    assert finish(lab.post(HOME_STOP)) == {"ok": True}
    assert lab.log() == ["stop begin", "stop end", "home_stop"]


def test_a_waiting_start_is_dropped_when_its_caller_left_but_a_stop_still_runs(lab: Lab) -> None:
    stop = lab.held_stop()
    home = lab.post(HOME_START, {"duration_seconds": 5})
    home_stop = lab.post(HOME_STOP)
    lab.health_ms()
    home.close()
    home_stop.close()
    lab.health_ms()

    lab.release()
    assert finish(stop) == {"ok": True}
    lab.wait_for("home_stop")
    lab.health_ms()
    assert lab.log() == ["stop begin", "stop end", "home_stop"]


def test_a_request_that_finds_no_waiting_place_is_refused(lab: Lab) -> None:
    stop = lab.held_stop()
    waiting = [lab.post(HOME_START, {"duration_seconds": seconds}) for seconds in (1, 2, 3)]
    lab.health_ms()

    assert finish(lab.post(HOME_STOP), 503) == {"ok": False, "error": "media_busy"}
    assert lab.health_ms() < 500
    assert lab.log() == ["stop begin"]

    lab.release()
    assert finish(stop) == {"ok": True}
    for conn in waiting:
        assert finish(conn)["ok"] is True
    assert lab.log() == ["stop begin", "stop end", "home_start 1", "home_start 2", "home_start 3"]


def test_waiting_requests_run_in_the_order_they_arrived(lab: Lab) -> None:
    stop = lab.held_stop()
    # A connection that only holds the client slot in front of the next request.
    idle = socket.create_connection(("127.0.0.1", lab.api_port), timeout=5)
    lab.health_ms()
    home = lab.post(HOME_START, {"duration_seconds": 7})
    lab.health_ms()
    idle.close()
    lab.health_ms()
    home_stop = lab.post(HOME_STOP)
    lab.health_ms()

    lab.release()
    assert finish(stop) == {"ok": True}
    finish(home)
    finish(home_stop)
    assert lab.log() == ["stop begin", "stop end", "home_start 7", "home_stop"]


def test_bus_and_media_requests_together_leave_an_api_slot_free(lab: Lab) -> None:
    lab.bus.hold(PRESS)
    unlock = lab.post(UNLOCK)
    assert lab.bus.seen.wait(5)
    stop = lab.held_stop()
    waiting = [lab.post("/api/v1/answering-machine", method="GET") for _ in range(2)]
    waiting.append(lab.post(HOME_START, {"duration_seconds": 4}))
    lab.health_ms()

    assert finish(lab.post(HOME_STOP), 503)["error"] == "media_busy"
    assert finish(lab.post("/api/v1/answering-machine", method="GET"), 502)["error"] == "openwebnet_busy"
    assert lab.health_ms() < 500

    lab.release()
    lab.bus.gate.set()
    assert finish(stop) == {"ok": True}
    assert finish(unlock)["ok"] is True
    for conn in waiting:
        assert finish(conn)["ok"] is True
    assert lab.log() == ["stop begin", "stop end", "home_start 4"]
    assert lab.bus.frames == [PRESS, RELEASE, "*#8**40##", "*#8**40##"]


def test_shutdown_lets_a_running_operation_end(lab: Lab) -> None:
    lab.held_stop()
    lab.process.send_signal(signal.SIGTERM)
    time.sleep(0.3)
    assert lab.process.poll() is None

    lab.release()
    assert lab.process.wait(timeout=5) == 0
    assert lab.log()[:2] == ["stop begin", "stop end"]


def test_a_door_command_that_lost_its_place_is_not_sent_later(lab: Lab) -> None:
    lab.bus.hold(PRESS)
    first = lab.post(UNLOCK)
    assert lab.bus.seen.wait(5)
    late = lab.post(UNLOCK)
    lab.health_ms()
    late.close()
    stop = lab.held_stop()
    waiting = [lab.post(HOME_STOP), lab.post(HOME_STOP)]
    lab.health_ms()
    # The places are taken; this one gets the place of the caller that left.
    extra = lab.post(HOME_START, {"duration_seconds": 3})
    # Until the one that lost its place is ended, all six client slots are taken.
    time.sleep(0.3)
    lab.health_ms()

    lab.bus.gate.set()
    assert finish(first)["ok"] is True
    lab.health_ms()
    lab.release()
    assert finish(stop) == {"ok": True}
    for conn in waiting:
        assert finish(conn) == {"ok": True}
    assert finish(extra)["ok"] is True
    lab.health_ms()
    assert lab.bus.frames == [PRESS, RELEASE]


def test_a_request_waiting_for_the_media_worker_leaves_the_agent_idle(lab: Lab) -> None:
    stop = lab.held_stop()
    waiting = lab.post(HOME_STOP)
    lab.health_ms()
    stat = Path(f"/proc/{lab.process.pid}/stat").read_text().rsplit(")", 1)[1].split()
    before = int(stat[11]) + int(stat[12])
    time.sleep(1)
    stat = Path(f"/proc/{lab.process.pid}/stat").read_text().rsplit(")", 1)[1].split()
    assert int(stat[11]) + int(stat[12]) - before < 20

    lab.release()
    assert finish(stop) == {"ok": True}
    assert finish(waiting) == {"ok": True}


ADMIN = {"maintenance": {"enabled": True, "adminToken": "maintenance-token"}}


def write_token(lab: Lab, token: str) -> HTTPConnection:
    conn = HTTPConnection("127.0.0.1", lab.api_port, timeout=10)
    lab.connections.append(conn)
    conn.request("POST", "/api/v1/maintenance/auth", body=json.dumps({"apiToken": token}),
                 headers={"Authorization": "Bearer " + TOKEN,
                          "X-Bticino-C300X-Maintenance-Token": "maintenance-token"})
    return conn


@pytest.mark.parametrize("lab", [ADMIN], indirect=True)
def test_a_configuration_write_waits_for_the_media_operation_and_its_answer(lab: Lab) -> None:
    stop = lab.held_stop()
    write = write_token(lab, "another-token-0123456789")
    lab.health_ms()
    assert select.select([write.sock], [], [], 0.3)[0] == []

    lab.release()
    # The stop is answered for what it did, with the token it came with.
    assert finish(stop) == {"ok": True}
    assert write.getresponse().status == 200
    assert lab.post(STOP).getresponse().status == 401


@pytest.mark.parametrize("lab", [ADMIN], indirect=True)
def test_a_held_configuration_write_is_not_applied_when_its_caller_left(lab: Lab) -> None:
    stop = lab.held_stop()
    write = write_token(lab, "another-token-0123456789")
    lab.health_ms()
    write.close()
    lab.health_ms()

    lab.release()
    assert finish(stop) == {"ok": True}
    lab.health_ms()
    assert finish(lab.post(STOP)) == {"ok": True}


@pytest.mark.parametrize("lab", [ADMIN], indirect=True)
def test_a_configuration_write_waits_for_a_media_operation_whose_request_is_over(lab: Lab) -> None:
    (lab.root / "hold-activate").write_text("")
    activate = lab.post(ACTIVATE, {"audio": False})
    lab.wait_for("activate")
    write = write_token(lab, "another-token-0123456789")
    lab.health_ms()
    # A ring ends the activation request early; its operation still runs.
    (lab.root / "ring").write_text("")
    lab.health_ms()
    assert activate.getresponse().status == 200
    assert select.select([write.sock], [], [], 0.5)[0] == []

    (lab.root / "hold-activate").unlink()
    assert write.getresponse().status == 200
