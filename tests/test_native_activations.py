"""Activations and the stair light against a recording OpenWebNet bus."""

from __future__ import annotations

import json
import socketserver
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from http.client import HTTPConnection
from pathlib import Path
from typing import Any

import pytest
from native_build import default_host_agent

from native_agent.test.smoke import (
    TOKEN,
    free_tcp_ports,
    managed_tcp_server,
    read_frame,
    wait_for_health,
)

ITEMS = [
    {"id": "stairs", "name": "Stairs", "type": "stair_light", "addressMode": "manual", "address": "11"},
]


class BusHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        bus = self.server
        assert isinstance(bus, Bus)
        self.request.settimeout(10)
        try:
            self.request.sendall(b"*#*1##")
            if read_frame(self.request) != "*99*0##":
                return
            self.request.sendall(b"*#*1##")
            while frame := read_frame(self.request):
                bus.frames.append((time.monotonic(), frame))
                self.request.sendall(b"*#*1##")
        except OSError:
            return


class Bus(socketserver.ThreadingTCPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), BusHandler)
        self.frames: list[tuple[float, str]] = []

    def sent(self) -> list[str]:
        return [frame for _, frame in self.frames]


@dataclass
class Lab:
    bus: Bus
    api_port: int
    config_path: Path

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        conn = HTTPConnection("127.0.0.1", self.api_port, timeout=10)
        try:
            conn.request(method, path, body=json.dumps(body) if body is not None else None,
                         headers={"Authorization": "Bearer " + TOKEN})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()


@pytest.fixture(scope="module")
def binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return default_host_agent(tmp_path_factory)


def agent_config(bus_port: int, api: int, ui: int, items: list[dict[str, Any]],
                 stair_light: str = "15") -> dict[str, Any]:
    return {
        "device": {"stairLightDefaultAddress": stair_light},
        "listen": {"host": "127.0.0.1", "apiPort": api, "uiPort": ui},
        "api": {"token": TOKEN},
        "openwebnet": {"host": "127.0.0.1", "port": bus_port, "timeoutMs": 5000},
        "locks": {"releaseDelayMs": 50, "items": {"default": {"name": "Door", "address": "20"}}},
        "maintenance": {"enabled": False},
        "activations": {"enabled": True, "autoDiscover": False, "items": items},
        "events": {"udp": {"enabled": False}},
        "answeringMachine": {"messages": {"enabled": False}},
        "memos": {"enabled": False}, "systemMetrics": {"enabled": False},
        "video": {"enabled": False}, "displayBridge": {"enabled": False},
        "mqtt": {"enabled": False}, "mdns": {"enabled": False},
    }


@pytest.fixture
def lab(binary: Path, tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Lab]:
    items = getattr(request, "param", ITEMS)
    stair_light = "" if items == [] else "15"
    with managed_tcp_server(Bus()) as bus:
        api, ui = free_tcp_ports(2)
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(agent_config(bus.server_address[1], api, ui, items, stair_light)))
        with (tmp_path / "agent.log").open("w") as log:
            process = subprocess.Popen([str(binary), "--config", str(config_path)],
                                       stdout=log, stderr=log, cwd=tmp_path)
            try:
                wait_for_health(api)
                bus.frames.clear()
                yield Lab(bus, api, config_path)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def assert_released_after_display_delay(bus: Bus, where: str) -> None:
    assert bus.sent() == [f"*8*21*{where}##", f"*8*22*{where}##"]
    gap = bus.frames[1][0] - bus.frames[0][0]
    assert 0.09 <= gap < 1.0


def test_the_stair_light_route_releases_the_light_as_the_display_does(lab: Lab) -> None:
    status, body = lab.request("POST", "/api/v1/stair-light/actions/activate", {"address": "11"})

    assert (status, body) == (200, {"ok": True, "address": "11"})
    assert_released_after_display_delay(lab.bus, "11")


def test_the_stair_light_route_uses_the_configured_address(lab: Lab) -> None:
    status, body = lab.request("POST", "/api/v1/stair-light/actions/activate", {})

    assert (status, body) == (200, {"ok": True, "address": "15"})
    assert_released_after_display_delay(lab.bus, "15")


@pytest.mark.parametrize("lab", [[]], indirect=True)
def test_without_a_configured_address_the_stair_light_is_not_at_a_fixed_one(lab: Lab) -> None:
    # The light is at the station's own address from /var/tmp/conf.xml; a
    # host has none, so there is no address, and never a made-up "10".
    if Path("/var/tmp/conf.xml").exists():
        pytest.skip("this host has a station conf.xml")
    status, body = lab.request("POST", "/api/v1/stair-light/actions/activate", {})

    assert (status, body) == (503, {"ok": False, "error": "stair_light_address_unknown"})
    assert lab.bus.sent() == []


def test_a_stair_light_activation_releases_the_light_as_the_display_does(lab: Lab) -> None:
    status, body = lab.request("POST", "/api/v1/activations/stairs/actions/run", {})

    assert status == 200 and body["type"] == "stair_light"
    assert_released_after_display_delay(lab.bus, "11")


STORED_LIGHT = [
    {"id": "lamp", "name": "Lamp", "type": "light", "addressMode": "manual", "address": "20"},
    {"id": "front", "name": "Front", "type": "lock", "addressMode": "manual", "address": "21"},
]
ACTUATOR = [
    {"id": "gate", "name": "Gate opener", "type": "actuator", "addressMode": "manual", "address": "25"},
]


@pytest.mark.parametrize("lab", [STORED_LIGHT], indirect=True)
def test_a_stored_light_item_is_left_out_and_the_file_saved_without_it(lab: Lab) -> None:
    # "light" sent the stair-light frame; the lock frames at its address
    # (here outdoor unit 20) would open a door, so the item goes.
    text = lab.config_path.read_text()
    stored = json.loads(text)["activations"]["items"]
    status, body = lab.request("GET", "/api/v1/activations")
    run_status, _ = lab.request("POST", "/api/v1/activations/lamp/actions/run", {})

    assert [item["id"] for item in stored] == ["front"]
    assert '"light"' not in text and '"lamp"' not in text
    assert status == 200
    assert [(item["id"], item["type"]) for item in body["items"]] == [("front", "lock")]
    assert run_status == 404
    assert lab.bus.sent() == []


@pytest.mark.parametrize("lab", [ACTUATOR], indirect=True)
def test_an_actuator_is_pressed_and_released_with_the_lock_frames(lab: Lab) -> None:
    status, body = lab.request("POST", "/api/v1/activations/gate/actions/run", {})

    assert (status, body["type"]) == (200, "actuator")
    assert lab.bus.sent() == ["*8*19*25##", "*8*20*25##"]
    assert lab.bus.frames[1][0] - lab.bus.frames[0][0] >= 0.045
