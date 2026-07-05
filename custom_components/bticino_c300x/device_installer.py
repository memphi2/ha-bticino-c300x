"""One-shot C300X native-agent bootstrap installer.

The config flow uses this module only after the user explicitly submits SSH
credentials for a device bootstrap. Passwords stay in memory and are passed only
to the in-process SSH client, never through command arguments.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shlex
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
_SSH_COMMAND_TIMEOUT = 30.0
_REQUIRED_PARAMIKO_VERSION = "3.5.1"
INSTALLER_REQUIREMENTS = (f"paramiko=={_REQUIRED_PARAMIKO_VERSION}",)
_LEGACY_RSA_SHA2_ALGORITHMS = ("rsa-sha2-512", "rsa-sha2-256")


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
    bundle = _resolve_bundle(request.remote_dir)
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
        client.run(f"mkdir -p {_quote(request.remote_dir)}")
        client.run(f"mkdir -p {_quote(f'{request.remote_dir}/qml/js')}")
        for payload in bundle.payload_files:
            if client.put_file(payload.source, payload.remote_path, payload.mode):
                changed_files.append(payload.remote_path)

        if _write_remote_file_sync(
            client,
            f"{request.remote_dir}/{REMOTE_CONFIG_NAME}",
            config_bytes,
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

        client.run(
            f"C300X_QML_SOURCE_DIR={_quote(f'{request.remote_dir}/qml')} "
            f"{_quote(f'{request.remote_dir}/qml_patch.sh')} core-apply"
        )
        if request.apply_gui_patch:
            client.run(
                f"C300X_QML_SOURCE_DIR={_quote(f'{request.remote_dir}/qml')} "
                f"{_quote(f'{request.remote_dir}/qml_patch.sh')} apply"
            )
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
        "qml/Alarm.qml": _first_existing(
            COMPONENT_DIR / "device_agent" / "qml" / "Alarm.qml",
            REPO_ROOT / "device_qml" / "Alarm.qml",
        ),
        "qml/HomeAssistant.qml": _first_existing(
            COMPONENT_DIR / "device_agent" / "qml" / "HomeAssistant.qml",
            REPO_ROOT / "device_qml" / "HomeAssistant.qml",
        ),
        "qml/js/c300x_ha.js": _first_existing(
            COMPONENT_DIR / "device_agent" / "qml" / "js" / "c300x_ha.js",
            REPO_ROOT / "device_qml" / "js" / "c300x_ha.js",
        ),
        "qml/js/c300x_i18n.js": _first_existing(
            COMPONENT_DIR / "device_agent" / "qml" / "js" / "c300x_i18n.js",
            REPO_ROOT / "device_qml" / "js" / "c300x_i18n.js",
        ),
        "qml/js/c300x_memos.js": _first_existing(
            COMPONENT_DIR / "device_agent" / "qml" / "js" / "c300x_memos.js",
            REPO_ROOT / "device_qml" / "js" / "c300x_memos.js",
        ),
    }

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
    return _ParamikoDeviceSshClient(request)


def _paramiko_connect_kwargs(request: C300XDeviceInstallRequest) -> dict[str, Any]:
    """Return C300X SSH connect arguments with legacy RSA compatibility."""
    return {
        "hostname": _ssh_host(request.host),
        "port": 22,
        "username": request.ssh_username.strip(),
        "password": request.ssh_password,
        "timeout": _SSH_CONNECT_TIMEOUT,
        "auth_timeout": _SSH_CONNECT_TIMEOUT,
        "banner_timeout": _SSH_CONNECT_TIMEOUT,
        "look_for_keys": False,
        "allow_agent": False,
        "disabled_algorithms": {
            # The C300X SSH stack is old and must be allowed to fall back to
            # ssh-rsa instead of Paramiko's newer RSA-SHA2 preference.
            "keys": _LEGACY_RSA_SHA2_ALGORITHMS,
            "pubkeys": _LEGACY_RSA_SHA2_ALGORITHMS,
        },
    }


def _validate_paramiko_version(paramiko_module: Any) -> None:
    """Reject Paramiko versions that are not validated for the C300X SSH stack."""
    version = getattr(paramiko_module, "__version__", "")
    if version != _REQUIRED_PARAMIKO_VERSION:
        raise C300XDeviceInstallError("installer_dependency_missing")


class _ParamikoDeviceSshClient(_DeviceSshClient):
    """Paramiko-backed SSH client which does not need HA host tools."""

    def __init__(self, request: C300XDeviceInstallRequest) -> None:
        try:
            import paramiko
        except ImportError as err:
            raise C300XDeviceInstallError("installer_dependency_missing") from err

        _validate_paramiko_version(paramiko)
        self._paramiko = paramiko
        self._client = paramiko.SSHClient()

        # The rooted C300X regenerates its SSH host key across reboots, so
        # host-key pinning is not stable. This installer is an optional local
        # bootstrap path and never used for normal agent runtime.
        # codeql[py/paramiko-missing-host-key-validation]
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self._client.connect(**_paramiko_connect_kwargs(request))
        except (
            OSError,
            TimeoutError,
            paramiko.AuthenticationException,
            paramiko.SSHException,
        ) as err:
            raise C300XDeviceInstallError("device_install_failed") from err

    def run(self, command: str, input_data: bytes | None = None) -> str:
        transport = self._client.get_transport()
        if transport is None or not transport.is_active():
            raise C300XDeviceInstallError("device_install_failed")
        channel = transport.open_session(timeout=_SSH_COMMAND_TIMEOUT)
        channel.settimeout(_SSH_COMMAND_TIMEOUT)
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        try:
            channel.exec_command(command)
            if input_data is not None:
                channel.sendall(input_data)
            channel.shutdown_write()
            while True:
                while channel.recv_ready():
                    stdout_chunks.append(channel.recv(65536))
                while channel.recv_stderr_ready():
                    stderr_chunks.append(channel.recv_stderr(65536))
                if channel.exit_status_ready():
                    returncode = channel.recv_exit_status()
                    while channel.recv_ready():
                        stdout_chunks.append(channel.recv(65536))
                    while channel.recv_stderr_ready():
                        stderr_chunks.append(channel.recv_stderr(65536))
                    break
                time.sleep(0.01)
        except (OSError, TimeoutError, self._paramiko.SSHException) as err:
            raise C300XDeviceInstallError("device_install_failed") from err
        finally:
            channel.close()
        if returncode != 0:
            raise C300XDeviceInstallError("device_install_failed")
        return b"".join(stdout_chunks).decode("utf-8", "replace")

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
        temp_path = f"{remote_path}.new"
        self.run(
            (
                f"umask 077 && cat > {_quote(temp_path)} && "
                f"chmod {file_mode} {_quote(temp_path)} && "
                f"mv -f {_quote(temp_path)} {_quote(remote_path)}"
            ),
            content,
        )
        return True

    def close(self) -> None:
        self._client.close()


def _install_startup_script_sync(
    client: _DeviceSshClient,
    source: Path,
    remote_dir: str,
) -> tuple[str, ...]:
    changed_files: list[str] = []
    temp_path = f"{remote_dir}/.c300x-native-agent-init.new"
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
            f"umask 077 && cat > {_quote(temp_path)} && chmod 700 {_quote(temp_path)}",
            init_content,
        )
    if init_changed or link_changed:
        install_init = (
            f"chmod 700 {_quote(temp_path)} && "
            f"mv -f {_quote(temp_path)} {_quote(REMOTE_INIT_SCRIPT)}; "
            "rc=$?; "
        ) if init_changed else "rc=0; "
        client.run(
            (
                "mount -o remount,rw /; rc=$?; "
                "if [ $rc -eq 0 ]; then "
                f"{install_init}"
                f"if [ $rc -eq 0 ]; then ln -sf {_quote(REMOTE_INIT_SCRIPT)} {_quote(REMOTE_INIT_LINK)}; rc=$?; fi; "
                "mount -o remount,ro /; fi; exit $rc"
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
    client.run(
        (
            f"umask 077 && cat > {_quote(f'{remote_path}.new')} && "
            f"chmod {mode} {_quote(f'{remote_path}.new')} && "
            f"mv -f {_quote(f'{remote_path}.new')} {_quote(remote_path)}"
        ),
        content,
    )
    return True


def _remote_content_matches_sync(
    client: _DeviceSshClient,
    remote_path: str,
    content: bytes,
) -> bool:
    """Return true when the remote file already has exactly this content."""

    remote_hash = _remote_sha256_sync(client, remote_path)
    return remote_hash == hashlib.sha256(content).hexdigest()


def _remote_sha256_sync(client: _DeviceSshClient, remote_path: str) -> str | None:
    script = (
        "import hashlib, sys\n"
        "path = sys.argv[1]\n"
        "h = hashlib.sha256()\n"
        "with open(path, 'rb') as handle:\n"
        "    for chunk in iter(lambda: handle.read(65536), b''):\n"
        "        h.update(chunk)\n"
        "print(h.hexdigest())\n"
    )
    try:
        output = client.run(f"python - {_quote(remote_path)}", script.encode())
    except C300XDeviceInstallError:
        return None
    remote_hash = output.strip().splitlines()[-1] if output.strip() else ""
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
