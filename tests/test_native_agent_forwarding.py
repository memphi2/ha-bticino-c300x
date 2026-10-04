"""Exercise forwarding writes through the native HTTP and OpenWebNet paths."""

from __future__ import annotations

import json
import socketserver
import subprocess
import time
from collections.abc import Iterator
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
FORWARDING_PATH = "/api/v1/smartphone-forwarding"


class ForwardingHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server = self.server
        assert isinstance(server, ForwardingDevice)
        self.request.settimeout(2)
        try:
            self.request.sendall(b"*#*1##")
            if read_frame(self.request) != "*99*0##":
                return
            self.request.sendall(b"*#*1##")
            while frame := read_frame(self.request):
                server.frames.append(frame)
                if frame.startswith("*#8**#37*"):
                    if server.applied_mode is not None:
                        server.mode = server.applied_mode
                    reply = server.write_reply
                elif frame == "*#8**37##":
                    reply = server.readback_reply
                    if reply is None:
                        reply = f"*#8**37*{server.mode}##"
                else:
                    reply = "*#*1##"
                self.request.sendall(reply.encode())
        except OSError:
            # The agent closes failed or malformed command sessions.
            return


class ForwardingDevice(socketserver.ThreadingTCPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), ForwardingHandler)
        self.frames: list[str] = []
        self.mode = 0
        self.applied_mode: int | None = 1
        self.write_reply = "*#*1##"
        self.readback_reply: str | None = None
        self.udp_port = free_udp_port()


@pytest.fixture(scope="module")
def forwarding_binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build_dir = tmp_path_factory.mktemp("forwarding-build")
    subprocess.run(
        [
            "make",
            "-C",
            str(ROOT / "native_agent"),
            f"BUILD_DIR={build_dir}",
            "-j2",
            "all",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return build_dir / "host" / "c300x-agent-native"


@pytest.fixture
def forwarding_agent(
    forwarding_binary: Path, tmp_path: Path
) -> Iterator[tuple[ForwardingDevice, int]]:
    with (
        managed_tcp_server(ForwardingDevice()) as device,
        managed_tcp_server(CallbackServer()) as callback,
    ):
        api_port = free_tcp_port()
        ui_port = free_tcp_port()
        config = {
            "listen": {"host": "127.0.0.1", "apiPort": api_port, "uiPort": ui_port},
            "api": {"token": TOKEN},
            "openwebnet": {
                "host": "127.0.0.1",
                "port": device.server_address[1],
                "timeoutMs": 300,
            },
            "maintenance": {"enabled": False},
            "activations": {"enabled": False, "autoDiscover": False},
            "events": {"udp": {"enabled": True, "port": device.udp_port}},
            "answeringMachine": {"messages": {"enabled": False}},
            "memos": {"enabled": False},
            "systemMetrics": {"enabled": False},
            "video": {"enabled": False},
            "displayBridge": {"enabled": False},
            "mqtt": {"enabled": False},
            "mdns": {"enabled": False},
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        with (tmp_path / "agent.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(forwarding_binary), "--config", str(config_path)],
                stdout=log,
                stderr=log,
                cwd=tmp_path,
            )
            try:
                wait_for_health(api_port)
                assert api_get(api_port, FORWARDING_PATH)["mode"] == "enabled"
                api_post(
                    api_port, "/api/v1/events/subscriptions",
                    {
                        "callback_url": callback_url(callback),
                        "token": "event-token",
                        "events": ["smartphone_forwarding.changed"],
                    },
                    expected_status=201,
                )
                device.frames.clear()
                yield device, api_port
                assert [item["body"] for item in callback.requests] == _forwarding_events(api_port)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


@pytest.mark.parametrize(
    ("payload", "mode", "code", "write_reply", "readback_reply"),
    [
        ({"mode": "homeassistant"}, "homeassistant", 1, "*#*1##", None),
        ({"mode": "enabled"}, "enabled", 0, "*#*1##", None),
        ({"mode": "blocked"}, "blocked", 2, "*#*1##", None),
        ({"enabled": True}, "enabled", 0, "*#*1##", None),
        ({"enabled": False}, "blocked", 2, "*#*1##", None),
        ({"mode": "homeassistant"}, "homeassistant", 1, "*#8**37*1##", None),
        ({"mode": "homeassistant"}, "homeassistant", 1, "*#8**#37*1##", None),
        (
            {"mode": "homeassistant"},
            "homeassistant",
            1,
            "*#*1##*#8**37*0##",
            "*#*1##*#8**37*1##",
        ),
    ],
)
def test_forwarding_success_requires_fresh_readback(
    forwarding_agent: tuple[ForwardingDevice, int],
    payload: dict[str, str | bool],
    mode: str,
    code: int,
    write_reply: str,
    readback_reply: str | None,
) -> None:
    device, port = forwarding_agent
    device.applied_mode = code
    device.write_reply = write_reply
    device.readback_reply = readback_reply
    response = api_post(port, FORWARDING_PATH, payload)
    assert response["ok"] is True
    assert response["error"] is None
    assert response["requested_mode"] == mode
    assert response["mode"] == mode
    assert response["mode_raw"] == f"*#8**37*{code}##"
    assert device.frames == [f"*#8**#37*{code}##", "*#8**37##"]
    assert api_get(port, "/api/v1/state")["state"]["smartphone_forwarding"] == mode
    events = _forwarding_events(port)
    assert [event["data"]["mode"] for event in events] == (
        [] if mode == "enabled" else [mode]
    )


def _forwarding_events(port: int) -> list[dict]:
    return [
        event
        for event in api_get(port, "/api/v1/events/recent")["events"]
        if event["type"] == "smartphone_forwarding.changed"
    ]


def test_confirmed_forwarding_publishes_once_then_suppresses_device_duplicate(
    forwarding_agent: tuple[ForwardingDevice, int],
) -> None:
    device, port = forwarding_agent
    api_post(port, FORWARDING_PATH, {"mode": "homeassistant"})
    assert [event["data"]["mode"] for event in _forwarding_events(port)] == [
        "homeassistant"
    ]
    send_udp_event(device.udp_port, "*#8**37*1##")
    # A second, different notification confirms the UDP queue was consumed.
    send_udp_event(device.udp_port, "*#8**37*2##")
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        events = _forwarding_events(port)
        if len(events) >= 2:
            break
        time.sleep(0.01)
    assert [event["data"]["mode"] for event in events] == ["homeassistant", "blocked"]


@pytest.mark.parametrize("write_reply", ["*#*1##", "*#8**37*1##"])
@pytest.mark.parametrize(
    ("actual_code", "actual_mode"), [(0, "enabled"), (3, "unprovisioned")]
)
def test_forwarding_mismatch_updates_cache_without_claiming_success(
    forwarding_agent: tuple[ForwardingDevice, int],
    write_reply: str,
    actual_code: int,
    actual_mode: str,
) -> None:
    device, port = forwarding_agent
    device.mode = 1
    assert api_get(port, FORWARDING_PATH)["mode"] == "homeassistant"
    device.frames.clear()
    device.applied_mode = actual_code
    device.write_reply = write_reply
    response = api_post(
        port, FORWARDING_PATH, {"mode": "homeassistant"}, expected_status=409
    )
    assert response["ok"] is False
    assert response["error"] == "smartphone_forwarding_not_applied"
    assert response["requested_mode"] == "homeassistant"
    assert response["mode"] == actual_mode
    assert device.frames == ["*#8**#37*1##", "*#8**37##"]
    assert (
        api_get(port, "/api/v1/state")["state"]["smartphone_forwarding"] == actual_mode
    )
    assert [event["data"]["mode"] for event in _forwarding_events(port)] == [actual_mode]


@pytest.mark.parametrize(
    "write_reply", ["*#*0##", "*42##", "*##0##", "*#8**37*1invalid##"]
)
def test_forwarding_rejects_invalid_write_even_when_readback_matches(
    forwarding_agent: tuple[ForwardingDevice, int], write_reply: str
) -> None:
    device, port = forwarding_agent
    device.write_reply = write_reply
    response = api_post(
        port, FORWARDING_PATH, {"mode": "homeassistant"}, expected_status=502
    )
    assert response["ok"] is False
    assert response["error"] == "smartphone_forwarding_write_failed"
    assert response["mode_raw"] == "*#8**37*1##"
    assert (
        api_get(port, "/api/v1/state")["state"]["smartphone_forwarding"]
        == "homeassistant"
    )


@pytest.mark.parametrize(
    "readback_reply", ["*#*0##", "*#8**41*1##", "*#8**37*4##", "*#8**37*1invalid##"]
)
def test_forwarding_rejects_invalid_readback_and_preserves_cache(
    forwarding_agent: tuple[ForwardingDevice, int], readback_reply: str
) -> None:
    device, port = forwarding_agent
    device.readback_reply = readback_reply
    response = api_post(
        port, FORWARDING_PATH, {"mode": "homeassistant"}, expected_status=502
    )
    assert response["ok"] is False
    assert response["error"] == "smartphone_forwarding_readback_failed"
    assert response["mode"] is None
    assert api_get(port, "/api/v1/state")["state"]["smartphone_forwarding"] == "enabled"


@pytest.mark.parametrize("readback_reply", ["", "*#*1##", "*#*1##" * 4])
def test_forwarding_missing_readback_never_reports_success(
    forwarding_agent: tuple[ForwardingDevice, int], readback_reply: str
) -> None:
    device, port = forwarding_agent
    device.readback_reply = readback_reply
    response = api_post(
        port, FORWARDING_PATH, {"mode": "homeassistant"}, expected_status=502
    )
    assert response["ok"] is False
    assert response["error"].startswith("openwebnet_readback_response_")
    assert api_get(port, "/api/v1/state")["state"]["smartphone_forwarding"] == "enabled"


def test_forwarding_unprovisioned_is_not_a_writable_mode(
    forwarding_agent: tuple[ForwardingDevice, int],
) -> None:
    device, port = forwarding_agent
    response = api_post(
        port, FORWARDING_PATH, {"mode": "unprovisioned"}, expected_status=400
    )
    assert response["error"] == "invalid_smartphone_forwarding_mode"
    assert device.frames == []
