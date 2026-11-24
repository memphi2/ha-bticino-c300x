"""Full native-agent loopback regressions; no device or external HA is contacted."""

import asyncio
import http.client
import json
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import aiohttp
import pytest

from custom_components.bticino_c300x.api import C300XAgentApi
from custom_components.bticino_c300x.executor import async_execute_dashboard_action
from native_agent.test.smoke import (
    TOKEN,
    OpenWebNetServer,
    wait_for_health,
)

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _reserved_listener_ports():
    """Keep both native listener ports bound until just before process startup."""
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as api,
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as ui,
    ):
        api.bind(("127.0.0.1", 0))
        ui.bind(("127.0.0.1", 0))
        yield api.getsockname()[1], ui.getsockname()[1]


@contextmanager
def _mock_servers(callback_handler):
    """Bind the mocks before selecting native ports and always stop their threads."""
    with ExitStack() as cleanup:
        own = cleanup.enter_context(OpenWebNetServer())
        callback = cleanup.enter_context(ThreadingHTTPServer(("127.0.0.1", 0), callback_handler))
        for service in (own, callback):
            thread = threading.Thread(target=service.serve_forever, daemon=True)
            thread.start()
            cleanup.callback(thread.join)
            cleanup.callback(service.shutdown)
        yield own, callback


def request(port, path, data=None, *, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
    try:
        conn.request(
            "POST" if data is not None else "GET",
            path,
            body=json.dumps(data) if data is not None else None,
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
                **(headers or {}),
            },
        )
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()


def target(entity, option=None):
    path = "/homeassistant?domain=c300x&service=toggle&entities=" + quote(
        entity, safe=""
    )
    return path if option is None else path + "&option=" + quote(option, safe="")


@pytest.fixture(scope="module")
def native_binary(tmp_path_factory):
    build = tmp_path_factory.mktemp("display-native-build")
    result = subprocess.run(
        ["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}", "-j2", "all"],
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return build / "host/c300x-agent-native"


@pytest.fixture
def auth_config(request):
    return getattr(request, "param", {})


@pytest.fixture
def lab(native_binary, tmp_path, auth_config):
    received, errors = [], []
    held, release = threading.Event(), threading.Event()

    async def execute(payload):
        async with aiohttp.ClientSession() as session:
            api = C300XAgentApi(session, f"http://127.0.0.1:{api_port}", TOKEN)
            entry = SimpleNamespace(
                entry_id="test",
                data={},
                options={},
                runtime_data=SimpleNamespace(api=api),
            )
            hass = SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *_: None))
            return await async_execute_dashboard_action(
                hass, entry, payload["entity_id"]
            )

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(payload)
            status = 200
            try:
                assert self.headers["X-Bticino-C300X-Secret"] == "synthetic-secret"
                if payload.get("entity_id") == "door_unlock":
                    result = asyncio.run(execute(payload))
                elif payload.get("entity_id") == "switch.held":
                    held.set()
                    assert release.wait(5)
                    result = payload
                elif payload.get("entity_id") == "switch.failure":
                    status, result = 500, {"ok": False}
                else:
                    result = payload
                body = json.dumps(result).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except BrokenPipeError, ConnectionResetError:
                pass
            except Exception as err:
                errors.append(err)
                self.send_error(500)

    with (
        _mock_servers(Callback) as (own, server),
        (tmp_path / "agent.log").open("w") as log,
    ):
        with _reserved_listener_ports() as (api_port, ui_port):
            config = {
                "listen": {"host": "127.0.0.1", "apiPort": api_port, "uiPort": ui_port},
                "api": {"token": TOKEN},
                "openwebnet": {
                    "host": "127.0.0.1",
                    "port": own.server_address[1],
                    "timeoutMs": 100,
                },
                "activations": {"enabled": False, "autoDiscover": False},
                "events": {"udp": {"enabled": False}},
                "answeringMachine": {"messages": {"enabled": False}},
                "memos": {"enabled": False},
                "systemMetrics": {"enabled": False},
                "video": {"enabled": False},
                "maintenance": {"enabled": False},
                "displayBridge": {"enabled": True, "homeAssistant": {"requestTimeoutMs": 3000}},
                "mqtt": {"enabled": False},
                "mdns": {"enabled": False},
            }
            config.update(auth_config)
            config_path = tmp_path / "config.json"
            config_path.write_text(json.dumps(config))
        process = subprocess.Popen(
            [str(native_binary), "--config", str(config_path)], stdout=log, stderr=log
        )
        try:
            wait_for_health(api_port)
            assert (
                request(
                    api_port,
                    "/api/v1/display-bridge",
                    {
                        "enabled": True,
                        "webhook_url": f"http://127.0.0.1:{server.server_address[1]}/display",
                        "shared_secret": "synthetic-secret",
                    },
                )[0]
                == 200
            )
            yield SimpleNamespace(
                api=api_port,
                ui=ui_port,
                own=own,
                received=received,
                held=held,
                release=release,
                config_path=config_path,
                callback=server.server_address[1],
            )
        finally:
            release.set()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    assert not errors


def test_display_door_action_completes_without_callback_deadlock(lab):
    before = request(lab.api, "/api/v1/diagnostics")[1]
    assert not before["home_assistant_connected_this_run"]
    status, body = request(lab.ui, target("door_unlock"))
    assert status == 200 and body["ok"] is True
    after = request(lab.api, "/api/v1/diagnostics")[1]
    assert after["home_assistant_connected_this_run"]
    assert after["home_assistant_last_seen_at"] > 0
    assert lab.own.frames.count("*8*19*20##") == 1
    assert lab.own.frames.count("*8*20*20##") == 1


def test_display_preserves_long_actions_and_rejects_overflow(lab):
    for entity, option in [
        ("light." + "a" * 249 + ":brightness", "50"),
        (
            "notification." + "a" * 64,
            json.dumps({"revision": "b" * 32, "action_id": "x" * 64}),
        ),
        ("select.test:option", "\u00e4" * 200),
        ("select.test:option", "\U0001f4a1" * 255),
        ("select.test:option", "x" * 1024),
        ("select.test:option", "\x01" * 1024),
    ]:
        status, body = request(lab.ui, target(entity, option))
        assert status == 200
        assert body == {
            "type": "dashboard_action",
            "entity_id": entity,
            "option": option,
        }
    count = len(lab.received)
    assert request(lab.ui, "/homeassistant?entities=" + "x" * 4096)[0] == 400
    assert request(lab.ui, target("select.test:option", "x" * 1025))[0] != 200
    assert len(lab.received) == count


def test_slow_display_request_does_not_block_api_or_queue_duplicate(lab):
    assert request(lab.ui, target("switch.failure"))[0] == 502
    assert not request(lab.api, "/api/v1/diagnostics")[1]["home_assistant_connected_this_run"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(request, lab.ui, target("switch.held"))
        try:
            assert lab.held.wait(2)
            assert request(lab.api, "/api/v1/health")[0] == 200
            status, body = request(lab.ui, target("door_unlock"))
            assert status == 503 and body["error"] == "display_command_pending"
            assert not lab.own.frames
        finally:
            lab.release.set()
        assert pending.result(timeout=5)[0] == 200
    assert request(lab.ui, target("switch.failure"))[0] == 502
    assert request(lab.ui, target("switch.ok"))[0] == 200


def test_disconnected_display_client_does_not_leave_request_busy(lab):
    conn = http.client.HTTPConnection("127.0.0.1", lab.ui, timeout=5)
    try:
        conn.request("GET", target("switch.held"))
        assert lab.held.wait(2)
    finally:
        conn.close()
        lab.release.set()
    # A status request can overlap the completion; it may not queue another action.
    for _ in range(50):
        status, _body = request(lab.ui, "/ui/state")
        if status == 200:
            break
        assert status == 503
        threading.Event().wait(0.02)
    assert status == 200
    assert request(lab.ui, target("door_unlock"))[0] == 200
    assert lab.own.frames.count("*8*19*20##") == 1


def test_complete_api_request_arriving_during_unlock_is_not_expired(lab):
    first = http.client.HTTPConnection("127.0.0.1", lab.api, timeout=4)
    second = http.client.HTTPConnection("127.0.0.1", lab.api, timeout=4)
    try:
        first.connect()
        second.connect()
        time.sleep(0.05)  # Both receive slots exist before the slow handler starts.
        first.request("POST", "/api/v1/locks/default/actions/unlock",
                      headers={"Authorization": f"Bearer {TOKEN}"})
        deadline = time.monotonic() + 1
        while "*8*19*20##" not in lab.own.frames:
            assert time.monotonic() < deadline
            time.sleep(0.005)
        # This fd was not readable at poll() return. Its request arrives during
        # the first handler's default 2s hold, longer than the 500ms receive limit.
        second.request("GET", "/api/v1/health")
        response = first.getresponse()
        assert response.status == 200
        response.read()
        response = second.getresponse()
        assert response.status == 200
        response.read()
    finally:
        first.close()
        second.close()


def test_local_status_shows_the_home_assistant_origin_and_last_contact(lab):
    """The Integration tab reads this while Home Assistant cannot be reached."""

    status, body = request(lab.ui, "/ui/status")
    assert status == 200
    assert isinstance(body.pop("firmware"), str)
    assert body == {
        "ok": True,
        "version": (ROOT / "native_agent/VERSION").read_text().strip(),
        "registered": True,
        # Scheme, host and port only: the path carries the webhook id.
        "home_assistant": f"http://127.0.0.1:{lab.callback}",
        "last_contact_age": None,
    }
    text = json.dumps(body)
    assert "/display" not in text and "synthetic-secret" not in text and TOKEN not in text
    assert request(lab.ui, target("switch.ok"))[0] == 200
    age = request(lab.ui, "/ui/status")[1]["last_contact_age"]
    assert isinstance(age, int) and 0 <= age <= 5
    conn = http.client.HTTPConnection("127.0.0.1", lab.ui, timeout=5)
    try:
        conn.request("POST", "/ui/status", body="{}")
        assert conn.getresponse().status == 405
    finally:
        conn.close()
    assert request(lab.api, "/api/v1/display-bridge", {"enabled": False})[0] == 200
    status, body = request(lab.ui, "/ui/status")
    assert status == 200 and body["registered"] is False and body["home_assistant"] == ""

