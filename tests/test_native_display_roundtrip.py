"""Full native-agent loopback regressions; no device or external HA is contacted."""

import asyncio
import http.client
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
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
    free_tcp_port,
    wait_for_health,
)

ROOT = Path(__file__).resolve().parents[1]


def request(port, path, data=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
    try:
        conn.request(
            "POST" if data is not None else "GET",
            path,
            body=json.dumps(data) if data is not None else None,
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
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
def lab(native_binary, tmp_path):
    api_port, ui_port = free_tcp_port(), free_tcp_port()
    received, errors = [], []
    held, release = threading.Event(), threading.Event()
    own = OpenWebNetServer()

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

    server = ThreadingHTTPServer(("127.0.0.1", 0), Callback)
    for service in (own, server):
        threading.Thread(target=service.serve_forever, daemon=True).start()
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
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    with (tmp_path / "agent.log").open("w") as log:
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
            )
        finally:
            release.set()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            for service in (server, own):
                service.shutdown()
                service.server_close()
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
