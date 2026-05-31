"""One-shot C300X native-agent bootstrap installer.

The config flow uses this module only after the user explicitly submits SSH
credentials for a device bootstrap. Passwords stay in memory and are passed only
to the in-process SSH client, never through command arguments.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .const import DEFAULT_AGENT_PORT, DEFAULT_STAIR_LIGHT_ADDRESS

COMPONENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = COMPONENT_DIR.parents[1]
DEFAULT_REMOTE_DIR = "/home/bticino/cfg/extra/c300x-native-agent"
REMOTE_AGENT_NAME = "c300x-agent-native"
REMOTE_CONFIG_NAME = "config.json"
REMOTE_INIT_ENV_NAME = "c300x-agent.env"
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


@dataclass(frozen=True, slots=True)
class C300XDeviceInstallResult:
    """Result of a successful bootstrap install."""

    remote_dir: str
    installed_files: tuple[str, ...]


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
    ).encode("utf-8")

    await asyncio.to_thread(_install_device_agent_sync, request, bundle, config_bytes)

    return C300XDeviceInstallResult(
        remote_dir=request.remote_dir,
        installed_files=tuple(payload.remote_path for payload in bundle.payload_files)
        + (
            f"{request.remote_dir}/{REMOTE_CONFIG_NAME}",
            f"{request.remote_dir}/{REMOTE_INIT_ENV_NAME}",
            REMOTE_INIT_SCRIPT,
            REMOTE_INIT_LINK,
        ),
    )


def _install_device_agent_sync(
    request: C300XDeviceInstallRequest,
    bundle: _ResolvedBundle,
    config_bytes: bytes,
) -> None:
    """Install the device files through a Python SSH client."""

    client = _connect_device_client(request)
    try:
        client.run(f"mkdir -p {_quote(request.remote_dir)}")
        client.run(f"mkdir -p {_quote(f'{request.remote_dir}/qml/js')}")
        for payload in bundle.payload_files:
            client.put_file(payload.source, payload.remote_path, payload.mode)

        _write_remote_file_sync(
            client,
            f"{request.remote_dir}/{REMOTE_CONFIG_NAME}",
            config_bytes,
            mode="600",
        )
        _install_startup_script_sync(client, bundle.init_script, request.remote_dir)
        if request.apply_firewall_patch:
            _apply_firewall_patch_sync(client, request.agent_port)
        client.run(f"{_quote(REMOTE_INIT_SCRIPT)} restart")

        if request.apply_gui_patch:
            client.run(
                f"C300X_QML_SOURCE_DIR={_quote(f'{request.remote_dir}/qml')} "
                f"{_quote(f'{request.remote_dir}/qml_patch.sh')} apply"
            )
    finally:
        client.close()


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
    ]
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


def _device_config_json(
    *,
    api_token: str,
    maintenance_token: str,
    agent_port: int,
    remote_dir: str = DEFAULT_REMOTE_DIR,
    firewall_enabled: bool = True,
) -> str:
    qml_patch_script = f"{remote_dir}/qml_patch.sh"
    remove_agent_script = f"{remote_dir}/remove_agent.sh"
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
            "stairLightDefaultAddress": DEFAULT_STAIR_LIGHT_ADDRESS,
        },
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
            "subscriptionStorePath": (
                f"{remote_dir}/subscriptions.json"
            ),
            "callbackTimeoutMs": 2500,
            "udp": {"enabled": True, "group": "239.255.76.67", "port": 7667},
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


class _DeviceSshClient:
    """Small blocking SSH client abstraction for testable installs."""

    def run(self, command: str, input_data: bytes | None = None) -> str:
        raise NotImplementedError

    def put_file(
        self,
        source: Path,
        remote_path: str,
        mode: str | None = None,
    ) -> None:
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
    ) -> None:
        file_mode = mode or f"{stat.S_IMODE(source.stat().st_mode):04o}"
        temp_path = f"{remote_path}.new"
        self.run(
            (
                f"umask 077 && cat > {_quote(temp_path)} && "
                f"chmod {file_mode} {_quote(temp_path)} && "
                f"mv -f {_quote(temp_path)} {_quote(remote_path)}"
            ),
            source.read_bytes(),
        )

    def close(self) -> None:
        self._client.close()


def _install_startup_script_sync(
    client: _DeviceSshClient,
    source: Path,
    remote_dir: str,
) -> None:
    temp_path = f"{remote_dir}/.c300x-native-agent-init.new"
    env_path = f"{remote_dir}/{REMOTE_INIT_ENV_NAME}"
    client.run(
        f"umask 077 && cat > {_quote(temp_path)} && chmod 700 {_quote(temp_path)}",
        _render_startup_script(source, remote_dir),
    )
    client.run(
        f"umask 077 && cat > {_quote(env_path)} && chmod 644 {_quote(env_path)}",
        _render_startup_defaults(remote_dir),
    )
    client.run(
        (
            "mount -o remount,rw /; rc=$?; "
            "if [ $rc -eq 0 ]; then "
            f"chmod 700 {_quote(temp_path)} && "
            f"mv -f {_quote(temp_path)} {_quote(REMOTE_INIT_SCRIPT)} && "
            f"ln -sf {_quote(REMOTE_INIT_SCRIPT)} {_quote(REMOTE_INIT_LINK)}; "
            "rc=$?; mount -o remount,ro /; fi; exit $rc"
        ),
    )


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
) -> None:
    client.run(
        (
            f"umask 077 && cat > {_quote(f'{remote_path}.new')} && "
            f"chmod {mode} {_quote(f'{remote_path}.new')} && "
            f"mv -f {_quote(f'{remote_path}.new')} {_quote(remote_path)}"
        ),
        content,
    )


def _apply_firewall_patch_sync(client: _DeviceSshClient, api_port: int) -> None:
    """Open the API port during bootstrap so HA can verify the new agent."""

    begin = "# c300x-native-agent firewall begin"
    end = "# c300x-native-agent firewall end"
    client.run(
        f"""
set -eu
PATH=/sbin:/usr/sbin:/bin:/usr/bin
IPTABLES={_quote(REMOTE_FIREWALL_PATH)}
BACKUP={_quote(REMOTE_FIREWALL_BACKUP)}
BEGIN={_quote(begin)}
END={_quote(end)}
PORT={api_port}
TMP="/tmp/c300x-firewall.$$"
BASE="/tmp/c300x-firewall-base.$$"
ORIGINAL="/tmp/c300x-firewall-original.$$"
cleanup() {{
    rm -f "$TMP" "$BASE" "$ORIGINAL"
}}
trap cleanup EXIT
[ -f "$IPTABLES" ] || exit 1
awk -v begin="$BEGIN" -v end="$END" '
    $0 == begin {{skip = 1; next}}
    $0 == end {{skip = 0; next}}
    skip != 1 {{print}}
' "$IPTABLES" > "$BASE"
awk '
    $0 == "# c300x-native-agent firewall begin" {{skip = 1; next}}
    $0 == "# c300x-native-agent firewall end" {{skip = 0; next}}
    $0 == "# c300x-native-agent ipv6 firewall begin" {{skip = 1; next}}
    $0 == "# c300x-native-agent ipv6 firewall end" {{skip = 0; next}}
    skip != 1 {{print}}
' "$IPTABLES" > "$ORIGINAL"
cat "$BASE" > "$TMP"
if [ -s "$TMP" ] && [ "$(tail -c 1 "$TMP" 2>/dev/null)" != "" ]; then
    printf '\\n' >> "$TMP"
fi
cat >> "$TMP" <<EOF
{begin}
# Managed by c300x-native-agent. Opens only the configured API port.
if command -v iptables >/dev/null 2>&1; then
    if ! iptables -C INPUT -p tcp --dport $PORT -j ACCEPT 2>/dev/null; then
        iptables -A INPUT -p tcp --dport $PORT -j ACCEPT
    fi
fi
{end}
EOF
if [ ! -f "$BACKUP" ]; then
    mkdir -p "$(dirname "$BACKUP")"
    cp "$ORIGINAL" "$BACKUP"
    chmod 600 "$BACKUP" >/dev/null 2>&1 || true
fi
if ! cmp -s "$IPTABLES" "$TMP"; then
    mount -o remount,rw /
    cat "$TMP" > "$IPTABLES"
    chmod 755 "$IPTABLES" >/dev/null 2>&1 || true
    mount -o remount,ro /
fi
if command -v iptables >/dev/null 2>&1; then
    if ! iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null; then
        iptables -A INPUT -p tcp --dport "$PORT" -j ACCEPT
    fi
fi
""",
    )


def _ssh_host(host: str) -> str:
    clean_host = host.strip()
    if clean_host.startswith("[") and clean_host.endswith("]"):
        return clean_host[1:-1]
    return clean_host


def _quote(value: str) -> str:
    return shlex.quote(value)
