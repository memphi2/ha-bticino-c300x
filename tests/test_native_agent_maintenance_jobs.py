"""Bounded script execution through the native HTTP loop, without a device."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from http.client import HTTPConnection
from pathlib import Path

import pytest

from native_agent.test.smoke import TOKEN, api_get, free_tcp_port, wait_for_health

ROOT = Path(__file__).resolve().parents[1]
QML = "/api/v1/maintenance/qml-patch"
GUI = "/api/v1/maintenance/gui/actions/reload"
HEADERS = {"Authorization": "Bearer " + TOKEN,
           "X-Bticino-C300X-Maintenance-Token": "maintenance-token"}


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition did not become true"
        time.sleep(0.01)


@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    build = tmp_path_factory.mktemp("maintenance-build")
    subprocess.run(["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}",
                    "-j2", "all"], check=True, capture_output=True, text=True)
    return build / "host/c300x-agent-native"


@dataclass
class Lab:
    root: Path
    port: int
    ui_port: int
    process: subprocess.Popen
    connections: list[HTTPConnection] = field(default_factory=list)

    def script(self, body):
        path = self.root / "job.sh"
        path.write_text('#!/bin/sh\ncd "$(dirname "$0")" || exit 1\nprintf "%s" "$$" > started\n' + body)
        path.chmod(0o700)

    def request(self, path=QML, payload=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=13)
        self.connections.append(conn)
        conn.request("GET" if payload is None else "POST", path,
                     body=None if payload is None else json.dumps(payload),
                     headers=HEADERS if headers is None else headers)
        return conn

    def started(self):
        wait_until(lambda: (self.root / "started").exists())

    def release(self):
        (self.root / "release").touch()


@pytest.fixture
def lab(binary, tmp_path):
    port, ui_port = free_tcp_port(), free_tcp_port()
    config = {
        "listen": {"host": "127.0.0.1", "apiPort": port, "uiPort": ui_port},
        "api": {"token": TOKEN},
        "openwebnet": {"host": "127.0.0.1", "port": free_tcp_port(), "timeoutMs": 100},
        "maintenance": {"enabled": True, "adminToken": "maintenance-token",
                        "qmlPatch": {"enabled": True, "script": str(tmp_path / "job.sh")},
                        "guiReload": {"enabled": True, "script": str(tmp_path / "job.sh")}},
        "activations": {"enabled": False, "autoDiscover": False},
        "events": {"udp": {"enabled": False}},
        "answeringMachine": {"messages": {"enabled": False}},
        "memos": {"enabled": False}, "systemMetrics": {"enabled": False},
        "video": {"enabled": False}, "displayBridge": {"enabled": False},
        "mqtt": {"enabled": False}, "mdns": {"enabled": False},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    env = {**os.environ, "C300X_QML_DYNAMIC_HOME_PAGE": "0"}
    with (tmp_path / "agent.log").open("w") as log:
        process = subprocess.Popen([str(binary), "--config", str(path)], cwd=tmp_path,
                                   stdout=log, stderr=log, env=env)
        lab = Lab(tmp_path, port, ui_port, process)
        try:
            wait_for_health(port)
            yield lab
        finally:
            for conn in lab.connections:
                conn.close()
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def response(conn, status=200):
    result = conn.getresponse()
    body = json.loads(result.read())
    assert result.status == status, body
    return body


@pytest.mark.parametrize("path,payload", [
    (QML, None),
    (QML + "/actions/apply", {"confirm": "apply_qml_patch", "dynamic_homepage": True}),
    (GUI, {"confirm": "reload_gui"}),
])
def test_slow_job_preserves_api_ui_auth_and_single_writer(lab, path, payload):
    lab.script('while [ ! -e release ]; do sleep 0.02; done\n'
               'printf \'{"ok":true,"changed_files":0,"dynamic":"%s"}\' "$C300X_QML_DYNAMIC_HOME_PAGE"\n')
    pending = lab.request(path, payload)
    lab.started()
    started = time.monotonic()
    assert api_get(lab.port, "/api/v1/health")["ok"]
    api_get(lab.ui_port, "/ui/events/status", authorized=False)
    assert time.monotonic() - started < 1
    assert response(lab.request(), 409)["error"] == "maintenance_busy"
    assert response(lab.request("/api/v1/device-user"), 409)["error"] == "maintenance_busy"
    assert response(lab.request(GUI, {"confirm": "reload_gui"}), 409)["error"] == "maintenance_busy"
    assert response(lab.request(GUI, {}, headers={"Authorization": "Bearer " + TOKEN}), 403)["error"] == "maintenance_unauthorized"
    assert response(lab.request(GUI, {}, headers={"X-Bticino-C300X-Maintenance-Token": "maintenance-token"}), 401)["error"] == "unauthorized"
    assert response(lab.request(headers={}), 401)["error"] == "unauthorized"
    lab.release()
    assert response(pending)["dynamic"] == ("1" if payload and payload.get("dynamic_homepage") else "0")
    assert response(lab.request())["ok"]


@pytest.mark.parametrize("body,status,expected", [
    ('printf \'{"ok":true,"changed_files":0}\'\n', 200, {"ok": True, "changed_files": 0}),
    ("exit 1\n", 502, {"ok": False, "available": False, "state": "script_failed"}),
    ("printf invalid\n", 502, {"ok": False, "available": False, "state": "invalid_script_response"}),
    ("while :; do printf 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'; done\n", 502,
     {"ok": False, "available": False, "state": "script_failed"}),
])
def test_job_response_and_failure_cleanup(lab, body, status, expected):
    lab.script(body)
    assert response(lab.request(), status) == expected
    assert api_get(lab.port, "/api/v1/health")["ok"]
    # A timed-out/overfull process is reaped before another command may start.
    time.sleep(0.15)
    lab.script('printf \'{"ok":true,"changed_files":0}\'\n')
    assert response(lab.request())["ok"]


def test_disconnect_keeps_one_job_and_does_not_reuse_its_client_fd(lab):
    lab.script('while [ ! -e release ]; do sleep 0.02; done\nprintf \'{"ok":true}\'\n')
    pending = lab.request()
    lab.started()
    pending.close()
    for _ in range(8):
        assert api_get(lab.port, "/api/v1/health")["agent"] == "native-c"
    assert response(lab.request(), 409)["error"] == "maintenance_busy"
    lab.release()
    time.sleep(0.2)
    assert response(lab.request())["ok"]


def test_timeout_with_closed_stdout_does_not_block_and_reaps_child(lab):
    lab.script("exec 1>&-\nexec sleep 30\n")
    pending = lab.request()
    lab.started()
    pid = int((lab.root / "started").read_text())
    assert api_get(lab.port, "/api/v1/health")["ok"]
    assert response(pending, 502)["state"] == "script_failed"
    wait_until(lambda: not Path(f"/proc/{pid}").exists())
    lab.script('printf \'{"ok":true}\'\n')
    assert response(lab.request())["ok"]


def test_shutdown_kills_pending_script_without_waiting(lab):
    lab.script("exec sleep 30\n")
    lab.request()
    lab.started()
    pid = int((lab.root / "started").read_text())
    lab.process.terminate()
    assert lab.process.wait(timeout=2) == 0
    wait_until(lambda: not Path(f"/proc/{pid}").exists()
               or Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z")


def test_completed_jobs_leave_no_fd_timer_or_write_churn(lab):
    lab.script('printf \'{"ok":true,"changed_files":0}\'\n')
    before = api_get(lab.port, "/api/v1/diagnostics")
    for _ in range(10):
        assert response(lab.request(QML + "/actions/apply", {"confirm": "apply_qml_patch"}))["ok"]
    after = api_get(lab.port, "/api/v1/diagnostics")
    assert after["open_fd_count"] == before["open_fd_count"]
    assert after["agent_write_count"] == before["agent_write_count"]
    time.sleep(0.3)
    idle = api_get(lab.port, "/api/v1/diagnostics")
    assert idle["loop_iterations"] - after["loop_iterations"] <= 3
    lab.script('printf \'{"ok":true,"changed_files":1}\'\n')
    assert response(lab.request(QML + "/actions/apply", {"confirm": "apply_qml_patch"}))["ok"]
    changed = api_get(lab.port, "/api/v1/diagnostics")
    assert changed["agent_write_count"] == before["agent_write_count"] + 1


def test_confirmation_and_missing_script_do_not_start_jobs(lab):
    assert response(lab.request(GUI, {}), 400)["error"] == "maintenance_confirmation_required"
    assert not (lab.root / "started").exists()
    assert response(lab.request(GUI, {"confirm": "reload_gui"}), 502)["error"] == "reload_script_missing"
    assert response(lab.request(), 502)["state"] == "script_missing"
    lab.script("printf ready\n")
    assert response(lab.request(GUI, {"confirm": "reload_gui"}))["action"] == "reload_gui"
