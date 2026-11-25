"""One-shot C300X native-agent bootstrap installer.

The config flow uses this module only after the user explicitly submits SSH
credentials for a device bootstrap. Passwords stay in memory and are passed only
to the in-process SSH client, never through command arguments.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import shlex
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from .activation_address import stair_light_where_from_entry_values
from .const import (
    DEFAULT_AGENT_PORT,
    DEFAULT_STAIR_LIGHT_N,
    DEFAULT_STAIR_LIGHT_P,
    DEVICE_ACTIVATION_MODE_AUTO,
    DEVICE_ACTIVATION_MODE_MANUAL,
    DOMAIN,
)
from .device_activations import desired_activation_items
from .factory_login import LOGIN_REFUSED

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

COMPONENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = COMPONENT_DIR.parents[1]
DEFAULT_REMOTE_DIR = "/home/bticino/cfg/extra/c300x-native-agent"
REMOTE_AGENT_NAME = "c300x-agent-native"
REMOTE_CONFIG_NAME = "config.json"
REMOTE_INIT_ENV_NAME = "c300x-agent.env"
REMOTE_BOOTSTRAP_FIREWALL_NAME = "bootstrap_firewall.sh"
REMOTE_INIT_SCRIPT = "/etc/init.d/c300x-native-agent"
REMOTE_INIT_LINK = "/etc/rc5.d/S40c300x-native-agent"
REMOTE_FIREWALL_PATH = "/etc/network/if-pre-up.d/iptables"
REMOTE_FIREWALL_BACKUP = (
    "/home/bticino/cfg/extra/c300x-device-file-backups/original"
    "/etc/network/if-pre-up.d/iptables"
)
_SSH_CONNECT_TIMEOUT = 12.0
# Probes, uploads of at most the agent binary, the init script and its
# restart (5 s stop wait, 2 s after SIGKILL, 20 status checks of 100 ms).
_SSH_COMMAND_TIMEOUT = 30.0
# A display write over SSH is the script the agent runs as a job, so it gets
# the agent's handling (http_maintenance.h): this deadline, then SIGTERM for
# the script's rollback trap and this grace period. The station's SSH server
# sends no signal when a channel closes; a write merely cut off would run on
# and die of SIGPIPE at its next message, in the middle of its clean-up.
_SSH_DISPLAY_WRITE_TIMEOUT = 30.0
_SSH_DISPLAY_WRITE_TERM_GRACE = 15.0
DISPLAY_WRITE_TIMEOUT = "device_display_timeout"
_REQUIRED_ASYNCSSH_VERSION = "2.24.1"
INSTALLER_REQUIREMENTS = (f"asyncssh=={_REQUIRED_ASYNCSSH_VERSION}",)
# The display files the agent directory holds; qml_patch.sh installs them.
DISPLAY_FILES = (
    "C300XRingerControl.qml",
    "js/c300x_ringer.js",
    "Alarm.qml",
    "HomeAssistant.qml",
    "C300XEnergy.qml",
    "C300XEnergyConsumers.qml",
    "js/c300x_energy_consumers.js",
    "C300XPageNavigation.qml",
    "C300XAlerts.qml",
    "js/c300x_alerts.js",
    "C300XAgenda.qml",
    "C300XLeaveHome.qml",
    "C300XChecks.qml",
    "C300XSituations.qml",
    "C300XOptionalPages.qml",
    "C300XDetailControl.qml",
    "C300XEnergyReadout.qml",
    "C300XEnergySums.qml",
    "js/c300x_energy.js",
    "js/c300x_ha.js",
    "js/c300x_i18n.js",
    "js/c300x_memos.js",
)


class C300XDeviceInstallError(Exception):
    """Raised when the device-agent bootstrap installer cannot complete."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class C300XDeviceInstallRequest:
    """Explicit one-shot bootstrap request from the config flow."""

    host: str
    ssh_username: str
    ssh_password: str
    agent_port: int = DEFAULT_AGENT_PORT
    remote_dir: str = DEFAULT_REMOTE_DIR
    apply_firewall_patch: bool = True
    apply_gui_patch: bool = False
    device_activation_mode: str = DEVICE_ACTIVATION_MODE_AUTO
    device_activation_stair_light_p: str = DEFAULT_STAIR_LIGHT_P
    device_activation_stair_light_n: str = DEFAULT_STAIR_LIGHT_N
    device_activations: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class C300XDeviceInstallResult:
    """Result of a successful bootstrap install."""

    remote_dir: str
    installed_files: tuple[str, ...]
    changed_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _PayloadFile:
    source: Path
    remote_path: str
    mode: str | None = None


async def async_install_device_agent(
    request: C300XDeviceInstallRequest,
    *,
    api_token: str,
    maintenance_token: str,
) -> C300XDeviceInstallResult:
    """Install the bundled native agent on the device through password SSH."""

    _validate_request(request)
    # About 30 Path.exists() calls: never on the event loop.
    bundle = await asyncio.to_thread(_resolve_bundle, request.remote_dir)
    config_bytes = _device_config_json(
        api_token=api_token,
        maintenance_token=maintenance_token,
        agent_port=request.agent_port,
        remote_dir=request.remote_dir,
        firewall_enabled=request.apply_firewall_patch,
        device_activation_mode=request.device_activation_mode,
        device_activation_stair_light_p=request.device_activation_stair_light_p,
        device_activation_stair_light_n=request.device_activation_stair_light_n,
        device_activations=request.device_activations,
    ).encode("utf-8")

    changed_files = await asyncio.to_thread(
        _install_device_agent_sync,
        request,
        bundle,
        config_bytes,
    )

    return C300XDeviceInstallResult(
        remote_dir=request.remote_dir,
        installed_files=tuple(payload.remote_path for payload in bundle.payload_files)
        + (
            f"{request.remote_dir}/{REMOTE_CONFIG_NAME}",
            f"{request.remote_dir}/{REMOTE_INIT_ENV_NAME}",
            REMOTE_INIT_SCRIPT,
            REMOTE_INIT_LINK,
        ),
        changed_files=changed_files,
    )


async def async_ensure_installer_dependencies(hass: HomeAssistant) -> None:
    """Install optional SSH bootstrap dependencies only when the installer is used."""

    from homeassistant.requirements import (
        RequirementsNotFound,
        async_process_requirements,
    )

    try:
        await async_process_requirements(
            hass,
            DOMAIN,
            list(INSTALLER_REQUIREMENTS),
            is_built_in=False,
        )
    except RequirementsNotFound as err:
        raise C300XDeviceInstallError("installer_dependency_missing") from err


def _install_device_agent_sync(
    request: C300XDeviceInstallRequest,
    bundle: _ResolvedBundle,
    config_bytes: bytes,
) -> tuple[str, ...]:
    """Install the device files through a Python SSH client."""

    client = _connect_device_client(request)
    changed_files: list[str] = []
    try:
        config_path = f"{request.remote_dir}/{REMOTE_CONFIG_NAME}"
        merged_config = _merge_existing_device_config(
            config_bytes, _read_remote_config_sync(client, config_path)
        )
        merged_config = _apply_qt5_low_res_video_default(client, merged_config)
        client.run(f"mkdir -p {_quote(request.remote_dir)}")
        client.run(f"mkdir -p {_quote(f'{request.remote_dir}/qml/js')}")
        manifest: _PayloadFile | None = None
        for payload in bundle.payload_files:
            if payload.remote_path == f"{request.remote_dir}/bundle.json":
                manifest = payload
                continue
            if client.put_file(payload.source, payload.remote_path, payload.mode):
                changed_files.append(payload.remote_path)

        if _write_remote_file_sync(
            client,
            config_path,
            merged_config,
            mode="600",
        ):
            changed_files.append(f"{request.remote_dir}/{REMOTE_CONFIG_NAME}")
        changed_files.extend(
            _install_startup_script_sync(client, bundle.init_script, request.remote_dir)
        )
        if request.apply_firewall_patch:
            _apply_firewall_patch_sync(client, request.remote_dir, request.agent_port)
        client.run(f"{_quote(REMOTE_INIT_SCRIPT)} restart")
        _verify_startup_sync(client)

        actions = ("core-apply", "apply") if request.apply_gui_patch else ("core-apply",)
        for action in actions:
            _apply_qml_patch_sync(client, request.remote_dir, action)
        # Capabilities reads this file on every request. Publish it only after
        # activation succeeds so an interrupted install still needs repair.
        if manifest is not None and client.put_file(
            manifest.source, manifest.remote_path, manifest.mode
        ):
            changed_files.append(manifest.remote_path)
        _remove_obsolete_display_source_sync(client, request.remote_dir)
    finally:
        client.close()
    return tuple(changed_files)


def installer_bundle_status() -> dict[str, Any]:
    """Return non-secret bundle readiness details for tests and diagnostics."""

    try:
        bundle = _resolve_bundle(DEFAULT_REMOTE_DIR)
    except C300XDeviceInstallError as err:
        return {"available": False, "reason": err.reason}
    return {
        "available": True,
        "payloads": [str(payload.source) for payload in bundle.payload_files],
        "init_script": str(bundle.init_script),
    }


def _validate_request(request: C300XDeviceInstallRequest) -> None:
    if not request.host.strip():
        raise C300XDeviceInstallError("invalid_device_host")
    if not request.ssh_username.strip():
        raise C300XDeviceInstallError("invalid_ssh_username")
    if not request.ssh_password:
        raise C300XDeviceInstallError("invalid_ssh_password")
    if request.agent_port <= 0 or request.agent_port > 65535:
        raise C300XDeviceInstallError("invalid_agent_port")
    _validate_remote_dir(request.remote_dir)


def _validate_remote_dir(remote_dir: str) -> None:
    if not remote_dir.startswith("/"):
        raise C300XDeviceInstallError("invalid_remote_dir")
    if (
        not remote_dir.strip()
        or remote_dir != remote_dir.strip()
        or "/../" in f"{remote_dir}/"
        or any(char.isspace() for char in remote_dir)
        or any(char in remote_dir for char in "\"'`$\\")
    ):
        raise C300XDeviceInstallError("invalid_remote_dir")


@dataclass(frozen=True, slots=True)
class _ResolvedBundle:
    payload_files: tuple[_PayloadFile, ...]
    init_script: Path


def _resolve_bundle(remote_dir: str) -> _ResolvedBundle:
    agent_binary = _first_existing(
        COMPONENT_DIR / "device_agent" / "armhf" / REMOTE_AGENT_NAME,
        REPO_ROOT / "native_agent" / "build" / "armhf" / REMOTE_AGENT_NAME,
    )
    init_script = _first_existing(
        COMPONENT_DIR / "device_agent" / "init" / "c300x-native-agent",
        REPO_ROOT / "custom_components" / "bticino_c300x" / "device_agent" / "init" / "c300x-native-agent",
    )
    qml_patch = _first_existing(
        COMPONENT_DIR / "device_agent" / "scripts" / "qml_patch.sh",
        REPO_ROOT / "native_agent" / "scripts" / "qml_patch.sh",
    )
    remove_agent = _first_existing(
        COMPONENT_DIR / "device_agent" / "scripts" / "remove_agent.sh",
        REPO_ROOT / "native_agent" / "scripts" / "remove_agent.sh",
    )
    bootstrap_firewall = _first_existing(
        COMPONENT_DIR / "device_agent" / "scripts" / REMOTE_BOOTSTRAP_FIREWALL_NAME,
        REPO_ROOT / "native_agent" / "scripts" / REMOTE_BOOTSTRAP_FIREWALL_NAME,
    )
    bundle_manifest = _optional_existing(COMPONENT_DIR / "device_agent" / "bundle.json")

    qml_sources = {
        f"qml/{name}": _first_existing(
            COMPONENT_DIR / "device_agent" / "qml" / name,
            REPO_ROOT / "device_qml" / name,
        )
        for name in DISPLAY_FILES
    }

    if qml_patch == REPO_ROOT / "native_agent/scripts/qml_patch.sh":
        for name in ("C300XSettings.qml", "js/c300x_maintenance.js"):
            qml_sources[f"qml/{name}"] = _first_existing(REPO_ROOT / "device_qml" / name)

    payloads = [
        _PayloadFile(agent_binary, f"{remote_dir}/{REMOTE_AGENT_NAME}", "700"),
        _PayloadFile(qml_patch, f"{remote_dir}/qml_patch.sh", "700"),
        _PayloadFile(remove_agent, f"{remote_dir}/remove_agent.sh", "700"),
        _PayloadFile(
            bootstrap_firewall,
            f"{remote_dir}/{REMOTE_BOOTSTRAP_FIREWALL_NAME}",
            "700",
        ),
    ]
    if bundle_manifest is not None:
        payloads.append(_PayloadFile(bundle_manifest, f"{remote_dir}/bundle.json", "600"))
    payloads.extend(
        _PayloadFile(source, f"{remote_dir}/{relative_path}")
        for relative_path, source in qml_sources.items()
    )
    return _ResolvedBundle(tuple(payloads), init_script)


def _first_existing(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise C300XDeviceInstallError("agent_bundle_missing")


def _optional_existing(*candidates: Path) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _device_config_json(
    *,
    api_token: str,
    maintenance_token: str,
    agent_port: int,
    remote_dir: str = DEFAULT_REMOTE_DIR,
    firewall_enabled: bool = True,
    device_activation_mode: str = DEVICE_ACTIVATION_MODE_AUTO,
    device_activation_stair_light_p: str = DEFAULT_STAIR_LIGHT_P,
    device_activation_stair_light_n: str = DEFAULT_STAIR_LIGHT_N,
    device_activations: Any = None,
) -> str:
    qml_patch_script = f"{remote_dir}/qml_patch.sh"
    remove_agent_script = f"{remote_dir}/remove_agent.sh"
    activations = _device_activation_config(
        mode=device_activation_mode,
        stair_light_p=device_activation_stair_light_p,
        stair_light_n=device_activation_stair_light_n,
        device_activations=device_activations,
    )
    config = {
        "listen": {
            "host": "0.0.0.0",
            "apiPort": agent_port,
            "uiPort": 8090,
            "allowLan": True,
        },
        "api": {
            "token": api_token,
            "noAuth": False,
        },
        "device": {
            "model": "C300X",
            "firmware": "",
            "stairLightDefaultAddress": stair_light_where_from_entry_values(
                DEFAULT_STAIR_LIGHT_P,
                DEFAULT_STAIR_LIGHT_N,
            ),
        },
        "activations": activations,
        "maintenance": {
            "enabled": True,
            "adminToken": maintenance_token,
            "sshStart": {"enabled": True},
            "reboot": {"enabled": True, "delayMs": 500},
            "agentRemove": {"enabled": True, "script": remove_agent_script},
            "guiReload": {"enabled": True, "script": qml_patch_script},
            "qmlPatch": {"enabled": True, "script": qml_patch_script},
            "firewall": {"enabled": firewall_enabled},
            "ipv6Firewall": {"enabled": False},
            "allowNoAuth": False,
        },
        "mdns": {"enabled": True, "name": "BTicino C300X"},
        "events": {
            "callbackTimeoutMs": 2500,
            "udp": {"enabled": True, "group": "239.255.76.67", "port": 7667},
        },
        "mqtt": {
            "enabled": False,
            "host": "",
            "port": 1883,
            "username": "",
            "password": "",
            "clientId": "c300x-native-agent",
            "commandHost": "127.0.0.1",
            "commandPort": 30006,
            "topics": {
                "command": "Bticino/rx",
                "event": "Bticino/tx",
                "jsonEvent": "",
                "status": "Bticino/start_date",
                "availability": "Bticino/LastWillT",
            },
            "qos": 0,
            "keepaliveSeconds": 120,
            "reconnectInitialSeconds": 30,
            "reconnectMaxSeconds": 600,
        },
        "answeringMachine": {
            "messages": {
                "enabled": True,
                "root": "/home/bticino/cfg/extra/47/messages",
                "watch": True,
                "maxMessages": 64,
            }
        },
        "memos": {
            "enabled": True,
            "textRoot": "/home/bticino/cfg/extra/47/memos_text",
            "voiceRoot": "/home/bticino/cfg/extra/47/memos_voice",
            "watch": True,
            "maxMemos": 64,
        },
        "systemMetrics": {
            "enabled": True,
            "watch": True,
            "sampleIntervalSeconds": 30,
            "heartbeatSeconds": 600,
            "changePercent": 5,
        },
        "video": {"enabled": True},
        "displayBridge": {"enabled": False},
    }
    return json.dumps(config, indent=2, sort_keys=True) + "\n"


# Sections of the agent config that Home Assistant does not own. They are set
# on the device (legacy MQTT migration, display bridge, setup page) and a
# repair reinstall must not reset them to the template defaults.
_DEVICE_OWNED_CONFIG_SECTIONS = (
    "mqtt",
    "mdns",
    "events",
    "answeringMachine",
    "memos",
    "systemMetrics",
    "video",
    "displayBridge",
)


def _read_remote_config_sync(client: _DeviceSshClient, remote_path: str) -> Any:
    # Shell only: the stock device Python has no json module. "F" precedes the
    # content of an existing path, "M" reports an absent one; a path that
    # exists but cannot be read, or a folder that cannot be searched, fails.
    path = _quote(remote_path)
    folder = _quote(remote_path.rpartition("/")[0] or "/")
    output = client.run(
        f"if [ -e {path} ] || [ -L {path} ]; then printf F && cat {path}; "
        f"elif [ -d {folder} ] && [ ! -x {folder} ]; then exit 1; "
        "else printf M; fi"
    )
    if output == "M":
        return None
    try:
        # The reply is decoded leniently. A config that is not UTF-8 would come
        # back with replacement characters and be saved that way.
        if not output.startswith("F") or "\ufffd" in output:
            raise ValueError("Invalid config read response")
        existing = json.loads(output[1:])
        if not isinstance(existing, dict):
            raise ValueError("Device config must be an object")
        return existing
    except (ValueError, TypeError) as err:
        raise C300XDeviceInstallError("device_install_failed") from err


def _merge_existing_device_config(template: bytes, existing: Any) -> bytes:
    """Return the template with the device-owned sections of the old config."""

    if not isinstance(existing, dict):
        return template
    config = json.loads(template)
    for section in _DEVICE_OWNED_CONFIG_SECTIONS:
        if isinstance(existing.get(section), dict):
            config[section] = existing[section]
    return (json.dumps(config, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _device_activation_config(
    *,
    mode: str,
    stair_light_p: str,
    stair_light_n: str,
    device_activations: Any = None,
) -> dict[str, Any]:
    """Return the native-agent activation config for a bootstrap install."""

    auto_discover = mode != DEVICE_ACTIVATION_MODE_MANUAL
    stair_light_address = stair_light_where_from_entry_values(
        stair_light_p,
        stair_light_n,
    )
    items = desired_activation_items(
        mode=mode,
        stair_light_address=stair_light_address,
        device_activations=device_activations or [],
    )
    return {
        "enabled": True,
        "autoDiscover": auto_discover,
        "discoveryRoots": [
            "/home/bticino/cfg/extra/47",
            "/home/bticino/cfg/extra",
            "/home/bticino/cfg",
        ],
        "items": items,
    }


class _DeviceSshClient:
    """Small blocking SSH client abstraction for testable installs."""

    def run(self, command: str, input_data: bytes | None = None) -> str:
        raise NotImplementedError

    def put_file(
        self,
        source: Path,
        remote_path: str,
        mode: str | None = None,
    ) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


def _connect_device_client(request: C300XDeviceInstallRequest) -> _DeviceSshClient:
    return _AsyncSshDeviceSshClient(request)


def _asyncssh_connect_kwargs(request: C300XDeviceInstallRequest) -> dict[str, Any]:
    """Return C300X SSH connect arguments with legacy RSA compatibility."""
    return {
        "host": _ssh_host(request.host),
        "port": 22,
        "username": request.ssh_username.strip(),
        "password": request.ssh_password,
        "connect_timeout": _SSH_CONNECT_TIMEOUT,
        "login_timeout": _SSH_CONNECT_TIMEOUT,
        "config": None,
        "client_keys": [],
        "agent_path": None,
        "preferred_auth": ["password"],
        "public_key_auth": False,
        "kbdint_auth": False,
        "gss_auth": False,
        "gss_kex": False,
        "host_based_auth": False,
        # LEGACY-SSH-001 in SECURITY.md: explicit local bootstrap/recovery only.
        "known_hosts": None,
        "server_host_key_algs": ["ssh-rsa"],
        "kex_algs": "+diffie-hellman-group1-sha1",
        "encryption_algs": "+aes128-cbc,3des-cbc",
    }


def _validate_asyncssh_version(asyncssh_module: Any) -> None:
    """Reject AsyncSSH versions that are not validated for the C300X SSH stack."""
    version = getattr(asyncssh_module, "__version__", "")
    if version != _REQUIRED_ASYNCSSH_VERSION:
        raise C300XDeviceInstallError("installer_dependency_missing")


class _AsyncSshDeviceSshClient(_DeviceSshClient):
    """AsyncSSH-backed SSH client which does not need HA host tools."""

    def __init__(self, request: C300XDeviceInstallRequest) -> None:
        try:
            import asyncssh
        except ImportError as err:
            raise C300XDeviceInstallError("installer_dependency_missing") from err

        _validate_asyncssh_version(asyncssh)
        self._asyncssh = asyncssh
        # The synchronous installer already runs in a worker thread. Keep one
        # private event loop/connection for the entire installation, never HA's.
        self._runner = asyncio.Runner()
        self._closed = False
        try:
            self._client = self._runner.run(self._connect(request))
        except (OSError, asyncssh.Error) as err:
            self._runner.close()
            self._closed = True
            # Nothing was changed on the device: another login can be asked for.
            if isinstance(err, getattr(asyncssh, "PermissionDenied", ())):
                raise C300XDeviceInstallError(LOGIN_REFUSED) from err
            raise C300XDeviceInstallError("device_install_failed") from err

    async def _connect(self, request: C300XDeviceInstallRequest) -> Any:
        return await self._asyncssh.connect(**_asyncssh_connect_kwargs(request))

    def run(self, command: str, input_data: bytes | None = None) -> str:
        if self._closed or self._client.is_closed():
            raise C300XDeviceInstallError("device_install_failed")
        try:
            return self._runner.run(self._run(command, input_data))
        except (OSError, self._asyncssh.Error) as err:
            raise C300XDeviceInstallError("device_install_failed") from err

    async def _run(self, command: str, input_data: bytes | None) -> str:
        # Include channel opening in the deadline and send EOF even without input.
        async with asyncio.timeout(_SSH_COMMAND_TIMEOUT):
            async with self._client.create_process(
                command, encoding=None, request_pty=False,
            ) as process:
                if input_data:
                    process.stdin.write(input_data)
                process.stdin.write_eof()
                result = await process.wait(check=True)
        return cast(bytes, result.stdout).decode("utf-8", "replace")

    def run_display_write(self, command: str) -> str:
        """Run a display write; past its deadline end it by SIGTERM, not a cut."""

        if self._closed or self._client.is_closed():
            raise C300XDeviceInstallError("device_install_failed")
        try:
            return self._runner.run(self._run_display_write(command))
        except (OSError, self._asyncssh.Error) as err:
            raise C300XDeviceInstallError("device_install_failed") from err

    async def _run_display_write(self, command: str) -> str:
        deadline = asyncio.get_running_loop().time() + _SSH_DISPLAY_WRITE_TIMEOUT
        async with asyncio.timeout_at(deadline):
            process = await self._client.create_process(
                command, encoding=None, request_pty=False,
            )
        try:
            process.stdin.write_eof()
            try:
                async with asyncio.timeout_at(deadline):
                    result = await process.wait(check=True)
            except TimeoutError:
                # The channel stays open: the trap's messages must not kill it.
                process.terminate()
                with suppress(TimeoutError):
                    async with asyncio.timeout(_SSH_DISPLAY_WRITE_TERM_GRACE):
                        await process.wait()
                raise C300XDeviceInstallError(DISPLAY_WRITE_TIMEOUT) from None
        finally:
            process.close()
            with suppress(TimeoutError):
                async with asyncio.timeout(_SSH_CONNECT_TIMEOUT):
                    await process.wait_closed()
        return cast(bytes, result.stdout).decode("utf-8", "replace")

    def put_file(
        self,
        source: Path,
        remote_path: str,
        mode: str | None = None,
    ) -> bool:
        content = source.read_bytes()
        file_mode = mode or f"{stat.S_IMODE(source.stat().st_mode):04o}"
        if _remote_content_matches_sync(self, remote_path, content):
            return _ensure_remote_mode_sync(self, remote_path, file_mode)
        self.run(_verified_upload_command(remote_path, content, file_mode), content)
        return True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._client.close()
            self._runner.run(self._wait_closed())
        finally:
            self._runner.close()

    async def _wait_closed(self) -> None:
        try:
            async with asyncio.timeout(_SSH_CONNECT_TIMEOUT):
                await self._client.wait_closed()
        except (OSError, self._asyncssh.Error):
            self._client.abort()


def _install_startup_script_sync(
    client: _DeviceSshClient,
    source: Path,
    remote_dir: str,
) -> tuple[str, ...]:
    changed_files: list[str] = []
    temp_path = _unique_temp_path(f"{remote_dir}/.c300x-native-agent-init")
    env_path = f"{remote_dir}/{REMOTE_INIT_ENV_NAME}"
    init_content = _render_startup_script(source, remote_dir)
    init_changed = not _remote_content_matches_sync(
        client,
        REMOTE_INIT_SCRIPT,
        init_content,
    )
    link_changed = not _remote_symlink_target_matches_sync(
        client,
        REMOTE_INIT_LINK,
        REMOTE_INIT_SCRIPT,
    )
    if _write_remote_file_sync(
        client,
        env_path,
        _render_startup_defaults(remote_dir),
        mode="644",
    ):
        changed_files.append(env_path)
    if init_changed:
        client.run(
            f"{{ {_verified_stage_command(temp_path, init_content, '700')}; }} "
            f"|| {{ rm -f {_quote(temp_path)}; exit 1; }}",
            init_content,
        )
    if init_changed or link_changed:
        # remote_dir can be on another filesystem. Copy beside the live init
        # first so a failed copy never truncates the script used at boot.
        init_temp_path = _unique_temp_path(REMOTE_INIT_SCRIPT)
        install_init = (
            f"rm -f {_quote(init_temp_path)} && "
            f"cp {_quote(temp_path)} {_quote(init_temp_path)} && "
            f"chmod 700 {_quote(init_temp_path)} && "
            f"mv -f {_quote(init_temp_path)} {_quote(REMOTE_INIT_SCRIPT)}; "
            "rc=$?; "
            f"rm -f {_quote(init_temp_path)} {_quote(temp_path)}; cleanup_rc=$?; "
            "if [ $rc -eq 0 ]; then rc=$cleanup_rc; fi; "
        ) if init_changed else "rc=0; "
        client.run(
            (
                "mount -o remount,rw /; rc=$?; "
                "if [ $rc -eq 0 ]; then "
                f"{install_init}"
                f"if [ $rc -eq 0 ]; then ln -sf {_quote(REMOTE_INIT_SCRIPT)} {_quote(REMOTE_INIT_LINK)}; rc=$?; fi; "
                "mount -o remount,ro /; ro_rc=$?; "
                "if [ $rc -eq 0 ]; then rc=$ro_rc; fi; fi; "
                + (f"rm -f {_quote(temp_path)}; " if init_changed else "")
                + "exit $rc"
            ),
        )
        if init_changed:
            changed_files.append(REMOTE_INIT_SCRIPT)
        if link_changed:
            changed_files.append(REMOTE_INIT_LINK)
    return tuple(changed_files)


def _render_startup_script(source: Path, remote_dir: str) -> bytes:
    content = source.read_text(encoding="utf-8")
    default_line = f'DEFAULT_AGENT_DIR="{DEFAULT_REMOTE_DIR}"'
    custom_line = f'DEFAULT_AGENT_DIR="{remote_dir}"'
    if default_line not in content:
        raise C300XDeviceInstallError("agent_bundle_missing")
    return content.replace(default_line, custom_line, 1).encode()


def _render_startup_defaults(remote_dir: str) -> bytes:
    return f"C300X_AGENT_DIR={shlex.quote(remote_dir)}\n".encode()


def _write_remote_file_sync(
    client: _DeviceSshClient,
    remote_path: str,
    content: bytes,
    *,
    mode: str,
) -> bool:
    if _remote_content_matches_sync(client, remote_path, content):
        return _ensure_remote_mode_sync(client, remote_path, mode)
    client.run(_verified_upload_command(remote_path, content, mode), content)
    return True


def _unique_temp_path(path: str) -> str:
    """Name a staging file that no other install run can share."""

    return f"{path}.c300x-{secrets.token_hex(8)}.new"


def _verified_stage_command(temp_path: str, content: bytes, mode: str) -> str:
    """Write stdin to temp_path and succeed only if it holds exactly content.

    A cut SSH stream still ends with EOF, so cat can exit 0 on a partial file.
    """

    temp = _quote(temp_path)
    return (
        f"umask 077 && cat > {temp} && sum=$(sha256sum < {temp}) && "
        f'[ "${{sum%% *}}" = {hashlib.sha256(content).hexdigest()} ] && '
        f"chmod {mode} {temp}"
    )


def _verified_upload_command(remote_path: str, content: bytes, mode: str) -> str:
    """Move a verified upload into place; never leave its staging file behind."""

    temp_path = _unique_temp_path(remote_path)
    return (
        f"{{ {_verified_stage_command(temp_path, content, mode)} && "
        f"mv -f {_quote(temp_path)} {_quote(remote_path)}; }}; "
        f"rc=$?; rm -f {_quote(temp_path)}; exit $rc"
    )


def _remote_content_matches_sync(
    client: _DeviceSshClient,
    remote_path: str,
    content: bytes,
) -> bool:
    """Return true when the remote file already has exactly this content."""

    remote_hash = _remote_sha256_sync(client, remote_path)
    return remote_hash == hashlib.sha256(content).hexdigest()


def _remote_sha256_sync(client: _DeviceSshClient, remote_path: str) -> str | None:
    # sha256sum, not Python: the stock device Python has no hashlib module.
    try:
        output = client.run(f"sha256sum {_quote(remote_path)}")
    except C300XDeviceInstallError:
        return None
    remote_hash = output.split()[0] if output.split() else ""
    if len(remote_hash) != 64 or any(char not in "0123456789abcdef" for char in remote_hash):
        return None
    return remote_hash


def _ensure_remote_mode_sync(
    client: _DeviceSshClient,
    remote_path: str,
    mode: str,
) -> bool:
    """Ensure mode on an already-matching remote file."""

    if _remote_mode_matches_sync(client, remote_path, mode):
        return False
    client.run(f"chmod {mode} {_quote(remote_path)}")
    return True


def _remote_mode_matches_sync(
    client: _DeviceSshClient,
    remote_path: str,
    mode: str,
) -> bool:
    """Return true when the remote file mode already matches."""

    desired = mode.lstrip("0") or "0"
    try:
        output = client.run(f"stat -c %a {_quote(remote_path)}")
    except C300XDeviceInstallError:
        return False
    current = output.strip().splitlines()[-1].lstrip("0") if output.strip() else ""
    return current == desired


def _remote_symlink_target_matches_sync(
    client: _DeviceSshClient,
    remote_path: str,
    target_path: str,
) -> bool:
    """Return true when the remote symlink already targets the desired path."""

    try:
        output = client.run(f"readlink {_quote(remote_path)}")
    except C300XDeviceInstallError:
        return False
    return output.strip().splitlines()[-1:] == [target_path]


def _verify_startup_sync(client: _DeviceSshClient) -> None:
    """Verify that the freshly installed agent is running and boot-persistent."""

    try:
        link_target = client.run(f"readlink {_quote(REMOTE_INIT_LINK)}")
    except C300XDeviceInstallError as err:
        raise C300XDeviceInstallError("device_install_verify_failed") from err
    if link_target.strip().splitlines()[-1:] != [REMOTE_INIT_SCRIPT]:
        raise C300XDeviceInstallError("device_install_verify_failed")
    try:
        client.run(f"{_quote(REMOTE_INIT_SCRIPT)} status")
    except C300XDeviceInstallError as err:
        raise C300XDeviceInstallError("device_install_verify_failed") from err


def _remove_obsolete_display_source_sync(client: _DeviceSshClient, remote_dir: str) -> None:
    """Retire only the old generated source, after the install has committed."""

    directory = _quote(f"{remote_dir}/qml")
    target = _quote(f"{remote_dir}/qml/C300XEnergyDistribution.qml")
    client.run(
        f"if [ -L {directory} ] || [ -L {target} ] || "
        f"{{ [ -e {target} ] && [ ! -f {target} ]; }}; then exit 1; fi; "
        f"if [ -f {target} ]; then rm -f {target}; fi"
    )


_LOGGER = logging.getLogger(__name__)

# Firmware 3.0.x has a Qt 5 display with its QML built into the BtClass program
# (qrc:/skins/default/...), so there are no files for the Display patch. The
# earlier ones have Qt 4 and QML files on disk. The Qt 5 library is the mark,
# not a missing QML folder: on an older device a missing folder is a fault the
# Display patch has to report.
_QT5_DISPLAY_MARKER = "/usr/lib/libQt5Core.so.5"


def _device_display_is_qt5(client: _DeviceSshClient) -> bool:
    """Return whether the device has the Qt 5 display, which cannot be patched."""

    output = client.run(f"test -e {_quote(_QT5_DISPLAY_MARKER)} && echo yes || echo no")
    return output.strip().splitlines()[-1:] == ["yes"]


def _apply_qt5_low_res_video_default(
    client: _DeviceSshClient, config_bytes: bytes
) -> bytes:
    """Fix the camera to the low-res stream on Qt5 firmware (3.0.x+).

    bt_av_media only fans out the low-res video branch (``multiudp_low_res``);
    the high-res branch has no ``multiudpsink``, so its stream never reaches the
    agent and clients get an undecodable picture. Qt4 firmware (1.7.x/2.0.x)
    keeps its setting, high-res by default. The agent also enforces low-res
    there; the config states it so it matches what the device does.
    """

    if not _device_display_is_qt5(client):
        return config_bytes
    try:
        config = json.loads(config_bytes)
    except (ValueError, TypeError):
        return config_bytes
    if not isinstance(config, dict):
        return config_bytes
    video = config.get("video")
    if not isinstance(video, dict):
        video = {}
        config["video"] = video
    av = video.get("av")
    if not isinstance(av, dict):
        av = {}
        video["av"] = av
    if av.get("highResolution") is False:
        return config_bytes
    av["highResolution"] = False
    _LOGGER.info(
        "C300X: Qt5 firmware detected; camera fixed to low-res "
        "(video.av.highResolution=false)"
    )
    return (json.dumps(config, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _apply_qml_patch_sync(client: _DeviceSshClient, remote_dir: str, action: str) -> None:
    """Require the patcher's reported outcome, not just a successful shell exit."""

    if _device_display_is_qt5(client):
        # Qt5 firmware (3.0.x+) has no on-disk QML to patch. Skip rather than
        # abort the whole install: the on-device display pages and ringer-sync
        # are unavailable, but camera, door, stair light, ring and calls work
        # through the agent API and do not depend on the QML hook.
        _LOGGER.warning(
            "C300X: device has no on-disk QML (Qt5 GUI); skipping %s patch", action
        )
        return
    # exec: the signal the SSH server delivers must reach the script itself.
    # The assignment prefix reaches the exec'd script without an env binary.
    command = (
        f"C300X_QML_SOURCE_DIR={_quote(f'{remote_dir}/qml')} "
        f"exec {_quote(f'{remote_dir}/qml_patch.sh')} {action}"
    )
    run_display_write = getattr(client, "run_display_write", client.run)
    output = run_display_write(command)
    try:
        result = json.loads(output)
    except (TypeError, ValueError) as err:
        raise C300XDeviceInstallError("device_install_verify_failed") from err
    if (
        not isinstance(result, dict)
        or result.get("ok") is not True
        or result.get("core_patched") is not True
        or result.get("gui_running") is not True
        or (action == "apply" and result.get("patched") is not True)
    ):
        raise C300XDeviceInstallError("device_install_verify_failed")


def _apply_firewall_patch_sync(
    client: _DeviceSshClient,
    remote_dir: str,
    api_port: int,
) -> None:
    """Open the API port during bootstrap so HA can verify the new agent."""

    client.run(
        (
            f"C300X_IPTABLES={_quote(REMOTE_FIREWALL_PATH)} "
            f"C300X_IPTABLES_BACKUP={_quote(REMOTE_FIREWALL_BACKUP)} "
            f"{_quote(f'{remote_dir}/{REMOTE_BOOTSTRAP_FIREWALL_NAME}')} "
            f"{api_port}"
        ),
    )


def _ssh_host(host: str) -> str:
    clean_host = host.strip()
    if clean_host.startswith("[") and clean_host.endswith("]"):
        return clean_host[1:-1]
    return clean_host


def _quote(value: str) -> str:
    return shlex.quote(value)
