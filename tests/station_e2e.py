"""A station on a network, as Home Assistant reaches it: over HTTP and SSH.

The flows, the installer and HA's duplicate checks run unchanged. Only the
transports are stand-ins: the aiohttp session HA hands the integration, the
name resolution and the AsyncSSH module. Behind them sits a station of one
of the firmware profiles:

- its files live under a root folder, and the installer's shell commands run
  in a real ``sh`` with the station's absolute paths moved below that root;
- its agent answers HTTP with the configuration it loaded when the init
  script last started it, as the agent does;
- its programs (init script, display patcher, firewall script) come from the
  test bundle and record what they were asked to do.

Every HTTP request and SSH login is recorded, with the keys it carried.
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import re
import socket
import subprocess
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from custom_components.bticino_c300x import device_installer
from custom_components.bticino_c300x.const import HEADER_MAINTENANCE_TOKEN
from custom_components.bticino_c300x.discovery_move import identity_proof
from custom_components.bticino_c300x.factory_login import factory_ssh_login

AGENT_DIR = device_installer.DEFAULT_REMOTE_DIR
PAGES = "/home/bticino/bin/gui/qml/HomePage.qml"
PATCHED_PAGES = b"display pages of the integration\n"

# What differs between the stations: what they name themselves, what the
# installer finds on disk, and the factory login of the model.
PROFILES: dict[str, dict[str, Any]] = {
    "1.7.19": {"model": "C300X", "kind": "qt4_ondisk", "files": ()},
    "2.0.2": {"model": "C300X", "kind": "qt4_ondisk", "files": ()},
    "3.0.6": {"model": "C300X", "kind": "qt5_rcc", "files": ("/usr/lib/libQt5Core.so.5",)},
    "c100x-1.5.8": {
        "model": "C100X", "kind": "qt5_ondisk",
        "files": ("/usr/lib/libQt5Core.so.5", "/home/bticino/bin/gui/BtClass100"),
    },
}
FIRMWARES = tuple(PROFILES)

_STATION_PATH = re.compile(r"(?<![\w./-])(/home/bticino|/etc/|/usr/lib/)")

INIT_SCRIPT = f"""#!/bin/sh
DEFAULT_AGENT_DIR="{AGENT_DIR}"
S="$STATION_STATE"
echo "$1" >> "$S/init.log"
load() {{ cp "$STATION_ROOT$DEFAULT_AGENT_DIR/config.json" "$S/agent.loaded"; }}
case "$1" in
    stop) rm -f "$S/agent.loaded" ;;
    start) [ -f "$S/agent.loaded" ] || load ;;
    restart)
        rm -f "$S/agent.loaded"
        if [ -f "$S/fail-restart" ]; then rm -f "$S/fail-restart"; exit 1; fi
        load ;;
    status) [ -f "$S/agent.loaded" ] || exit 3 ;;
esac
exit 0
"""

QML_PATCH = f"""#!/bin/sh
echo "$1" >> "$STATION_STATE/display.log"
if [ -f "$STATION_STATE/fail-display" ]; then
    rm -f "$STATION_STATE/fail-display"
    echo '{{"ok": false}}'
    exit 0
fi
[ "$1" = apply ] && printf 'stock pages\\n' > "$STATION_ROOT{PAGES}"
overlay=""
[ -e "$STATION_ROOT/usr/lib/libQt5Core.so.5" ] && overlay=', "qt5_overlay": "active"'
echo "{{\\"ok\\": true, \\"core_patched\\": true, \\"gui_running\\": true, \\"patched\\": true$overlay}}"
"""

FIREWALL = """#!/bin/sh
echo "$1" >> "$STATION_STATE/firewall.log"
"""


def bundle(root: Path) -> Path:
    """The package the installer writes, its programs replaced by recording ones."""

    component = root / "bticino_c300x"
    agent = component / "device_agent"
    files = {
        "armhf/c300x-agent-native": "agent binary\n",
        "init/c300x-native-agent": INIT_SCRIPT,
        "scripts/qml_patch.sh": QML_PATCH,
        "scripts/remove_agent.sh": "#!/bin/sh\nexit 1\n",
        "scripts/bootstrap_firewall.sh": FIREWALL,
        "qml/c100x_bundle.sh": "#!/bin/sh\nexit 0\n",
        **{f"qml/{name}": f"{name}\n" for name in device_installer.DISPLAY_FILES},
    }
    for name, text in files.items():
        path = agent / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    binary = (agent / "armhf/c300x-agent-native").read_bytes()
    (agent / "bundle.json").write_text(json.dumps({
        "c100x_compatible": True,
        "files": [{"path": "device_agent/armhf/c300x-agent-native",
                   "sha256": hashlib.sha256(binary).hexdigest()}],
    }), encoding="utf-8")
    return component


def agent_config(api_token: str, maintenance_token: str, port: int) -> dict[str, Any]:
    """The configuration of an agent a release installed, as the station holds it."""

    config = json.loads(device_installer._device_config_json(
        api_token=api_token, maintenance_token=maintenance_token, agent_port=port,
    ))
    # Set up on the station itself; an install keeps it.
    config["mqtt"] = {"enabled": True, "host": "broker.lan"}
    return config


@dataclass
class Account:
    password: str
    uid: int = 0
    keys: tuple[str, ...] = ()


@dataclass
class Station:
    """One station: its files, its agent and its SSH accounts."""

    firmware: str
    root: Path
    state: Path
    ip: str
    device_id: str
    port: int = 8091
    accounts: dict[str, Account] = field(default_factory=dict)
    logins: list[tuple[str, str, bool]] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)

    @property
    def profile(self) -> dict[str, Any]:
        return PROFILES[self.firmware]

    @classmethod
    def with_agent(cls, base: Path, firmware: str, *, ip: str = "192.0.2.10",
                   device_id: str = "c300x-0003504a1b2c", keys: tuple[str, str] = ("old-access", "old-maint"),
                   port: int = 8091) -> Station:
        """A station with a running agent that holds ``keys``."""

        station = cls(firmware, base / f"station-{ip}", base / f"state-{ip}", ip, device_id, port)
        station.root.mkdir(parents=True)
        station.state.mkdir(parents=True)
        model = station.profile["model"]
        user, password = factory_ssh_login(model)
        station.accounts[user] = Account(password)
        station.write("/home/bticino/sp/dbfiles_ws.xml", f"<webserver_type>{model}</webserver_type>\n")
        for name in station.profile["files"]:
            station.write(name, "")
        station.write("/etc/network/if-pre-up.d/iptables", "#!/bin/sh\n", mode=0o755)
        station.write(PAGES, PATCHED_PAGES)
        init = INIT_SCRIPT.encode()
        station.write("/etc/init.d/c300x-native-agent", init, mode=0o700)
        station.path("/etc/rc5.d").mkdir(parents=True)
        os.symlink(station.path("/etc/init.d/c300x-native-agent"), station.path("/etc/rc5.d/S40c300x-native-agent"))
        station.write(f"{AGENT_DIR}/config.json", json.dumps(agent_config(*keys, port)), mode=0o600)
        station.run_init("start")
        return station

    def path(self, name: str) -> Path:
        return self.root / name.lstrip("/")

    def write(self, name: str, content: str | bytes, mode: int = 0o644) -> None:
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        path.chmod(mode)

    def env(self, uid: int) -> dict[str, str]:
        return {
            "PATH": f"{self.state / 'bin'}:/usr/bin:/bin", "STATION_ROOT": str(self.root),
            "STATION_STATE": str(self.state), "STATION_UID": str(uid), "LC_ALL": "C",
        }

    def run_init(self, action: str) -> None:
        self._stubs()
        subprocess.run(["sh", str(self.path("/etc/init.d/c300x-native-agent")), action],
                       env=self.env(0), check=True, timeout=30)

    def _stubs(self) -> None:
        stubs = self.state / "bin"
        if stubs.exists():
            return
        stubs.mkdir()
        for name, body in {"id": '[ "$1" = -u ] && echo "$STATION_UID"', "mount": "exit 0"}.items():
            (stubs / name).write_text(f"#!/bin/sh\n{body}\n")
            (stubs / name).chmod(0o755)

    def shell(self, command: str, stdin: bytes, uid: int) -> tuple[int, bytes]:
        """Run one SSH command the way the station's shell would."""

        self._stubs()
        self.commands.append(command)
        rewritten = _STATION_PATH.sub(lambda match: f"{self.root}{match.group(1)}", command)
        result = subprocess.run(["sh", "-c", rewritten], input=stdin, env=self.env(uid),
                                capture_output=True, check=False, timeout=60)
        return result.returncode, result.stdout.replace(str(self.root).encode(), b"")

    # What the station holds and did.

    def log(self, name: str) -> list[str]:
        path = self.state / f"{name}.log"
        return path.read_text().split() if path.exists() else []

    def config(self) -> dict[str, Any]:
        return json.loads(self.path(f"{AGENT_DIR}/config.json").read_text())

    def held_keys(self) -> tuple[str, str]:
        config = self.config()
        return config["api"]["token"], config["maintenance"]["adminToken"]

    def loaded(self) -> dict[str, Any] | None:
        """The configuration the running agent loaded; None when no agent runs."""

        path = self.state / "agent.loaded"
        return json.loads(path.read_text()) if path.exists() else None

    def files(self) -> dict[str, Any]:
        """Every file and link below the root, for a comparison before and after."""

        seen: dict[str, Any] = {}
        for path in sorted(self.root.rglob("*")):
            name = "/" + path.relative_to(self.root).as_posix()
            if path.is_symlink():
                seen[name] = ("link", os.readlink(path))
            elif path.is_file():
                seen[name] = (hashlib.sha256(path.read_bytes()).hexdigest(), oct(path.stat().st_mode))
        return seen

    def fail_next(self, step: str) -> None:
        (self.state / f"fail-{step}").write_text("")

    # The agent's HTTP side.

    def answer(self, method: str, path: str, headers: dict[str, str], body: Any,
               reached: tuple[str, int]) -> tuple[int, Any] | None:
        """Status and JSON of the running agent, None when nothing listens."""

        config = self.loaded()
        if config is None or reached[1] != config["listen"]["apiPort"]:
            return None
        token, admin = config["api"]["token"], config["maintenance"]["adminToken"]
        if path == "/api/v1/identity/proof" and method == "POST":
            nonce = str((body or {}).get("nonce", ""))
            return 200, {"ok": True, "id": self.device_id,
                         "proof": identity_proof(token, self.device_id, *reached, nonce)}
        if path.startswith("/api/v1/maintenance/"):
            if headers.get(HEADER_MAINTENANCE_TOKEN) != admin:
                return 403, {"error": "maintenance_unauthorized"}
            if path == "/api/v1/maintenance/auth":
                return 200, {"noAuth": False, "maintenance_enabled": True, "api_token_configured": True,
                             "maintenance_token_configured": True}
            return 200, {"ok": True, "available": False}
        if headers.get("Authorization") != f"Bearer {token}":
            return 401, {"error": "unauthorized"}
        if path == "/api/v1/capabilities":
            capabilities: dict[str, Any] = {"display_bridge": {"supported": True}}
            if self.profile["model"] == "C100X":
                capabilities["c100x_display"] = {"confirmed": False}
            return 200, {
                "api_version": "1",
                "agent": {"version": "3.0.0", "implementation": "native"},
                "device": {"id": self.device_id, "model": self.profile["model"],
                           "firmware": self.firmware.removeprefix("c100x-"),
                           "display_kind": self.profile["kind"]},
                "capabilities": capabilities,
            }
        if path == "/api/v1/events/subscriptions":
            return 200, {"subscriptions": []}
        return 404, {"error": "not_found"}


@dataclass
class Request:
    method: str
    host: str
    port: int
    path: str
    token: str
    maintenance: str


class Network:
    """Names, stations and every request that went out to them."""

    def __init__(self, monkeypatch: Any, component: Path, names: dict[str, str] | None = None) -> None:
        self.names = dict(names or {})
        self.stations: dict[str, Station] = {}
        self.requests: list[Request] = []
        self.ssh_hosts: list[str] = []
        session = _Session(self)
        import homeassistant.helpers.aiohttp_client as aiohttp_client
        import homeassistant.requirements as requirements

        from custom_components.bticino_c300x import config_flow_auth

        monkeypatch.setattr(aiohttp_client, "async_get_clientsession", lambda _hass: session)
        monkeypatch.setattr(config_flow_auth, "async_get_clientsession", lambda _hass: session)

        async def no_requirements(*_args: Any, **_kwargs: Any) -> None:
            return None

        monkeypatch.setattr(requirements, "async_process_requirements", no_requirements)
        monkeypatch.setattr(device_installer, "COMPONENT_DIR", component)
        monkeypatch.setattr(socket, "getaddrinfo", self._getaddrinfo)
        monkeypatch.setitem(__import__("sys").modules, "asyncssh", _asyncssh(self))

    def add(self, station: Station, *names: str) -> Station:
        self.stations[station.ip] = station
        for name in names:
            self.names[name] = station.ip
        return station

    def resolve(self, host: str) -> str | None:
        host = host.strip("[]")
        return self.names.get(host, host if re.fullmatch(r"[\d.]+|[0-9a-f:]+", host) else None)

    def _getaddrinfo(self, host: Any, port: Any, family: int = 0, type: int = 0, proto: int = 0,
                     flags: int = 0) -> list[Any]:
        address = self.resolve(str(host))
        if address is None or ":" in address:
            raise socket.gaierror(socket.EAI_NONAME, "unknown")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port or 0))]

    def keyed_requests(self, host: str) -> list[Request]:
        """Requests to ``host`` (as written in the URL) that carried a key."""

        return [item for item in self.requests if item.host == host and (item.token or item.maintenance)]


class _Content:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    async def iter_chunked(self, _size: int) -> Any:
        yield self._raw


class _Response:
    def __init__(self, status: int, payload: Any) -> None:
        raw = json.dumps(payload).encode()
        self.status, self.content, self.content_length = status, _Content(raw), len(raw)
        self.charset, self.headers = "utf-8", {"Content-Type": "application/json"}


class _Call:
    def __init__(self, network: Network, method: str, url: str, headers: dict[str, str] | None,
                 body: Any) -> None:
        self._network, self._method, self._url = network, method, url
        self._headers, self._body = dict(headers or {}), body

    async def __aenter__(self) -> _Response:
        parts = urlsplit(self._url)
        host, port = parts.hostname or "", parts.port or 80
        bearer = self._headers.get("Authorization", "")
        self._network.requests.append(Request(
            self._method, host, port, parts.path, bearer.removeprefix("Bearer ").strip(),
            self._headers.get(HEADER_MAINTENANCE_TOKEN, ""),
        ))
        address = self._network.resolve(host)
        station = self._network.stations.get(address or "")
        answer = None if station is None else station.answer(
            self._method, parts.path, self._headers, self._body, (address or "", port),
        )
        if answer is None:
            raise aiohttp.ClientConnectionError("connection refused")
        return _Response(*answer)

    async def __aexit__(self, *_exc: Any) -> None:
        return None


class _Session:
    def __init__(self, network: Network) -> None:
        self._network = network

    def request(self, method: str, url: str, *, headers: dict[str, str] | None = None, json: Any = None,
                **_kwargs: Any) -> _Call:
        return _Call(self._network, method, url, headers, json)


# AsyncSSH as the installer uses it.


class _Error(Exception):
    pass


class _PermissionDenied(_Error):
    pass


class _ProcessError(_Error):
    pass


class _Key:
    def __init__(self, text: str) -> None:
        self.text = text


def _import_private_key(text: str, _passphrase: Any = None) -> _Key:
    if not text.startswith("-----BEGIN OPENSSH PRIVATE KEY-----"):
        raise ValueError("not a key")
    return _Key(text.strip())


class _Stdin:
    def __init__(self) -> None:
        self.data = b""

    def write(self, data: bytes) -> None:
        self.data += data

    def write_eof(self) -> None:
        return None


class _Process:
    def __init__(self, station: Station, uid: int, command: str) -> None:
        self._station, self._uid, self._command = station, uid, command
        self.stdin = _Stdin()

    async def wait(self, check: bool = False) -> Any:
        status, stdout = self._station.shell(self._command, self.stdin.data, self._uid)
        if check and status:
            raise _ProcessError(f"exit {status}")
        return types.SimpleNamespace(stdout=stdout, exit_status=status)

    def terminate(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


class _ProcessCall:
    """``create_process`` is awaited or used as an async context manager."""

    def __init__(self, process: _Process) -> None:
        self._process = process

    def __await__(self) -> Any:
        async def done() -> _Process:
            return self._process
        return done().__await__()

    async def __aenter__(self) -> _Process:
        return self._process

    async def __aexit__(self, *_exc: Any) -> None:
        return None


class _Connection:
    def __init__(self, station: Station, uid: int) -> None:
        self._station, self._uid, self._closed = station, uid, False

    def create_process(self, command: str, **_kwargs: Any) -> _ProcessCall:
        return _ProcessCall(_Process(self._station, self._uid, command))

    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True

    async def wait_closed(self) -> None:
        return None

    def abort(self) -> None:
        self._closed = True


def _asyncssh(network: Network) -> types.ModuleType:
    module = types.ModuleType("asyncssh")

    async def connect(**options: Any) -> _Connection:
        await asyncio.sleep(0)
        host = str(options["host"])
        network.ssh_hosts.append(host)
        station = network.stations.get(network.resolve(host) or "")
        if station is None:
            raise ConnectionRefusedError(errno.ECONNREFUSED, "refused")
        user = str(options.get("username") or "")
        account = station.accounts.get(user)
        keys = [key.text for key in options.get("client_keys") or []]
        if keys and options.get("public_key_auth"):
            accepted = account is not None and any(key in account.keys for key in keys)
            station.logins.append((user, "key", accepted))
            if accepted:
                return _Connection(station, account.uid)  # type: ignore[union-attr]
        password = options.get("password")
        if password and options.get("password_auth", True):
            accepted = account is not None and account.password == password
            station.logins.append((user, "password", accepted))
            if accepted:
                return _Connection(station, account.uid)  # type: ignore[union-attr]
        raise _PermissionDenied("refused")

    module.__dict__.update(
        __version__=device_installer._REQUIRED_ASYNCSSH_VERSION, Error=_Error,
        PermissionDenied=_PermissionDenied, ProcessError=_ProcessError, connect=connect,
        import_private_key=_import_private_key,
    )
    return module
