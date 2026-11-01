"""Exercise GUI-confirmed ringer control through the real native HTTP loop."""

from __future__ import annotations

import json
import socket
import socketserver
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.client import HTTPConnection
from pathlib import Path

import pytest

from native_agent.test.smoke import (
    TOKEN,
    CallbackServer,
    api_get,
    api_post,
    callback_url,
    free_tcp_port,
    free_udp_port,
    managed_tcp_server,
    read_frame,
    send_udp_event,
    wait_for_health,
)

ROOT = Path(__file__).resolve().parents[1]
PATH = "/api/v1/ringer"
GUI_PATH = "/ui/ringer/next"


class DeviceHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        device = self.server
        assert isinstance(device, Device)
        self.request.settimeout(3)
        try:
            self.request.sendall(b"*#*1##")
            if read_frame(self.request) != "*99*0##":
                return
            self.request.sendall(b"*#*1##")
            while frame := read_frame(self.request):
                device.frames.append(frame)
                if frame == "*#8**33##":
                    reply = device.read_reply or f"*#8**33*{0 if device.muted else 1}##"
                elif frame.startswith("*#8**#33*"):
                    if device.write_reply != "*#*0##":
                        device.muted = frame == "*#8**#33*0##"
                    reply = device.write_reply
                elif frame == "*#8**41##":
                    reply = f"*#8**41*{device.volume * 10}##"
                elif frame.startswith("*#8**#41*"):
                    device.volume = int(frame.split("*")[-1][:-2]) // 10
                    reply = "*#*1##"
                else:
                    reply = "*#*0##"
                self.request.sendall(reply.encode())
        except OSError:
            return


class Device(socketserver.ThreadingTCPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), DeviceHandler)
        self.frames: list[str] = []
        self.muted = False
        self.volume = 3
        self.write_reply = "*#*1##"
        self.read_reply: str | None = None


@dataclass
class Lab:
    device: Device
    api_port: int
    ui_port: int
    udp_port: int
    connections: list[HTTPConnection] = field(default_factory=list)

    def request(
        self, port: int, path: str, *, payload: dict | None = None,
        headers: dict | None = None, method: str | None = None,
    ) -> HTTPConnection:
        conn = HTTPConnection("127.0.0.1", port, timeout=8)
        self.connections.append(conn)
        conn.request(method or ("POST" if payload is not None else "GET"), path,
                     body=json.dumps(payload) if payload is not None else None,
                     headers=headers or {})
        return conn

    def post(self, payload: dict) -> HTTPConnection:
        return self.request(self.api_port, PATH, payload=payload,
                            headers={"Authorization": "Bearer " + TOKEN})

    def next(self, completed: str = "", muted: bool = False) -> HTTPConnection:
        path = GUI_PATH
        if completed:
            path += f"?completed={completed}&muted={int(muted)}"
        conn = self.request(self.ui_port, path, headers={"X-C300X-GUI": "ringer-v1"})
        # A later request on the same listener is a barrier, without sleeps.
        api_get(self.ui_port, "/ui/events/status", authorized=False)
        return conn


def response(conn: HTTPConnection, status: int = 200) -> dict:
    result = conn.getresponse()
    body = json.loads(result.read())
    assert result.status == status, body
    return body


@pytest.fixture(scope="module")
def ringer_binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("ringer-build")
    subprocess.run(["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={directory}",
                    "-j2", "all"], check=True, capture_output=True, text=True)
    return directory / "host/c300x-agent-native"


@pytest.fixture
def lab(ringer_binary: Path, tmp_path: Path) -> Iterator[Lab]:
    with managed_tcp_server(Device()) as device, managed_tcp_server(CallbackServer()) as callback:
        lab = Lab(device, free_tcp_port(), free_tcp_port(), free_udp_port())
        config = {
            "listen": {"host": "127.0.0.1", "apiPort": lab.api_port, "uiPort": lab.ui_port},
            "api": {"token": TOKEN},
            "openwebnet": {"host": "127.0.0.1", "port": device.server_address[1], "timeoutMs": 300},
            "maintenance": {"enabled": False},
            "activations": {"enabled": False, "autoDiscover": False},
            "events": {"udp": {"enabled": True, "port": lab.udp_port}},
            "answeringMachine": {"messages": {"enabled": False}},
            "memos": {"enabled": False}, "systemMetrics": {"enabled": False},
            "video": {"enabled": False}, "displayBridge": {"enabled": False},
            "mqtt": {"enabled": False}, "mdns": {"enabled": False},
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        with (tmp_path / "agent.log").open("w") as log:
            process = subprocess.Popen([str(ringer_binary), "--config", str(config_path)],
                                       stdout=log, stderr=log, cwd=tmp_path)
            try:
                wait_for_health(lab.api_port)
                assert api_get(lab.api_port, PATH)["muted"] is False
                api_post(lab.api_port, "/api/v1/events/subscriptions", {
                    "callback_url": callback_url(callback), "token": "ringer-test-token",
                    "events": ["ringer.muted", "ringer.unmuted"],
                }, expected_status=201)
                device.frames.clear()
                yield lab
            finally:
                for conn in lab.connections:
                    conn.close()
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def test_no_gui_never_performs_half_a_write(lab: Lab) -> None:
    assert api_post(lab.api_port, PATH, {"muted": False}, expected_status=503)["error"] == "ringer_gui_unavailable"
    assert lab.device.frames == []


def test_idle_gui_does_not_poll_write_or_wake_the_agent(lab: Lab) -> None:
    lab.next()
    before = api_get(lab.api_port, "/api/v1/diagnostics")
    assert before["ringer_gui_ready"] is True
    assert before["ringer_command_pending"] is False
    assert before["last_poll_timeout_ms"] == -1
    time.sleep(0.15)
    after = api_get(lab.api_port, "/api/v1/diagnostics")
    assert after["loop_iterations"] == before["loop_iterations"] + 1
    assert after["agent_write_count"] == before["agent_write_count"]
    assert lab.device.frames == []


def test_mute_unmute_repeat_and_publish_confirmed_changes(lab: Lab) -> None:
    gui = lab.next()
    for muted in (True, False, True, False):
        post = lab.post({"muted": muted})
        command = response(gui)
        assert command["muted"] is muted
        assert len(command["id"]) == 32
        assert lab.device.frames == []
        # Model the device write made by the existing GUI state transition.
        lab.device.muted = muted
        gui = lab.next(command["id"], muted)
        assert response(post)["muted"] is muted
        assert lab.device.frames == ["*#8**33##"]
        lab.device.frames.clear()
    events = api_get(lab.api_port, "/api/v1/events/recent")["events"]
    assert [event["type"] for event in events] == ["ringer.muted", "ringer.unmuted"] * 2
    send_udp_event(lab.udp_port, "*#8**33*1##")
    assert api_get(lab.api_port, PATH)["muted"] is False
    assert len(api_get(lab.api_port, "/api/v1/events/recent")["events"]) == 4


def test_audio_state_priorities_are_not_overridden_by_raw_write(lab: Lab) -> None:
    gui = lab.next()
    lab.device.muted = True
    post = lab.post({"enabled": True})
    command = response(gui)
    lab.next(command["id"], False)
    assert response(post, 409)["error"] == "ringer_not_applied"
    assert lab.device.frames == ["*#8**33##"]
    assert lab.device.muted is True


@pytest.mark.parametrize("bad_ack", ["missing", "malformed", "wrong_id"])
def test_invalid_ack_cannot_complete_pending_command(lab: Lab, bad_ack: str) -> None:
    gui = lab.next()
    post = lab.post({"muted": True})
    command = response(gui)
    query = {"missing": "", "malformed": "?completed=x&muted=1",
             "wrong_id": "?completed=" + "0" * 32 + "&muted=1"}[bad_ack]
    conn = lab.request(lab.ui_port, GUI_PATH + query, headers={"X-C300X-GUI": "ringer-v1"})
    response(conn, 400 if bad_ack == "malformed" else 409)
    assert lab.device.frames == []
    lab.device.muted = True
    lab.next(command["id"], True)
    assert response(post)["muted"] is True


def test_gui_mismatch_fails_without_device_write(lab: Lab) -> None:
    gui = lab.next()
    post = lab.post({"muted": True})
    command = response(gui)
    lab.next(command["id"], False)
    assert response(post, 502)["error"] == "ringer_gui_not_applied"
    assert lab.device.frames == []


def test_timeout_and_late_ack_do_not_replay_command(lab: Lab) -> None:
    gui = lab.next()
    post = lab.post({"muted": True})
    command = response(gui)
    assert response(post, 504)["error"] == "ringer_gui_timeout"
    assert response(lab.next(command["id"], True), 409)["error"] == "ringer_gui_stale_ack"
    assert lab.device.frames == []
    assert api_post(lab.api_port, PATH, {"muted": False}, expected_status=503)["error"] == "ringer_gui_unavailable"


def test_concurrent_write_cannot_replace_pending_request(lab: Lab) -> None:
    gui = lab.next()
    post = lab.post({"muted": True})
    command = response(gui)
    assert api_post(lab.api_port, PATH, {"muted": False}, expected_status=409)["error"] == "ringer_gui_busy"
    lab.device.muted = True
    lab.next(command["id"], True)
    assert response(post)["muted"] is True


@pytest.mark.parametrize("disconnected", ["gui", "client"])
def test_disconnect_discards_connection_and_pending_work(lab: Lab, disconnected: str) -> None:
    gui = lab.next()
    if disconnected == "gui":
        assert gui.sock is not None
        gui.sock.shutdown(socket.SHUT_RDWR)
        gui.close()
    else:
        post = lab.post({"muted": True})
        command = response(gui)
        assert post.sock is not None
        post.sock.shutdown(socket.SHUT_RDWR)
        post.close()
    api_get(lab.ui_port, "/ui/events/status", authorized=False)
    if disconnected == "client":
        response(lab.next(command["id"], True), 409)
    assert api_post(lab.api_port, PATH, {"muted": False}, expected_status=503)["error"] == "ringer_gui_unavailable"
    assert lab.device.frames == []


def test_duplicate_gui_waiter_cannot_steal_first_connection(lab: Lab) -> None:
    gui = lab.next()
    assert response(lab.next(), 409)["error"] == "ringer_gui_busy"
    post = lab.post({"muted": False})
    command = response(gui)
    lab.next(command["id"], False)
    assert response(post)["muted"] is False


def test_security_boundaries_and_validation(lab: Lab) -> None:
    response(lab.request(lab.api_port, PATH, payload={"muted": False}), 401)
    response(lab.request(lab.ui_port, GUI_PATH), 403)
    response(lab.request(lab.ui_port, GUI_PATH, method="OPTIONS"), 405)
    response(lab.request(lab.ui_port, GUI_PATH, payload={"muted": False}), 405)
    assert api_post(lab.api_port, PATH, {"muted": True, "volume": 11}, expected_status=400)["error"] == "invalid_ringer_volume"
    assert lab.device.frames == []


@pytest.mark.parametrize("reply", ["*#*0##", "*#*1##", "*#8**33*2##"])
def test_unconfirmed_hardware_does_not_report_success(lab: Lab, reply: str) -> None:
    gui = lab.next()
    post = lab.post({"muted": False})
    command = response(gui)
    lab.device.read_reply = reply
    lab.next(command["id"], False)
    assert response(post, 502)["error"] == "ringer_readback_failed"
    assert lab.device.frames == ["*#8**33##"]


def test_volume_only_does_not_require_gui(lab: Lab) -> None:
    assert api_post(lab.api_port, PATH, {"volume": 4})["volume"] == 4
    assert lab.device.frames == ["*#8**#41*40##", "*#8**41##"]


def test_combined_volume_waits_for_gui_confirmation(lab: Lab) -> None:
    gui = lab.next()
    post = lab.post({"muted": True, "volume": 4})
    command = response(gui)
    assert lab.device.frames == []
    lab.device.muted = True
    lab.next(command["id"], True)
    data = response(post)
    assert data["muted"] is True and data["volume"] == 4
