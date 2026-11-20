"""Media operations of API requests run beside the HTTP loop, one at a time."""

from __future__ import annotations

import json
import signal
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.client import HTTPConnection
from pathlib import Path

import pytest

from native_agent.test.smoke import TOKEN, api_get, free_tcp_ports, wait_for_health

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
ACTIVATE = "/api/v1/video/doorbell/actions/activate"
STOP = "/api/v1/video/doorbell/actions/stop"
HANGUP = "/api/v1/calls/doorbell/actions/hangup"
HOME_START = "/api/v1/calls/home/actions/start"
HOME_STOP = "/api/v1/calls/home/actions/stop"


@dataclass
class Lab:
    root: Path
    api_port: int
    process: subprocess.Popen[bytes]
    connections: list[HTTPConnection] = field(default_factory=list)

    def post(self, path: str, body: dict | None = None) -> HTTPConnection:
        conn = HTTPConnection("127.0.0.1", self.api_port, timeout=10)
        self.connections.append(conn)
        conn.request("POST", path, body=json.dumps(body or {}),
                     headers={"Authorization": "Bearer " + TOKEN})
        return conn

    def log(self) -> list[str]:
        path = self.root / "media.log"
        return path.read_text().splitlines() if path.exists() else []

    def hold(self) -> None:
        (self.root / "hold").write_text("")

    def release(self) -> None:
        (self.root / "hold").unlink(missing_ok=True)

    def held_stop(self, path: str = STOP) -> HTTPConnection:
        self.hold()
        conn = self.post(path)
        self.wait_for("stop begin")
        return conn

    def wait_for(self, line: str, count: int = 1) -> None:
        deadline = time.monotonic() + 5
        while self.log().count(line) < count:
            assert time.monotonic() < deadline, self.log()
            time.sleep(0.01)

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
    directory = tmp_path_factory.mktemp("media-control-build")
    subprocess.run(["make", "-C", str(NATIVE), f"BUILD_DIR={directory}", "-j2", "all"],
                   check=True, capture_output=True, text=True)
    objects = [str(path) for path in sorted((directory / "host").glob("*.o"))
               if path.name != "media_bridge.o"]
    target = directory / "agent-with-held-media"
    subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
                    str(NATIVE / "test/media_bridge_hold_stub.c"), *objects,
                    "-pthread", "-ldl", "-o", str(target)],
                   check=True, capture_output=True, text=True)
    return target


@pytest.fixture
def lab(binary: Path, tmp_path: Path) -> Iterator[Lab]:
    api, ui = free_tcp_ports(2)
    config = {
        "listen": {"host": "127.0.0.1", "apiPort": api, "uiPort": ui},
        "api": {"token": TOKEN},
        "openwebnet": {"host": "127.0.0.1", "port": 1, "timeoutMs": 200},
        "maintenance": {"enabled": False},
        "activations": {"enabled": False, "autoDiscover": False},
        "events": {"udp": {"enabled": False}},
        "answeringMachine": {"messages": {"enabled": False}},
        "memos": {"enabled": False}, "systemMetrics": {"enabled": False},
        "video": {"enabled": True}, "displayBridge": {"enabled": False},
        "mqtt": {"enabled": False}, "mdns": {"enabled": False},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    with (tmp_path / "agent.log").open("w") as log:
        process = subprocess.Popen([str(binary), "--config", str(config_path)],
                                   stdout=log, stderr=log, cwd=tmp_path)
        lab = Lab(tmp_path, api, process)
        try:
            wait_for_health(api)
            yield lab
        finally:
            lab.release()
            for conn in lab.connections:
                conn.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def test_a_held_stop_leaves_the_api_answering(lab: Lab) -> None:
    stop = lab.held_stop()

    assert max(lab.health_ms() for _ in range(5)) < 500
    assert lab.log() == ["stop begin"]

    lab.release()
    assert finish(stop) == {"ok": True}
    assert lab.log() == ["stop begin", "stop end"]


def test_operations_run_one_after_the_other_and_once_each(lab: Lab) -> None:
    stop = lab.held_stop()
    home = lab.post(HOME_START, {"duration_seconds": 7})
    home_stop = lab.post(HOME_STOP)
    lab.health_ms()
    assert lab.log() == ["stop begin"]

    lab.release()
    assert finish(stop) == {"ok": True}
    assert finish(home) == {"ok": True, "duration_seconds": 7}
    assert finish(home_stop) == {"ok": True}
    assert lab.log() == ["stop begin", "stop end", "home_start 7", "home_stop"]
    lab.health_ms()
    assert lab.log() == ["stop begin", "stop end", "home_start 7", "home_stop"]


def test_an_activation_answers_with_its_own_result(lab: Lab) -> None:
    hangup = lab.held_stop(HANGUP)
    activate = lab.post(ACTIVATE, {"audio": False})
    lab.health_ms()

    lab.release()
    assert finish(hangup) == {"ok": True}
    assert finish(activate) == {"ok": True, "audio": False}
    assert lab.log() == ["stop begin", "stop end", "activate"]


def test_a_stop_whose_caller_left_ends_and_frees_the_worker(lab: Lab) -> None:
    stop = lab.held_stop()
    stop.close()
    lab.health_ms()

    lab.release()
    assert finish(lab.post(HOME_STOP)) == {"ok": True}
    assert lab.log() == ["stop begin", "stop end", "home_stop"]


def test_a_waiting_start_is_dropped_when_its_caller_left_but_a_stop_still_runs(lab: Lab) -> None:
    stop = lab.held_stop()
    home = lab.post(HOME_START, {"duration_seconds": 5})
    home_stop = lab.post(HOME_STOP)
    lab.health_ms()
    home.close()
    home_stop.close()
    lab.health_ms()

    lab.release()
    assert finish(stop) == {"ok": True}
    lab.wait_for("home_stop")
    lab.health_ms()
    assert lab.log() == ["stop begin", "stop end", "home_stop"]


def test_a_request_beyond_the_waiting_places_runs_after_the_running_one(lab: Lab) -> None:
    stop = lab.held_stop()
    waiting = [lab.post(HOME_START, {"duration_seconds": seconds}) for seconds in (1, 2, 3)]
    lab.health_ms()
    extra = lab.post(HOME_STOP)
    time.sleep(0.2)
    assert lab.log() == ["stop begin"]

    lab.release()
    assert finish(stop) == {"ok": True}
    assert finish(extra) == {"ok": True}
    for conn in waiting:
        assert finish(conn)["ok"] is True
    log = lab.log()
    assert log[:3] == ["stop begin", "stop end", "home_stop"]
    assert sorted(log[3:]) == ["home_start 1", "home_start 2", "home_start 3"]


def test_shutdown_lets_a_running_operation_end(lab: Lab) -> None:
    lab.held_stop()
    lab.process.send_signal(signal.SIGTERM)
    time.sleep(0.3)
    assert lab.process.poll() is None

    lab.release()
    assert lab.process.wait(timeout=5) == 0
    assert lab.log()[:2] == ["stop begin", "stop end"]
