"""Real local HTTP preference requests with isolated native builds and config."""

import fcntl
import http.client
import json
import os
import socket
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from native_agent.test.smoke import (
    TOKEN,
    free_tcp_port,
    free_tcp_ports,
    wait_for_health,
)

ROOT = Path(__file__).resolve().parents[1]
HEADER = {"X-C300X-UI": "1"}
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}",
                "X-Bticino-C300X-Maintenance-Token": "test-admin"}


@pytest.fixture(scope="module")
def native_preferences_binary(tmp_path_factory):
    build = tmp_path_factory.mktemp("preferences-native-build")
    result = subprocess.run(
        ["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}", "-j2", "all"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    # Fault only the config writer's temporary-file creation, not the HTTP stack.
    source = build / "fail_config.c"
    source.write_text('''#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int mkstemp(char *path) {
    const char *marker = getenv("C300X_TEST_FAIL_CONFIG");
    if (marker && access(marker, F_OK) == 0 && strstr(path, "config.json.tmp.")) {
        errno = ENOSPC;
        return -1;
    }
    int (*original)(char *) = dlsym(RTLD_NEXT, "mkstemp");
    return original(path);
}
''')
    preload = build / "fail_config.so"
    subprocess.run(["cc", "-shared", "-fPIC", str(source), "-ldl", "-o", str(preload)],
                   check=True, capture_output=True, text=True, timeout=30)
    return build / "host/c300x-agent-native", preload


def request(port, method="GET", body=None, headers=None, path="/ui/preferences", source=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5, source_address=source)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        return response.status, json.loads(data) if data else None, dict(response.getheaders())
    finally:
        connection.close()


def post(lab, value):
    return request(lab.ui, "POST", json.dumps({"feedback_enabled": value}), HEADER)


def file_state(path):
    info = path.stat()
    return path.read_bytes(), info.st_ino, info.st_mtime_ns, info.st_ctime_ns


@pytest.fixture
def lab(native_preferences_binary, tmp_path):
    binary, preload = native_preferences_binary
    api, ui, own = free_tcp_ports(3)
    config = {
        "listen": {"host": "127.0.0.1", "apiPort": api, "uiPort": ui},
        "api": {"token": TOKEN},
        "openwebnet": {"host": "127.0.0.1", "port": own, "timeoutMs": 100},
        "activations": {"enabled": False, "autoDiscover": False},
        "events": {"udp": {"enabled": False}}, "memos": {"enabled": False},
        "answeringMachine": {"messages": {"enabled": False}},
        "systemMetrics": {"enabled": False}, "video": {"enabled": False},
        "displayBridge": {"enabled": False}, "mqtt": {"enabled": False},
        "maintenance": {"enabled": False, "adminToken": "test-admin"},
        "mdns": {"enabled": False},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    marker = tmp_path / "fail-config"
    log = (tmp_path / "agent.log").open("w")
    processes = []

    def start():
        process = subprocess.Popen([str(binary), "--config", str(path)], stdout=log, stderr=log,
                                   env={**os.environ, "LD_PRELOAD": str(preload),
                                        "C300X_TEST_FAIL_CONFIG": str(marker)})
        processes.append(process)
        wait_for_health(api)
        return process

    def stop(process):
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def restart():
        stop(processes[-1])
        start()

    try:
        start()
        yield SimpleNamespace(api=api, ui=ui, path=path, marker=marker, restart=restart)
    finally:
        for process in processes:
            if process.poll() is None:
                stop(process)
        log.close()


def test_default_reads_and_noop_never_write_without_display_registration(lab):
    before = file_state(lab.path)
    for _ in range(3):
        assert request(lab.ui)[:2] == (200, {"ok": True, "feedback_enabled": True})
        assert post(lab, True)[:2] == (200, {"ok": True, "feedback_enabled": True})
    assert file_state(lab.path) == before
    assert not list(lab.path.parent.glob("config.json.tmp.*"))


def test_changes_persist_across_restart_and_noop_preserves_inode(lab):
    assert post(lab, False)[:2] == (200, {"ok": True, "feedback_enabled": False})
    assert json.loads(lab.path.read_text())["displayBridge"]["feedbackEnabled"] is False
    before = file_state(lab.path)
    assert post(lab, False)[0] == 200
    assert file_state(lab.path) == before
    lab.restart()
    assert request(lab.ui)[1]["feedback_enabled"] is False
    assert post(lab, True)[1]["feedback_enabled"] is True
    lab.restart()
    assert request(lab.ui)[1]["feedback_enabled"] is True


@pytest.mark.parametrize("body", ["", "{}", "[]", "null", '{"feedback_enabled":',
                                  '{"feedback_enabled":false} trailing',
                                  *[json.dumps({"feedback_enabled": value})
                                    for value in (0, 1, "false", "true", None, [], {})],
                                  '{"nested":{"feedback_enabled":false}}'])
def test_malformed_or_nonboolean_value_is_rejected_without_writes(lab, body):
    before = file_state(lab.path)
    assert request(lab.ui, "POST", body, HEADER)[0] == 400
    assert file_state(lab.path) == before
    assert request(lab.ui)[1]["feedback_enabled"] is True


@pytest.mark.parametrize("headers", [{}, {"X-C300X-UI": "0"}, {"X-C300X-UI": "1x"},
                                      {**HEADER, "Origin": "http://evil.invalid"},
                                      {**HEADER, "Origin": "null"}, {**HEADER, "Origin": ""}])
def test_browser_and_missing_gui_header_cannot_write(lab, headers):
    before = file_state(lab.path)
    status, _, response_headers = request(lab.ui, "POST", '{"feedback_enabled":false}', headers)
    assert status == 403
    assert "Access-Control-Allow-Origin" not in response_headers
    assert file_state(lab.path) == before


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def test_unsupported_methods_do_not_write(lab, method):
    before = file_state(lab.path)
    assert request(lab.ui, method, headers=HEADER)[0] == 405
    assert file_state(lab.path) == before


def test_api_listener_does_not_expose_local_preference_route(lab):
    before = file_state(lab.path)
    assert request(lab.api, "POST", '{"feedback_enabled":false}', {**HEADER, **AUTH_HEADERS})[0] != 200
    assert file_state(lab.path) == before


def test_nonloopback_source_cannot_read_or_write_preferences(lab):
    address = None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        for _, name in socket.if_nameindex():
            if name == "lo":
                continue
            try:
                result = fcntl.ioctl(probe, 0x8915, struct.pack("256s", name.encode()[:15]))
                address = socket.inet_ntoa(result[20:24])
                break
            except OSError:
                continue
    if address is None:
        pytest.skip("No local non-loopback IPv4 interface")
    before = file_state(lab.path)
    for method in ("GET", "POST"):
        assert request(lab.ui, method, '{"feedback_enabled":false}' if method == "POST" else None,
                       HEADER, source=(address, 0))[0] == 403
    assert file_state(lab.path) == before


@pytest.mark.parametrize("failure", ["invalid-config", "missing-config", "no-space"])
def test_persistence_failure_leaves_runtime_and_existing_file_unchanged(lab, failure):
    if failure == "invalid-config":
        lab.path.write_text("invalid JSON")
    elif failure == "missing-config":
        lab.path.unlink()
    else:
        lab.marker.touch()
    before = file_state(lab.path) if lab.path.exists() else None
    assert post(lab, False)[0] == 500
    assert request(lab.ui)[1]["feedback_enabled"] is True
    assert (file_state(lab.path) if lab.path.exists() else None) == before
    assert not list(lab.path.parent.glob("config.json.tmp.*"))


def test_pending_admin_config_and_later_admin_saves_preserve_feedback(lab):
    auth = "/api/v1/maintenance/auth"
    # uiPort remains live on the old port until restart.
    pending_port = free_tcp_port()
    assert request(lab.api, "POST", json.dumps({"uiPort": pending_port}), AUTH_HEADERS, auth)[0] == 200
    assert post(lab, False)[0] == 200
    assert json.loads(lab.path.read_text())["listen"]["uiPort"] == pending_port
    assert request(lab.api, "POST", '{"stairLightDefaultAddress":"21"}', AUTH_HEADERS, auth)[0] == 200
    persisted = json.loads(lab.path.read_text())
    assert persisted["displayBridge"]["feedbackEnabled"] is False
    assert persisted["listen"]["uiPort"] == pending_port
    assert request(lab.ui)[1]["feedback_enabled"] is False


def test_later_admin_save_without_pending_restart_preserves_feedback(lab):
    assert post(lab, False)[0] == 200
    assert request(lab.api, "POST", '{"stairLightDefaultAddress":"21"}', AUTH_HEADERS,
                   "/api/v1/maintenance/auth")[0] == 200
    assert json.loads(lab.path.read_text())["displayBridge"]["feedbackEnabled"] is False
    lab.restart()
    assert request(lab.ui)[1]["feedback_enabled"] is False


def test_targeted_save_preserves_unrelated_disk_changes_even_without_restart_flag(lab):
    pending = json.loads(lab.path.read_text())
    pending["mqtt"] = {"enabled": False, "host": "pending.local", "password": "pending-secret"}
    lab.path.write_text(json.dumps(pending))
    assert post(lab, False)[0] == 200
    persisted = json.loads(lab.path.read_text())
    assert persisted["mqtt"]["host"] == "pending.local"
    assert persisted["mqtt"]["password"] == "pending-secret"
