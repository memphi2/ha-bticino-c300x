"""Download backpressure must leave the real agent's event loop responsive."""

from __future__ import annotations

import http.client
import json
import socket
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path

import pytest

from native_agent.test.smoke import (
    TOKEN,
    OpenWebNetServer,
    free_tcp_port,
    managed_tcp_server,
    wait_for_health,
    write_memo,
    write_voicemail_message,
)

ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION = f"Bearer {TOKEN}"


@pytest.fixture(scope="module")
def native_binary(tmp_path_factory):
    build = tmp_path_factory.mktemp("file-transfer-native-build")
    result = subprocess.run(
        ["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}", "-j2", "all"],
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return build / "host/c300x-agent-native"


def request(port, path, *, method="GET"):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.8)
    try:
        connection.request(method, path, headers={"Authorization": AUTHORIZATION})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


@pytest.mark.parametrize("kind", ["video", "voice"])
def test_download_backpressure_capacity_disconnect_and_shutdown(native_binary, tmp_path, kind):
    messages, memos = tmp_path / "messages", tmp_path / "memos"
    write_voicemail_message(messages, "message_1", read=False, unix_time=1710000000)
    write_voicemail_message(messages, "message_2", read=False, unix_time=1710000000)
    write_memo(memos, "message_1", kind="voice", read=False, unix_time=1710000000)
    write_memo(memos, "message_2", kind="voice", read=False, unix_time=1710000000)
    large = (messages if kind == "video" else memos) / "message_1" / (
        "aswm.avi" if kind == "video" else "audio.wav"
    )
    with large.open("wb") as file:
        file.truncate(8 * 1024 * 1024)
    small = large.parent.parent / "message_2" / large.name
    payload = bytes(range(256)) * 256
    small.write_bytes(payload)
    prefix = (
        "/api/v1/answering-machine/messages/" if kind == "video" else "/api/v1/memos/voice/"
    )
    suffix = "/video" if kind == "video" else "/audio"
    api_port, ui_port = free_tcp_port(), free_tcp_port()
    with managed_tcp_server(OpenWebNetServer()) as own:
        config = {
            "listen": {"host": "127.0.0.1", "apiPort": api_port, "uiPort": ui_port},
            "api": {"token": TOKEN},
            "openwebnet": {"host": "127.0.0.1", "port": own.server_address[1], "timeoutMs": 100},
            "activations": {"enabled": False, "autoDiscover": False},
            "events": {"udp": {"enabled": False}},
            "answeringMachine": {"messages": {"enabled": True, "root": str(messages), "watch": False}},
            "memos": {"enabled": True, "voiceRoot": str(memos), "textRoot": str(tmp_path / "text"), "watch": False},
            "systemMetrics": {"enabled": False},
            "video": {"enabled": False},
            "maintenance": {"enabled": False},
            "mqtt": {"enabled": False},
            "mdns": {"enabled": False},
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        with (tmp_path / "agent.log").open("w") as log, ExitStack() as clients:
            process = subprocess.Popen(
                [str(native_binary), "--config", str(config_path)], stdout=log, stderr=log
            )
            try:
                wait_for_health(api_port)
                before_fds = len(list(Path(f"/proc/{process.pid}/fd").iterdir()))
                slow = []
                for _ in range(4):
                    connection = clients.enter_context(socket.socket())
                    connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
                    connection.settimeout(0.8)
                    connection.connect(("127.0.0.1", api_port))
                    connection.sendall(
                        f"GET {prefix}message_1{suffix} HTTP/1.1\r\nHost: localhost\r\n"
                        f"Authorization: {AUTHORIZATION}\r\n\r\n".encode()
                    )
                    assert connection.recv(256).startswith(b"HTTP/1.1 200 OK\r\n")
                    slow.append(connection)
                assert request(api_port, "/api/v1/health")[0] == 200
                assert request(api_port, "/api/v1/stair-light/actions/activate", method="POST")[0] == 200
                assert own.frames
                status, body = request(api_port, prefix + "message_2" + suffix)
                assert status == 503 and json.loads(body)["error"] == "media_transfers_busy"

                for connection in slow:
                    connection.shutdown(socket.SHUT_RDWR)
                    connection.close()
                # The same listener handles new requests as closed transfer slots drain.
                deadline = time.monotonic() + 1
                while len(list(Path(f"/proc/{process.pid}/fd").iterdir())) > before_fds:
                    assert time.monotonic() < deadline
                    assert request(api_port, "/api/v1/health")[0] == 200
                    time.sleep(0.01)
                assert request(api_port, prefix + "message_2" + suffix) == (200, payload)
                # Shutdown also owns and closes a currently blocked download.
                connection = clients.enter_context(socket.socket())
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
                connection.settimeout(0.8)
                connection.connect(("127.0.0.1", api_port))
                connection.sendall(
                    f"GET {prefix}message_1{suffix} HTTP/1.1\r\nHost: localhost\r\n"
                    f"Authorization: {AUTHORIZATION}\r\n\r\n".encode()
                )
                assert connection.recv(256).startswith(b"HTTP/1.1 200 OK\r\n")
                process.terminate()
                assert process.wait(timeout=1) == 0
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
