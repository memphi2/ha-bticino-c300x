"""Activations and the stair light against a recording OpenWebNet bus."""

from __future__ import annotations

import json
import socketserver
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.client import HTTPConnection
from pathlib import Path
from typing import Any

import pytest
from native_build import NATIVE, default_host_agent

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
                 stair_light: str = "15", discovery_roots: list[str] | None = None) -> dict[str, Any]:
    config = {
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
    if discovery_roots is not None:
        # Every file written before 3.1 has them; 3.1 writes none.
        config["activations"]["discoveryRoots"] = discovery_roots
    return config


@contextmanager
def running(binary: Path, tmp_path: Path, items: list[dict[str, Any]], stair_light: str,
            discovery_roots: list[str] | None = None) -> Iterator[Lab]:
    with managed_tcp_server(Bus()) as bus:
        api, ui = free_tcp_ports(2)
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(
            agent_config(bus.server_address[1], api, ui, items, stair_light, discovery_roots)
        ))
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


@pytest.fixture
def lab(binary: Path, tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Lab]:
    items = getattr(request, "param", ITEMS)
    with running(binary, tmp_path, items, "" if items == [] else "15") as lab:
        yield lab


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


@pytest.fixture(scope="module")
def station_binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The agent reading the station's conf.xml from its working directory."""

    build = tmp_path_factory.mktemp("station-conf-build")
    flags = ("-std=c11 -O2 -Wall -Wextra -Werror -pedantic -D_DEFAULT_SOURCE -D_POSIX_C_SOURCE=200809L "
             '-DC300X_NATIVE_AGENT_VERSION=\\"test\\" -DC300X_CONF_XML_PATH=\\"./conf.xml\\"')
    result = subprocess.run(["make", "-C", str(NATIVE), f"BUILD_DIR={build}", f"CFLAGS={flags}", "-j2", "all"],
                            capture_output=True, text=True, timeout=600, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return build / "host/c300x-agent-native"


# The station at 1, 1 (address 11), its default outdoor unit at 2, 0.
CONF_XML = ("<setup><vdes><communication><vde_enabled>1</vde_enabled><dev>1</dev><address>1</address>"
            "<p_default><dev>2</dev><address>0</address></p_default></communication></vdes></setup>")
ROOTS_3_0 = ["/home/bticino/cfg/extra/47", "/home/bticino/cfg/extra", "/home/bticino/cfg"]


@pytest.mark.parametrize(("roots", "address"), [(ROOTS_3_0, "11"), (None, "10")])
def test_the_fixed_stair_light_address_of_a_3_0_file_gives_way_to_the_station_s(
    station_binary: Path, tmp_path: Path, roots: list[str] | None, address: str,
) -> None:
    # The 3.0 installer always wrote "10"; a "10" set since 3.1 stays.
    (tmp_path / "conf.xml").write_text(CONF_XML)
    with running(station_binary, tmp_path, [], "10", roots) as lab:
        stored = json.loads(lab.config_path.read_text())
        status, body = lab.request("POST", "/api/v1/stair-light/actions/activate", {})

        assert (status, body) == (200, {"ok": True, "address": address})
        assert_released_after_display_delay(lab.bus, address)
    assert stored["device"]["stairLightDefaultAddress"] == ("" if roots else "10")
    assert "discoveryRoots" not in stored["activations"]


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
