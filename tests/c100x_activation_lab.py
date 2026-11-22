"""Local native-agent/probe harness. Never binds LAN or contacts a device/HA."""

from contextlib import contextmanager
from http.client import HTTPConnection
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

import pytest

from native_agent.test.smoke import TOKEN, free_tcp_ports, wait_for_health
from test_c100x_qml_adapter import ROOT
from test_native_routing_firmware_restore import FIRMWARE_ROOT, original


@pytest.fixture(scope="module")
def activation_binary(tmp_path_factory):
    original("c100x-1.5.8")
    marker = FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino/bin/gui/BtClass100"
    build = tmp_path_factory.mktemp("c100x-activation-build")
    flags = ("-std=c11 -O2 -g -Wall -Wextra -Werror -pedantic -D_DEFAULT_SOURCE -D_POSIX_C_SOURCE=200809L "
             '-DC300X_NATIVE_AGENT_VERSION=\\\"test\\\" '
             f'-DC300X_C100X_DISPLAY_MARKER=\\\"{marker}\\\"')
    result = subprocess.run(["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}",
                             f"CFLAGS={flags}", "-j2", "all"], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return build / "host/c300x-agent-native"


@contextmanager
def agent_lab(binary, tree):
    root, _, _, env = tree
    agent = root / "agent"
    agent.mkdir()
    shutil.copy2(binary, agent / "c300x-agent-native")
    api, ui, own = free_tcp_ports(3)
    config = {
        "listen": {"host": "127.0.0.1", "apiPort": api, "uiPort": ui}, "api": {"token": TOKEN},
        "openwebnet": {"host": "127.0.0.1", "port": own, "timeoutMs": 100},
        "activations": {"enabled": False, "autoDiscover": False}, "events": {"udp": {"enabled": False}},
        "answeringMachine": {"messages": {"enabled": False}}, "memos": {"enabled": False},
        "systemMetrics": {"enabled": False}, "video": {"enabled": False}, "displayBridge": {"enabled": False},
        "mqtt": {"enabled": False}, "mdns": {"enabled": False},
    }
    (agent / "config.json").write_text(json.dumps(config))
    env.update(C300X_AGENT_DIR=str(agent), C100X_TEST_UI_PORT=str(ui))
    wget = root / "tools/wget"
    wget.write_text(f"#!{sys.executable}\n" + '''import os, sys, urllib.request
url = sys.argv[-1]
assert url.startswith("http://127.0.0.1:8090/ui/c100x/presence/")
assert "-Y" in sys.argv and "off" in sys.argv and "-T" in sys.argv
assert not any(os.environ.get(key) for key in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"))
url = url.replace("127.0.0.1:8090", "127.0.0.1:" + os.environ["C100X_TEST_UI_PORT"], 1)
request = urllib.request.Request(url, headers={"X-C100X-GUI": "presence-v1"})
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(request, timeout=2) as response: sys.stdout.buffer.write(response.read(4096))
except Exception: sys.exit(1)
''')
    wget.chmod(0o700)
    with (root / "agent.log").open("w") as log:
        process = subprocess.Popen([str(agent / "c300x-agent-native"), "--config", str(agent / "config.json")],
                                   cwd=root, env=env, stdout=log, stderr=log)
        try:
            wait_for_health(api)
            yield ui
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            assert process.returncode == 0, (root / "agent.log").read_text()


@contextmanager
def gui_peer(port, generation, *, responsive=True, blocked=False):
    stop = threading.Event()
    sockets, errors = [], []

    def serve():
        probe = ""
        try:
            while not stop.is_set():
                connection = HTTPConnection("127.0.0.1", port, timeout=15)
                connection.connect()
                sockets.append(connection.sock)
                connection.request("GET", f"/ui/c100x/presence/next?generation={generation}&blocked={int(blocked)}{probe}",
                                   headers={"X-C100X-GUI": "presence-v1"})
                if not responsive:
                    stop.wait(15)
                    connection.close()
                    return
                response = connection.getresponse()
                data = json.loads(response.read())
                connection.close()
                probe = "&probe=" + data["probe"] if "probe" in data else ""
        except (OSError, ValueError) as error:
            if not stop.is_set():
                errors.append(str(error))

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 3
        while True:
            connection = HTTPConnection("127.0.0.1", port, timeout=2)
            connection.request("GET", "/ui/c100x/presence/status?generation=" + generation,
                               headers={"X-C100X-GUI": "presence-v1"})
            state = json.loads(connection.getresponse().read())
            connection.close()
            if state.get("present"):
                assert state["gui_ready"] is False
                break
            assert time.monotonic() < deadline, errors
            time.sleep(0.02)
        yield
    finally:
        stop.set()
        for descriptor in sockets:
            try:
                descriptor.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert not errors, errors
