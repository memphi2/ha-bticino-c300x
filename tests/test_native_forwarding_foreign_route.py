"""Forwarding changes are refused next to a foreign route.conf (C100X user-only mode).

A vendor forwarding change may relink route.conf. When the file is a regular
file of another program, the real agent must refuse the request with
409 foreign_active_route, send no OpenWebNet write, and change no file.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from native_agent.test.smoke import (
    TOKEN,
    api_post,
    free_tcp_ports,
    managed_tcp_server,
    wait_for_health,
)
from tests.test_native_agent_forwarding import FORWARDING_PATH, ForwardingDevice

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = "<sip:alluser@plant.example> <sip:app@plant.example>\n"
FOREIGN = OFFICIAL + "<sip:other@plant.example> <sip:companion@plant.example>\n"


def _define(name: str, path: Path) -> str:
    return f'-D{name}=\\"{path}\\"'


@pytest.fixture(scope="module")
def station(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """A C100X-like station tree and an agent built to use it."""

    root = tmp_path_factory.mktemp("foreign-route")
    users = root / "users"
    users.mkdir()
    (root / "BtClass100").write_text("", encoding="utf-8")
    build_dir = root / "build"
    cflags = " ".join([
        "-std=c11 -O2 -Wall -Wextra -Werror -pedantic -D_DEFAULT_SOURCE -D_POSIX_C_SOURCE=200809L",
        '-DC300X_NATIVE_AGENT_VERSION=\\"test\\"',
        _define("C300X_C100X_DISPLAY_MARKER", root / "BtClass100"),
        _define("FLEXISIP_CONFIG_FILE", root / "flexisip.conf"),
        _define("FLEXISIP_DOMAIN_FILE", root / "domain-registration.conf"),
        _define("FLEXISIP_USERS_DIR", users),
        _define("FLEXISIP_USERS_FILE", users / "users.db.txt"),
        _define("FLEXISIP_ACCOUNTS_FILE", users / "accounts.txt"),
        _define("FLEXISIP_ROUTE_INT_FILE", users / "route_int.conf"),
        _define("FLEXISIP_ROUTE_EXT_FILE", users / "route_ext.conf"),
        _define("FLEXISIP_ROUTE_ACTIVE_FILE", users / "route.conf"),
        _define("C300X_DEVICE_USER_ADDED_DIR", root / "backups"),
    ])
    subprocess.run(
        ["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build_dir}", f"CFLAGS={cflags}", "all"],
        check=True, capture_output=True, text=True,
    )
    return users, build_dir / "host" / "c300x-agent-native"


def _snapshot(users: Path) -> dict[str, tuple[bytes | None, str | None]]:
    return {
        path.name: (None if path.is_symlink() else path.read_bytes(),
                    str(path.readlink()) if path.is_symlink() else None)
        for path in sorted(users.iterdir())
    }


@pytest.fixture
def agent(station: tuple[Path, Path], tmp_path: Path) -> Iterator[tuple[ForwardingDevice, int, Path]]:
    users, binary = station
    for path in users.iterdir():
        path.unlink()
    (users / "users.db.txt").write_text(
        "version:1\nc100x@plant.example md5:synthetic ;\ncompanion@plant.example md5:synthetic ;\n")
    (users / "accounts.txt").write_text("App|app\nCompanion|companion\n")
    (users / "route_int.conf").write_text(OFFICIAL)
    (users / "route_ext.conf").write_text(OFFICIAL)
    with managed_tcp_server(ForwardingDevice()) as device:
        api_port, ui_port = free_tcp_ports(2)
        config = {
            "listen": {"host": "127.0.0.1", "apiPort": api_port, "uiPort": ui_port},
            "api": {"token": TOKEN},
            "openwebnet": {"host": "127.0.0.1", "port": device.server_address[1], "timeoutMs": 300},
            "maintenance": {"enabled": False},
            "activations": {"enabled": False, "autoDiscover": False},
            "events": {"udp": {"enabled": False}},
            "answeringMachine": {"messages": {"enabled": False}},
            "memos": {"enabled": False},
            "systemMetrics": {"enabled": False},
            "video": {"enabled": False},
            "displayBridge": {"enabled": False},
            "mqtt": {"enabled": False},
            "mdns": {"enabled": False},
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        with (tmp_path / "agent.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([str(binary), "--config", str(config_path)],
                                       stdout=log, stderr=log, cwd=tmp_path)
            try:
                wait_for_health(api_port)
                yield device, api_port, users
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


@pytest.mark.parametrize("mode", ["homeassistant", "enabled", "blocked"])
def test_forwarding_change_is_refused_next_to_a_foreign_route(agent, mode) -> None:
    device, port, users = agent
    (users / "route.conf").write_text(FOREIGN)
    before = _snapshot(users)
    device.frames.clear()
    response = api_post(port, FORWARDING_PATH, {"mode": mode}, expected_status=409)
    assert response == {"ok": False, "error": "foreign_active_route"}
    assert not any(frame.startswith("*#8**#37*") for frame in device.frames)
    assert _snapshot(users) == before
    assert not (users / "route.conf").is_symlink()


def test_the_vendor_link_still_allows_forwarding_changes(agent) -> None:
    device, port, users = agent
    (users / "route.conf").symlink_to("route_int.conf")
    before = _snapshot(users)
    device.frames.clear()
    device.applied_mode = 1
    response = api_post(port, FORWARDING_PATH, {"mode": "homeassistant"})
    assert response["ok"] is True and response["mode"] == "homeassistant"
    assert "*#8**#37*1##" in device.frames
    assert _snapshot(users) == before
