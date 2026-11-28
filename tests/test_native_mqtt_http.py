"""Real loopback MQTT backpressure through the complete HTTP event loop."""

import json
import os
import select
import socket
import subprocess
import time

import pytest
from test_native_agent_maintenance_jobs import (
    HEADERS,
    QML,
    ROOT,
    Lab,
    response,
    wait_until,
)

from native_agent.test.smoke import api_get, free_tcp_port, wait_for_health


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def binary(request, tmp_path_factory):
    build = tmp_path_factory.mktemp("mqtt-http-build")
    flags = ("-std=c11 -O2 -g -Wall -Wextra -Werror -pedantic "
             "-D_DEFAULT_SOURCE -D_POSIX_C_SOURCE=200809L "
             '-DC300X_NATIVE_AGENT_VERSION=\\\"test\\\"')
    if request.param:
        flags += " -fsanitize=address,undefined -fno-omit-frame-pointer"
    link = ("-pthread -ldl " + str(ROOT / "native_agent/test/mqtt_backpressure_stub.c")
            + " -Wl,--wrap=send -Wl,--wrap=connect -Wl,--wrap=poll -Wl,--wrap=__poll_chk"
            + " -Wl,--wrap=c300x_mqtt_output_timeout")
    result = subprocess.run(
        ["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}", f"CFLAGS={flags}",
         f"LDFLAGS={link}", "-j2", "all"], capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return build / "host/c300x-agent-native"


@pytest.fixture
def mqtt_lab(binary, tmp_path):
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(30)
    port, ui_port = free_tcp_port(), free_tcp_port()
    broker_port = listener.getsockname()[1]
    config = {
        "listen": {"host": "127.0.0.1", "apiPort": port, "uiPort": ui_port},
        "api": {"token": HEADERS["Authorization"].removeprefix("Bearer ")},
        "maintenance": {"enabled": True, "adminToken": "maintenance-token",
                        "qmlPatch": {"enabled": True, "script": str(tmp_path / "job.sh")}},
        "openwebnet": {"host": "127.0.0.1", "port": free_tcp_port(), "timeoutMs": 100},
        "activations": {"enabled": False, "autoDiscover": False},
        "events": {"udp": {"enabled": False}},
        "answeringMachine": {"messages": {"enabled": False}},
        "memos": {"enabled": False}, "systemMetrics": {"enabled": False},
        "video": {"enabled": False}, "displayBridge": {"enabled": False},
        "mdns": {"enabled": False},
        "mqtt": {"enabled": True, "host": "127.0.0.1", "port": broker_port,
                 "clientId": "http-test", "keepaliveSeconds": 60,
                 "reconnectInitialSeconds": 30, "reconnectMaxSeconds": 60,
                 "topics": {"command": "test/command", "event": "", "jsonEvent": "test/json",
                            "availability": "test/online", "status": "test/start"}},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    env = {**os.environ, "C300X_TEST_MQTT_PORT": str(broker_port),
           "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1"}
    peer = None
    with (tmp_path / "agent.log").open("w") as log:
        process = subprocess.Popen([str(binary), "--config", str(path)], cwd=tmp_path,
                                   stdout=log, stderr=log, env=env)
        lab = Lab(tmp_path, port, ui_port, process)
        try:
            wait_for_health(port)
            peer, _ = listener.accept()
            peer.settimeout(30)
            yield lab, peer
        finally:
            for connection in lab.connections:
                connection.close()
            if peer:
                peer.close()
            listener.close()
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=30)
            assert process.returncode == 0, (tmp_path / "agent.log").read_text()


def receive(peer, size):
    data = b""
    while len(data) < size:
        chunk = peer.recv(size - len(data))
        assert chunk, "MQTT connection closed within a frame"
        data += chunk
    return data


def packet(peer):
    kind = receive(peer, 1)[0]
    size, multiplier = 0, 1
    try:
        for _ in range(4):
            byte = receive(peer, 1)[0]
            size += (byte & 127) * multiplier
            if not byte & 128:
                return kind, receive(peer, size)
            multiplier *= 128
    except TimeoutError as error:
        raise AssertionError("stalled within a partial MQTT frame") from error
    raise AssertionError("invalid MQTT frame length")


def served_at_once(lab, ports, *, within):
    """Each request is answered in less time than an old blocking wait took."""

    for port, path in ports:
        started = time.monotonic()
        body = api_get(port, path, authorized=port == lab.port)
        assert time.monotonic() - started < within, path
        assert port != lab.port or body["ok"], body


def ready(lab, peer):
    assert packet(peer)[0] == 0x10
    # No CONNACK yet: the HTTP loop must still serve health. The old
    # handshake waited 1.5 s for the CONNACK on the loop.
    served_at_once(lab, [(lab.port, "/api/v1/health")], within=1.0)
    peer.sendall(b"\x20\x02\x00\x00")
    assert packet(peer)[0] == 0x82
    assert packet(peer) == (0x31, b"\x00\x0btest/onlineonline")
    kind, payload = packet(peer)
    assert kind == 0x31 and payload.startswith(b"\x00\x0atest/start")
    assert response(lab.request("/api/v1/maintenance/mqtt"))["connected"]


def test_backpressure_does_not_block_health_or_change_http_result(mqtt_lab):
    lab, peer = mqtt_lab
    ready(lab, peer)
    marker = lab.root / "mqtt-backpressure"
    marker.unlink(missing_ok=True)
    lab.script('printf \'{"ok":true,"changed_files":1}\\n\'\n')
    response(lab.request("/api/v1/events/subscriptions", {
        "callback_url": f"http://127.0.0.1:{free_tcp_port()}/callback",
        "events": ["agent.diagnostics_changed"],
    }), 201)
    # Stop reading until kernel backpressure: EAGAIN or loss of POLLOUT.
    held = None
    for _ in range(100):
        pending = lab.request(QML + "/actions/apply", {"confirm": "apply_qml_patch"})
        deadline = time.monotonic() + 30
        while not marker.exists() and not select.select([pending.sock], [], [], 0.005)[0]:
            assert time.monotonic() < deadline
        if marker.exists():
            held = pending
            break
        assert response(pending)["ok"]
    assert held is not None
    # Probe health before waiting for the event-generating request's response.
    # The old synchronous writable wait (500 ms) would delay these requests.
    served_at_once(lab, [(lab.port, "/api/v1/health"), (lab.ui_port, "/ui/events/status")] * 5, within=0.45)
    assert response(held)["ok"]
    assert response(lab.request("/api/v1/maintenance/mqtt"))["connected"]
    # Resume reading. Every admitted JSON event must still be a complete frame.
    # A frame's rest may follow late on a busy machine; a second without a
    # new frame ends the stream.
    events = []
    while True:
        readable, _, _ = select.select([peer], [], [], 1.0)
        if not readable:
            break
        kind, payload = packet(peer)
        assert kind == 0x30 and payload.startswith(b"\x00\x09test/json")
        events.append(json.loads(payload[11:]))
    assert events
    ids = [int(event["event_id"].rsplit("-", 1)[1]) for event in events]
    assert ids == sorted(set(ids))
    before = api_get(lab.port, "/api/v1/diagnostics")
    time.sleep(0.2)
    after = api_get(lab.port, "/api/v1/diagnostics")
    assert after["loop_iterations"] - before["loop_iterations"] <= 4
    assert after["open_fd_count"] == before["open_fd_count"]


def test_connack_timeout_and_shutdown_do_not_stall_http(mqtt_lab):
    lab, peer = mqtt_lab
    assert packet(peer)[0] == 0x10
    served_at_once(lab, [(lab.port, "/api/v1/health")] * 5, within=1.0)
    time.sleep(1.6)
    assert peer.recv(1) == b""
    assert response(lab.request("/api/v1/maintenance/mqtt"))["connected"] is False
    lab.process.terminate()
    assert lab.process.wait(timeout=30) == 0


@pytest.mark.parametrize("marker", ["shutdown-before-poll", "shutdown-worker-before-poll"])
def test_shutdown_signal_before_poll_wakes_the_idle_loop(mqtt_lab, marker):
    lab, peer = mqtt_lab
    ready(lab, peer)
    (lab.root / marker).touch()
    # Wake the old poll via the established broker socket. The next poll can
    # terminate the server before an HTTP wake-up request would get a reply.
    peer.close()
    wait_until(lambda: not (lab.root / marker).exists(), timeout=30)
    assert lab.process.wait(timeout=30) == 0
    assert "shutdown injected" in (lab.root / "agent.log").read_text()
