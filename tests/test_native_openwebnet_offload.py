"""OpenWebNet exchanges of API requests run beside the HTTP loop, exactly once."""

from __future__ import annotations

import json
import select
import shutil
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

    def start(self, path: str, *, post: bool = False, body: dict | None = None,
              headers: dict | None = None) -> HTTPConnection:
        conn = HTTPConnection("127.0.0.1", self.api_port, timeout=10)
        self.connections.append(conn)
        post = post or body is not None
        conn.request("POST" if post else "GET", path, body=json.dumps(body or {}) if post else None,
                     headers={"Authorization": "Bearer " + TOKEN, **(headers or {})})
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
            "video": {"enabled": False}, "displayBridge": {"enabled": False},
            "mqtt": {"enabled": False}, "mdns": {"enabled": False},
        }
        config.update(getattr(request, "param", {}))
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


def test_waiting_requests_whose_callers_left_give_their_places_to_new_ones(lab: Lab) -> None:
    lab.bus.hold(PRESS)
    unlock = lab.start(UNLOCK, post=True)
    assert lab.bus.seen.wait(5)
    gone = [lab.start("/api/v1/answering-machine") for _ in range(3)]
    lab.health_ms()
    for conn in gone:
        conn.close()
    lab.health_ms()
    ringer = lab.start("/api/v1/ringer")
    lab.health_ms()

    lab.bus.gate.set()
    assert finish(unlock)["ok"] is True
    assert finish(ringer)["volume"] == 3
    lab.health_ms()
    # None of the requests nobody waits for was sent.
    assert "*#8**40##" not in lab.bus.frames


def cpu_seconds(pid: int) -> float:
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return (int(fields[11]) + int(fields[12])) / 100


def test_a_request_waiting_for_the_bus_leaves_the_agent_idle(lab: Lab) -> None:
    lab.bus.hold(PRESS)
    unlock = lab.start(UNLOCK, post=True)
    assert lab.bus.seen.wait(5)
    waiting = lab.start("/api/v1/answering-machine")
    lab.health_ms()
    before = cpu_seconds(lab.process.pid)
    time.sleep(1)
    assert cpu_seconds(lab.process.pid) - before < 0.2

    lab.bus.gate.set()
    assert finish(unlock)["ok"] is True
    assert finish(waiting)["ok"] is True


def test_more_departed_callers_than_places_leave_the_agent_idle_and_its_slots_free(lab: Lab) -> None:
    lab.bus.hold(PRESS)
    unlock = lab.start(UNLOCK, post=True)
    assert lab.bus.seen.wait(5)
    for _ in range(4):
        conn = lab.start("/api/v1/answering-machine")
        lab.health_ms()
        conn.close()
        lab.health_ms()

    lab.bus.gate.set()
    assert finish(unlock)["ok"] is True
    lab.health_ms()
    before = cpu_seconds(lab.process.pid)
    time.sleep(1)
    assert cpu_seconds(lab.process.pid) - before < 0.2
    assert "*#8**40##" not in lab.bus.frames
    # All six client slots of the API are free again.
    waiting = [lab.start("/api/v1/answering-machine") for _ in range(4)]
    for conn in waiting:
        assert finish(conn)["ok"] is True


def test_a_request_with_its_command_out_is_answered_for_that_command(lab: Lab) -> None:
    write = "*#8**#41*40##"
    assert finish(lab.start("/api/v1/ringer"))["volume"] == 3
    lab.bus.hold(write)
    volume = lab.start("/api/v1/ringer", body={"volume": 4})
    assert lab.bus.seen.wait(5)
    # A mute request takes the display meanwhile; before, it came after the volume.
    lab.start("/api/v1/ringer", body={"muted": True})
    lab.health_ms()

    lab.bus.gate.set()
    # This bus always reads back volume 3: the answer is the one for the write,
    # not "the display is busy" from a check made again after the write.
    assert finish(volume, 409)["error"] == "ringer_volume_not_applied"
    assert lab.bus.frames.count(write) == 1


def test_a_maintenance_write_that_is_not_admitted_is_answered_at_once(lab: Lab) -> None:
    lab.bus.hold(PRESS)
    unlock = lab.start(UNLOCK, post=True)
    assert lab.bus.seen.wait(5)
    refused = [lab.start("/api/v1/maintenance/auth", body={}) for _ in range(5)]
    for conn in refused:
        assert conn.getresponse().status in (403, 404)
    assert lab.health_ms() < 500

    lab.bus.gate.set()
    assert finish(unlock)["ok"] is True


@pytest.mark.parametrize(
    "lab", [{"maintenance": {"enabled": True, "adminToken": "maintenance-token"}}], indirect=True)
def test_an_admitted_maintenance_write_waits_for_the_request_on_the_bus(lab: Lab) -> None:
    admin = {"X-Bticino-C300X-Maintenance-Token": "maintenance-token"}
    lab.bus.hold(PRESS)
    unlock = lab.start(UNLOCK, post=True)
    assert lab.bus.seen.wait(5)
    write = lab.start("/api/v1/maintenance/auth", body={}, headers=admin)
    lab.health_ms()
    assert select.select([write.sock], [], [], 0.3)[0] == []
    assert lab.bus.frames == [PRESS]

    lab.bus.gate.set()
    assert finish(unlock)["ok"] is True
    # Answered after the door command, whatever it says to an empty change.
    assert write.getresponse().status in (200, 400)
    assert lab.bus.frames == [PRESS, RELEASE]


STAIR = "/api/v1/stair-light/actions/activate"


@pytest.mark.parametrize(
    "lab", [{"maintenance": {"enabled": True, "adminToken": "maintenance-token"}}], indirect=True)
def test_a_configuration_write_admitted_by_the_admin_token_alone_waits_too(lab: Lab) -> None:
    lab.bus.hold("*8*21*10##")
    stair = lab.start(STAIR, post=True)
    assert lab.bus.seen.wait(5)
    write = lab.start("/api/v1/maintenance/auth", body={"stairLightDefaultAddress": "11"},
                      headers={"X-Bticino-C300X-Maintenance-Token": "maintenance-token",
                               "Authorization": "Bearer wrong"})
    lab.health_ms()
    assert select.select([write.sock], [], [], 0.3)[0] == []

    lab.bus.gate.set()
    assert finish(stair)["address"] == "10"
    assert write.getresponse().status == 200
    lab.health_ms()
    # The request on the bus sent one command, for the address it started with.
    assert [frame for frame in lab.bus.frames if frame.startswith("*8*21*")] == ["*8*21*10##"]


STORES = {
    "memos": {"enabled": True, "textRoot": "memos_text", "voiceRoot": "memos_voice", "watch": True},
    "answeringMachine": {"messages": {"enabled": True, "root": "messages", "watch": True}},
}
DELETES = [
    ("/api/v1/memos/actions/delete", "text/memo_1", "memos_text/memo_1", "*8*94#1#3##"),
    ("/api/v1/answering-machine/messages/actions/delete", "message_1", "messages/message_1",
     "*8*94#1#0##"),
]


@pytest.fixture
def stores(tmp_path: Path) -> Path:
    for entry in ("memos_text/memo_1", "memos_voice", "messages/message_1"):
        (tmp_path / entry).mkdir(parents=True)
    (tmp_path / "memos_text/memo_1/message.txt").write_text("memo\n")
    (tmp_path / "messages/message_1/msg_info.ini").write_text("[Message Information]\nRead=0\n")
    return tmp_path


@pytest.mark.parametrize("lab", [STORES], indirect=True)
@pytest.mark.parametrize(("path", "entry_id", "entry", "command"), DELETES)
def test_a_delete_with_its_command_out_is_answered_for_that_command(
    stores: Path, lab: Lab, path: str, entry_id: str, entry: str, command: str,
) -> None:
    lab.bus.hold(command)
    delete = lab.start(path, body={"id": entry_id})
    assert lab.bus.seen.wait(5)
    # The device removes the entry while the command is out; a pass of the
    # request meanwhile finds it no longer a directory it can open.
    shutil.rmtree(stores / entry)
    (stores / entry).write_text("")
    lab.health_ms()
    (stores / entry).unlink()

    lab.bus.gate.set()
    assert finish(delete)["deleted"] is True
    assert lab.bus.frames.count(command) == 1
