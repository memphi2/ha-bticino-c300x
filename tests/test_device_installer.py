from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

custom_components = sys.modules.setdefault(
    "custom_components",
    types.ModuleType("custom_components"),
)
custom_components.__path__ = [str(ROOT / "custom_components")]
bticino_package = types.ModuleType("custom_components.bticino_c300x")
bticino_package.__path__ = [str(ROOT / "custom_components" / "bticino_c300x")]
bticino_package = sys.modules.setdefault(
    "custom_components.bticino_c300x",
    bticino_package,
)
custom_components.bticino_c300x = bticino_package

import custom_components.bticino_c300x.device_installer as device_installer  # noqa: E402
from custom_components.bticino_c300x.const import (  # noqa: E402
    DEVICE_ACTIVATION_MODE_MANUAL,
)
from custom_components.bticino_c300x.device_installer import (  # noqa: E402
    DEFAULT_REMOTE_DIR,
    INSTALLER_REQUIREMENTS,
    C300XDeviceInstallError,
    C300XDeviceInstallRequest,
    _device_config_json,
    _render_startup_defaults,
    async_ensure_installer_dependencies,
    async_install_device_agent,
    installer_bundle_status,
)


async def _to_thread_inline(func: Any, /, *args: Any, **kwargs: Any) -> Any:
    return func(*args, **kwargs)


def test_bootstrap_device_config_generates_token_auth_without_noauth() -> None:
    config = json.loads(
        _device_config_json(
            api_token="api-token",
            maintenance_token="maintenance-token",
            agent_port=8091,
        )
    )

    assert config["listen"]["host"] == "0.0.0.0"
    assert config["listen"]["allowLan"] is True
    assert config["api"] == {"token": "api-token", "noAuth": False}
    assert config["maintenance"]["adminToken"] == "maintenance-token"
    assert config["maintenance"]["allowNoAuth"] is False
    assert config["maintenance"]["sshStart"]["enabled"] is True
    assert config["maintenance"]["reboot"]["enabled"] is True
    assert config["maintenance"]["agentRemove"] == {
        "enabled": True,
        "script": f"{DEFAULT_REMOTE_DIR}/remove_agent.sh",
    }
    assert config["maintenance"]["guiReload"] == {
        "enabled": True,
        "script": f"{DEFAULT_REMOTE_DIR}/qml_patch.sh",
    }
    assert config["maintenance"]["qmlPatch"] == {
        "enabled": True,
        "script": f"{DEFAULT_REMOTE_DIR}/qml_patch.sh",
    }
    assert config["maintenance"]["firewall"] == {"enabled": True}
    assert config["activations"]["enabled"] is True
    assert config["activations"]["autoDiscover"] is True
    assert config["activations"]["items"] == []
    assert config["mqtt"] == {
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
    }
    assert config["video"]["enabled"] is True
    assert config["displayBridge"]["enabled"] is False


def test_installer_bundle_uses_built_agent_without_running_make() -> None:
    status = installer_bundle_status()

    if status["available"]:
        payloads = status["payloads"]
        assert any(payload.endswith("/c300x-agent-native") for payload in payloads)
        assert any(payload.endswith("/qml_patch.sh") for payload in payloads)
        assert any(payload.endswith("/remove_agent.sh") for payload in payloads)
        assert any(payload.endswith("/bootstrap_firewall.sh") for payload in payloads)
        assert status["init_script"].endswith("/c300x-native-agent")
        assert any(payload.endswith("/Alarm.qml") for payload in payloads)
    else:
        assert status["reason"] == "agent_bundle_missing"


def test_bootstrap_paths_follow_configured_device_agent_dir() -> None:
    remote_dir = "/home/bticino/cfg/extra/custom-agent"
    config = json.loads(
        _device_config_json(
            api_token="api-token",
            maintenance_token="maintenance-token",
            agent_port=8091,
            remote_dir=remote_dir,
        )
    )

    assert "subscriptionStorePath" not in config["events"]
    assert config["maintenance"]["qmlPatch"]["script"] == f"{remote_dir}/qml_patch.sh"
    assert config["maintenance"]["agentRemove"]["script"] == f"{remote_dir}/remove_agent.sh"


def test_bootstrap_device_config_supports_manual_stair_light_activation() -> None:
    config = json.loads(
        _device_config_json(
            api_token="api-token",
            maintenance_token="maintenance-token",
            agent_port=8091,
            device_activation_mode=DEVICE_ACTIVATION_MODE_MANUAL,
            device_activation_stair_light_p="01",
            device_activation_stair_light_n="02",
        )
    )

    assert config["activations"]["enabled"] is True
    assert config["activations"]["autoDiscover"] is False
    assert config["activations"]["items"] == [
        {
            "address": "12",
            "addressMode": "manual",
            "id": "stair_light",
            "name": "Stair light",
            "type": "stair_light",
        }
    ]


def test_bootstrap_device_config_supports_additional_activation_items() -> None:
    config = json.loads(
        _device_config_json(
            api_token="api-token",
            maintenance_token="maintenance-token",
            agent_port=8091,
            device_activations=[
                {
                    "id": "front_lock",
                    "name": "Front lock",
                    "type": "lock",
                    "address": "10",
                }
            ],
        )
    )

    assert config["activations"]["enabled"] is True
    assert config["activations"]["autoDiscover"] is True
    assert config["activations"]["items"] == [
        {
            "address": "10",
            "addressMode": "manual",
            "id": "front_lock",
            "name": "Front lock",
            "type": "lock",
        }
    ]


def test_bootstrap_request_validation_rejects_unsafe_inputs() -> None:
    invalid_requests = [
        (
            C300XDeviceInstallRequest(
                host=" ",
                ssh_username="root",
                ssh_password="secret",
            ),
            "invalid_device_host",
        ),
        (
            C300XDeviceInstallRequest(
                host="c300x.local",
                ssh_username=" ",
                ssh_password="secret",
            ),
            "invalid_ssh_username",
        ),
        (
            C300XDeviceInstallRequest(
                host="c300x.local",
                ssh_username="root",
                ssh_password="",
            ),
            "invalid_ssh_password",
        ),
        (
            C300XDeviceInstallRequest(
                host="c300x.local",
                ssh_username="root",
                ssh_password="secret",
                agent_port=0,
            ),
            "invalid_agent_port",
        ),
        (
            C300XDeviceInstallRequest(
                host="c300x.local",
                ssh_username="root",
                ssh_password="secret",
                remote_dir="/home/bticino/cfg/extra/bad path",
            ),
            "invalid_remote_dir",
        ),
    ]

    for request, reason in invalid_requests:
        try:
            device_installer._validate_request(request)
        except C300XDeviceInstallError as err:
            assert err.reason == reason
        else:
            raise AssertionError(f"{reason} was accepted")


def test_bootstrap_remote_dir_validation_rejects_traversal_and_shell_chars() -> None:
    for remote_dir in (
        "relative/path",
        "/home/bticino/cfg/extra/../bad",
        "/home/bticino/cfg/extra/bad`cmd`",
        "/home/bticino/cfg/extra/bad$var",
        "/home/bticino/cfg/extra/bad\\path",
        " /home/bticino/cfg/extra/c300x-native-agent",
    ):
        try:
            device_installer._validate_remote_dir(remote_dir)
        except C300XDeviceInstallError as err:
            assert err.reason == "invalid_remote_dir"
        else:
            raise AssertionError(f"{remote_dir!r} was accepted")


def test_startup_defaults_use_configured_device_agent_dir() -> None:
    content = _render_startup_defaults(
        "/home/bticino/cfg/extra/custom-agent",
    ).decode()

    assert content == "C300X_AGENT_DIR=/home/bticino/cfg/extra/custom-agent\n"
    assert DEFAULT_REMOTE_DIR not in content


def test_bootstrap_install_uses_python_ssh_client(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    # Exercise shared Qt4 installation mechanics, not C100X branch admission.
    monkeypatch.setattr(device_installer, "_admit_station_sync", lambda *_: "qt4_ondisk")
    remote_dir = "/home/bticino/cfg/extra/custom-agent"

    class FakeSshClient:
        def __init__(self) -> None:
            self.commands: list[tuple[str, bytes | None]] = []
            self.uploads: list[tuple[str, str, str | None]] = []
            self.closed = False

        def run(self, command: str, input_data: bytes | None = None) -> str:
            self.commands.append((command, input_data))
            if command.startswith("if [ -e "):
                assert len(self.commands) == 1
                assert not self.uploads
                return "M"
            if command == f"readlink {device_installer.REMOTE_INIT_LINK}":
                return f"{device_installer.REMOTE_INIT_SCRIPT}\n"
            if "qml_patch.sh " in command:
                return json.dumps({
                    "ok": True, "core_patched": True, "gui_running": True,
                    "patched": command.endswith(" apply"),
                })
            return ""

        def put_file(
            self,
            source: Path,
            remote_path: str,
            mode: str | None = None,
        ) -> bool:
            self.uploads.append((source.name, remote_path, mode))
            return True

        def close(self) -> None:
            self.closed = True

    agent = tmp_path / "c300x-agent-native"
    qml_patch = tmp_path / "qml_patch.sh"
    remove_agent = tmp_path / "remove_agent.sh"
    bootstrap_firewall = tmp_path / "bootstrap_firewall.sh"
    init_script = tmp_path / "c300x-native-agent"
    alarm_qml = tmp_path / "Alarm.qml"
    for path in (agent, qml_patch, remove_agent, bootstrap_firewall, alarm_qml):
        path.write_text("payload", encoding="utf-8")
    init_script.write_text(
        '#!/bin/sh\n'
        f'DEFAULT_AGENT_DIR="{DEFAULT_REMOTE_DIR}"\n'
        'AGENT_ENV="${C300X_AGENT_ENV:-$DEFAULT_AGENT_DIR/c300x-agent.env}"\n'
        '[ -r "$AGENT_ENV" ] && . "$AGENT_ENV"\n'
        'AGENT_DIR="${C300X_AGENT_DIR:-${AGENT_DIR:-$DEFAULT_AGENT_DIR}}"\n'
        'exec "$AGENT_DIR/c300x-agent-native"\n',
        encoding="utf-8",
    )
    bundle = device_installer._ResolvedBundle(
        (
            device_installer._PayloadFile(
                agent,
                f"{remote_dir}/c300x-agent-native",
                "700",
            ),
            device_installer._PayloadFile(
                qml_patch,
                f"{remote_dir}/qml_patch.sh",
                "700",
            ),
            device_installer._PayloadFile(
                remove_agent,
                f"{remote_dir}/remove_agent.sh",
                "700",
            ),
            device_installer._PayloadFile(
                bootstrap_firewall,
                f"{remote_dir}/bootstrap_firewall.sh",
                "700",
            ),
            device_installer._PayloadFile(
                alarm_qml,
                f"{remote_dir}/qml/Alarm.qml",
                None,
            ),
        ),
        init_script,
    )
    fake_client = FakeSshClient()
    monkeypatch.setattr(device_installer, "_resolve_bundle", lambda _remote_dir: bundle)
    monkeypatch.setattr(
        device_installer,
        "_connect_device_client",
        lambda _request: fake_client,
    )
    monkeypatch.setattr(device_installer.asyncio, "to_thread", _to_thread_inline)

    result = asyncio.run(
        async_install_device_agent(
            C300XDeviceInstallRequest(
                host="c300x.local",
                ssh_username="root",
                ssh_password="secret",
                remote_dir=remote_dir,
                apply_gui_patch=True,
            ),
            api_token="api-token",
            maintenance_token="maintenance-token",
        )
    )

    assert fake_client.closed is True
    assert (
        "c300x-agent-native",
        f"{remote_dir}/c300x-agent-native",
        "700",
    ) in fake_client.uploads
    init_write = next(
        command
        for command in fake_client.commands
        if command[1] and b"DEFAULT_AGENT_DIR" in command[1]
    )
    assert re.search(rf"{remote_dir}/\.c300x-native-agent-init\.c300x-[0-9a-f]{{16}}\.new", init_write[0])
    assert f'DEFAULT_AGENT_DIR="{remote_dir}"'.encode() in init_write[1]
    assert DEFAULT_REMOTE_DIR.encode() not in init_write[1]
    defaults_write = next(
        command
        for command in fake_client.commands
        if command[1] and b"C300X_AGENT_DIR=" in command[1]
    )
    assert f"{remote_dir}/c300x-agent.env" in defaults_write[0]
    assert remote_dir.encode() in defaults_write[1]
    config_write = next(
        command for command in fake_client.commands if command[1] and b"api-token" in command[1]
    )
    assert f"{remote_dir}/config.json.c300x-" in config_write[0]
    assert any(command[0] == "/etc/init.d/c300x-native-agent restart" for command in fake_client.commands)
    assert any(command[0] == f"readlink {device_installer.REMOTE_INIT_LINK}" for command in fake_client.commands)
    assert any(command[0] == f"{device_installer.REMOTE_INIT_SCRIPT} status" for command in fake_client.commands)
    assert any(
        command[0]
        == (
            f"C300X_QML_SOURCE_DIR={remote_dir}/qml "
            f"exec {remote_dir}/qml_patch.sh core-apply"
        )
        for command in fake_client.commands
    )
    assert any(
        command[0]
        == (
            "C300X_IPTABLES=/etc/network/if-pre-up.d/iptables "
            "C300X_IPTABLES_BACKUP=/home/bticino/cfg/extra/c300x-device-file-backups/original"
            "/etc/network/if-pre-up.d/iptables "
            f"{remote_dir}/bootstrap_firewall.sh 8091{FIREWALL_STATUS_TAIL}"
        )
        for command in fake_client.commands
    )
    assert any(
        command[0]
        == (
            f"C300X_QML_SOURCE_DIR={remote_dir}/qml "
            f"exec {remote_dir}/qml_patch.sh apply"
        )
        for command in fake_client.commands
    )
    assert f"{remote_dir}/config.json" in result.installed_files
    assert f"{remote_dir}/c300x-agent.env" in result.installed_files
    assert f"{remote_dir}/config.json" in result.changed_files
    assert device_installer.REMOTE_INIT_SCRIPT in result.changed_files


def test_bootstrap_install_fails_when_startup_link_is_missing(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    # Admission has its own real-stager tests; inject failure after that boundary.
    monkeypatch.setattr(device_installer, "_admit_station_sync", lambda *_: "qt4_ondisk")
    remote_dir = "/home/bticino/cfg/extra/custom-agent"

    class FakeSshClient:
        def run(self, command: str, input_data: bytes | None = None) -> str:
            if command.startswith("if [ -e "):
                return "M"
            if command == f"readlink {device_installer.REMOTE_INIT_LINK}":
                return ""
            return ""

        def put_file(
            self,
            source: Path,
            remote_path: str,
            mode: str | None = None,
        ) -> bool:
            return True

        def close(self) -> None:
            pass

    payload = tmp_path / "payload"
    payload.write_text("payload", encoding="utf-8")
    init_script = tmp_path / "c300x-native-agent"
    init_script.write_text(
        '#!/bin/sh\n'
        f'DEFAULT_AGENT_DIR="{DEFAULT_REMOTE_DIR}"\n',
        encoding="utf-8",
    )
    bundle = device_installer._ResolvedBundle(
        (device_installer._PayloadFile(payload, f"{remote_dir}/c300x-agent-native", "700"),),
        init_script,
    )
    monkeypatch.setattr(device_installer, "_resolve_bundle", lambda _remote_dir: bundle)
    monkeypatch.setattr(
        device_installer,
        "_connect_device_client",
        lambda _request: FakeSshClient(),
    )
    monkeypatch.setattr(device_installer.asyncio, "to_thread", _to_thread_inline)

    try:
        asyncio.run(
            async_install_device_agent(
                C300XDeviceInstallRequest(
                    host="c300x.local",
                    ssh_username="root",
                    ssh_password="secret",
                    remote_dir=remote_dir,
                ),
                api_token="api-token",
                maintenance_token="maintenance-token",
            )
        )
    except device_installer.C300XDeviceInstallError as err:
        assert err.reason == "device_install_verify_failed"
    else:
        raise AssertionError("Expected device_install_verify_failed")


def test_write_remote_file_skips_identical_content() -> None:
    content = b"same"
    expected_hash = hashlib.sha256(content).hexdigest()

    class FakeSshClient:
        def __init__(self) -> None:
            self.commands: list[tuple[str, bytes | None]] = []

        def run(self, command: str, input_data: bytes | None = None) -> str:
            self.commands.append((command, input_data))
            if command.startswith("sha256sum "):
                return expected_hash + "\n"
            if command.startswith("stat -c %a "):
                return "600\n"
            raise AssertionError("unexpected write command")

        def put_file(
            self,
            source: Path,
            remote_path: str,
            mode: str | None = None,
        ) -> bool:
            raise AssertionError("not used")

        def close(self) -> None:
            pass

    client = FakeSshClient()

    assert (
        device_installer._write_remote_file_sync(
            client,
            "/home/bticino/cfg/extra/c300x-native-agent/config.json",
            content,
            mode="600",
        )
        is False
    )
    assert len(client.commands) == 2


def test_write_remote_file_repairs_mode_drift_for_identical_content() -> None:
    content = b"same"
    expected_hash = hashlib.sha256(content).hexdigest()

    class FakeSshClient:
        def __init__(self) -> None:
            self.commands: list[tuple[str, bytes | None]] = []

        def run(self, command: str, input_data: bytes | None = None) -> str:
            self.commands.append((command, input_data))
            if command.startswith("sha256sum "):
                return expected_hash + "\n"
            if command.startswith("stat -c %a "):
                return "644\n"
            if command.startswith("chmod 600 "):
                return ""
            raise AssertionError(f"unexpected command: {command}")

        def put_file(
            self,
            source: Path,
            remote_path: str,
            mode: str | None = None,
        ) -> bool:
            raise AssertionError("not used")

        def close(self) -> None:
            pass

    client = FakeSshClient()

    assert (
        device_installer._write_remote_file_sync(
            client,
            "/home/bticino/cfg/extra/c300x-native-agent/config.json",
            content,
            mode="600",
        )
        is True
    )
    assert client.commands[-1][0].startswith("chmod 600 ")


def test_write_remote_file_replaces_changed_content_atomically() -> None:
    content = b"changed"

    class FakeSshClient:
        def __init__(self) -> None:
            self.commands: list[tuple[str, bytes | None]] = []

        def run(self, command: str, input_data: bytes | None = None) -> str:
            self.commands.append((command, input_data))
            if command.startswith("sha256sum "):
                return "not-a-sha\n"
            if ".new" in command and "mv -f" in command:
                return ""
            raise AssertionError(f"unexpected command: {command}")

        def put_file(
            self,
            source: Path,
            remote_path: str,
            mode: str | None = None,
        ) -> bool:
            raise AssertionError("not used")

        def close(self) -> None:
            pass

    client = FakeSshClient()

    assert device_installer._write_remote_file_sync(
        client,
        "/home/bticino/cfg/extra/c300x-native-agent/config.json",
        content,
        mode="600",
    )
    write_command, input_data = client.commands[-1]
    assert "config.json.c300x-" in write_command
    assert "chmod 600" in write_command
    assert "mv -f" in write_command
    assert input_data == content


def test_remote_helpers_treat_invalid_or_missing_remote_state_as_mismatch() -> None:
    class FakeSshClient:
        def __init__(self) -> None:
            self.commands: list[str] = []

        def run(self, command: str, input_data: bytes | None = None) -> str:
            self.commands.append(command)
            if command.startswith("sha256sum "):
                raise C300XDeviceInstallError("device_install_failed")
            if command.startswith("stat -c %a "):
                raise C300XDeviceInstallError("device_install_failed")
            if command.startswith("readlink "):
                raise C300XDeviceInstallError("device_install_failed")
            raise AssertionError(f"unexpected command: {command}")

        def put_file(
            self,
            source: Path,
            remote_path: str,
            mode: str | None = None,
        ) -> bool:
            raise AssertionError("not used")

        def close(self) -> None:
            pass

    client = FakeSshClient()

    assert device_installer._remote_sha256_sync(client, "/missing") is None
    assert not device_installer._remote_content_matches_sync(client, "/missing", b"x")
    assert not device_installer._remote_mode_matches_sync(client, "/missing", "600")
    assert not device_installer._remote_symlink_target_matches_sync(
        client,
        "/missing-link",
        "/target",
    )


def test_base_ssh_client_methods_are_abstract() -> None:
    client = device_installer._DeviceSshClient()

    for call in (
        lambda: client.run("true"),
        lambda: client.put_file(Path("/tmp/source"), "/remote"),
        client.close,
    ):
        try:
            call()
        except NotImplementedError:
            continue
        raise AssertionError("abstract SSH client method did not raise")


def test_required_existing_helper(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    present = tmp_path / "present"
    present.write_text("payload", encoding="utf-8")

    assert device_installer._first_existing(missing, present) == present
    try:
        device_installer._first_existing(missing)
    except C300XDeviceInstallError as err:
        assert err.reason == "agent_bundle_missing"
    else:
        raise AssertionError("missing bundle path was accepted")


def test_put_file_repairs_mode_drift_for_identical_payload(tmp_path: Path) -> None:
    payload = tmp_path / "c300x-agent-native"
    payload.write_bytes(b"agent")
    expected_hash = hashlib.sha256(b"agent").hexdigest()
    commands: list[tuple[str, bytes | None]] = []

    client = object.__new__(device_installer._AsyncSshDeviceSshClient)

    def fake_run(command: str, input_data: bytes | None = None) -> str:
        commands.append((command, input_data))
        if command.startswith("sha256sum "):
            return expected_hash + "\n"
        if command.startswith("stat -c %a "):
            return "600\n"
        if command.startswith("chmod 700 "):
            return ""
        raise AssertionError(f"unexpected command: {command}")

    client.run = fake_run

    assert client.put_file(
        payload,
        "/home/bticino/cfg/extra/c300x-native-agent/c300x-agent-native",
        "700",
    )
    assert commands[-1][0].startswith("chmod 700 ")


def test_asyncssh_client_run_fails_when_transport_inactive() -> None:
    client = object.__new__(device_installer._AsyncSshDeviceSshClient)
    client._closed = False
    client._client = types.SimpleNamespace(is_closed=lambda: True)
    with pytest.raises(C300XDeviceInstallError, match="device_install_failed"):
        client.run("agent status")


def test_asyncssh_put_file_replaces_changed_payload(tmp_path: Path) -> None:
    payload = tmp_path / "config.json"
    payload.write_bytes(b"new")
    commands: list[tuple[str, bytes | None]] = []

    client = object.__new__(device_installer._AsyncSshDeviceSshClient)

    def fake_run(command: str, input_data: bytes | None = None) -> str:
        commands.append((command, input_data))
        if command.startswith("sha256sum "):
            return "not-a-valid-sha\n"
        if ".new" in command and "mv -f" in command:
            return ""
        raise AssertionError(f"unexpected command: {command}")

    client.run = fake_run

    assert client.put_file(payload, "/remote/config.json", "600") is True
    command, data = commands[-1]
    assert data == b"new"
    temp = r"(/remote/config\.json\.c300x-[0-9a-f]{16}\.new)"
    digest = hashlib.sha256(b"new").hexdigest()
    assert re.fullmatch(
        r"\{ umask 077 && cat > " + temp + r" && sum=\$\(sha256sum < \1\) && "
        r'\[ "\$\{sum%% \*\}" = ' + digest + r" \] && chmod 600 \1 && "
        r"mv -f \1 /remote/config\.json; \}; rc=\$\?; rm -f \1; exit \$rc",
        command,
    )


def test_asyncssh_client_init_reports_connect_failures(monkeypatch: Any) -> None:
    async def connect(**_kwargs: Any) -> None:
        raise OSError("denied")

    module = types.SimpleNamespace(
        __version__="2.24.1", Error=RuntimeError, connect=connect
    )
    monkeypatch.setitem(sys.modules, "asyncssh", module)
    with pytest.raises(C300XDeviceInstallError, match="device_install_failed"):
        device_installer._AsyncSshDeviceSshClient(
            C300XDeviceInstallRequest(
                host="c300x.local", ssh_username="root", ssh_password="secret",
            )
        )


def test_asyncssh_client_init_tells_a_refused_login(monkeypatch: Any) -> None:
    class Error(Exception):
        pass

    class PermissionDenied(Error):
        pass

    async def connect(**_kwargs: Any) -> None:
        raise PermissionDenied("refused")

    module = types.SimpleNamespace(
        __version__="2.24.1", Error=Error, PermissionDenied=PermissionDenied, connect=connect
    )
    monkeypatch.setitem(sys.modules, "asyncssh", module)
    with pytest.raises(C300XDeviceInstallError, match="ssh_login_refused"):
        device_installer._AsyncSshDeviceSshClient(
            C300XDeviceInstallRequest(
                host="c300x.local", ssh_username="root", ssh_password="secret",
            )
        )


@pytest.mark.parametrize("failure", [ImportError, OSError])
def test_asyncssh_client_init_reports_missing_dependency(monkeypatch: Any, caplog, failure) -> None:
    monkeypatch.delitem(sys.modules, "asyncssh", raising=False)

    original_import = __import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "asyncssh":
            raise failure("private-index-token")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    try:
        device_installer._AsyncSshDeviceSshClient(
            C300XDeviceInstallRequest(
                host="c300x.local",
                ssh_username="root",
                ssh_password="secret",
            )
        )
    except device_installer.C300XDeviceInstallError as err:
        assert err.reason == "installer_dependency_missing"
    else:  # pragma: no cover
        raise AssertionError("missing AsyncSSH dependency was accepted")
    assert f"import optional SSH requirement asyncssh==2.24.1 ({failure.__name__})" in caplog.text
    assert "private-index-token" not in caplog.text and "secret" not in caplog.text


def test_startup_script_recreates_missing_rc_link_without_rewriting_init(
    tmp_path: Path,
) -> None:
    remote_dir = "/home/bticino/cfg/extra/custom-agent"
    init_script = tmp_path / "c300x-native-agent"
    init_script.write_text(
        '#!/bin/sh\n'
        f'DEFAULT_AGENT_DIR="{DEFAULT_REMOTE_DIR}"\n'
        'exec "$DEFAULT_AGENT_DIR/c300x-agent-native"\n',
        encoding="utf-8",
    )
    init_content = device_installer._render_startup_script(init_script, remote_dir)
    env_content = device_installer._render_startup_defaults(remote_dir)
    hashes = {
        f"{remote_dir}/{device_installer.REMOTE_INIT_ENV_NAME}": hashlib.sha256(
            env_content
        ).hexdigest(),
        device_installer.REMOTE_INIT_SCRIPT: hashlib.sha256(init_content).hexdigest(),
    }

    class FakeSshClient:
        def __init__(self) -> None:
            self.commands: list[tuple[str, bytes | None]] = []

        def run(self, command: str, input_data: bytes | None = None) -> str:
            self.commands.append((command, input_data))
            if command.startswith("sha256sum "):
                for path, digest in hashes.items():
                    if path in command:
                        return digest + "\n"
                raise device_installer.C300XDeviceInstallError("device_install_failed")
            if command.startswith("stat -c %a "):
                return "644\n"
            if command.startswith("readlink "):
                raise device_installer.C300XDeviceInstallError("device_install_failed")
            if "ln -sf /etc/init.d/c300x-native-agent" in command:
                return ""
            raise AssertionError(f"unexpected command: {command}")

        def put_file(
            self,
            source: Path,
            remote_path: str,
            mode: str | None = None,
        ) -> bool:
            raise AssertionError("not used")

        def close(self) -> None:
            pass

    client = FakeSshClient()

    changed = device_installer._install_startup_script_sync(
        client,
        init_script,
        remote_dir,
    )

    assert changed == (device_installer.REMOTE_INIT_LINK,)
    assert not any(
        command[1] and b"DEFAULT_AGENT_DIR" in command[1]
        for command in client.commands
    )
    link_repair = next(command[0] for command in client.commands if "ln -sf" in command[0])
    assert ".c300x-native-agent-init." not in link_repair
    assert "mv -f" not in link_repair


def test_startup_script_update_preserves_init_move_failure_status(
    tmp_path: Path,
) -> None:
    remote_dir = "/home/bticino/cfg/extra/custom-agent"
    init_script = tmp_path / "c300x-native-agent"
    init_script.write_text(
        '#!/bin/sh\n'
        f'DEFAULT_AGENT_DIR="{DEFAULT_REMOTE_DIR}"\n'
        'exec "$DEFAULT_AGENT_DIR/c300x-agent-native"\n',
        encoding="utf-8",
    )
    env_content = device_installer._render_startup_defaults(remote_dir)
    hashes = {
        f"{remote_dir}/{device_installer.REMOTE_INIT_ENV_NAME}": hashlib.sha256(
            env_content
        ).hexdigest(),
    }

    class FakeSshClient:
        def __init__(self) -> None:
            self.commands: list[tuple[str, bytes | None]] = []

        def run(self, command: str, input_data: bytes | None = None) -> str:
            self.commands.append((command, input_data))
            if command.startswith("sha256sum "):
                for path, digest in hashes.items():
                    if path in command:
                        return digest + "\n"
                raise device_installer.C300XDeviceInstallError("device_install_failed")
            if command.startswith("stat -c %a "):
                return "644\n"
            if command.startswith("readlink "):
                raise device_installer.C300XDeviceInstallError("device_install_failed")
            if command.startswith("{ umask 077 && cat > ") and "mv -f" not in command:
                return ""
            if "mv -f" in command:
                return ""
            raise AssertionError(f"unexpected command: {command}")

        def put_file(
            self,
            source: Path,
            remote_path: str,
            mode: str | None = None,
        ) -> bool:
            raise AssertionError("not used")

        def close(self) -> None:
            pass

    client = FakeSshClient()

    changed = device_installer._install_startup_script_sync(
        client,
        init_script,
        remote_dir,
    )

    update_command = next(command[0] for command in client.commands if "mv -f" in command[0])
    assert changed == (
        device_installer.REMOTE_INIT_SCRIPT,
        device_installer.REMOTE_INIT_LINK,
    )
    assert "mv -f" in update_command
    assert "if [ $rc -eq 0 ]; then ln -sf" in update_command
    assert "fi; rc=$?" not in update_command
    assert re.search(
        r"mount -o remount,ro /; ro_rc=\$\?; if \[ \$rc -eq 0 \]; then rc=\$ro_rc; fi; fi; "
        r"rm -f \S+/\.c300x-native-agent-init\.c300x-[0-9a-f]{16}\.new; exit \$rc$",
        update_command,
    )


def test_startup_script_keeps_matching_rc_link_unchanged(tmp_path: Path) -> None:
    remote_dir = "/home/bticino/cfg/extra/custom-agent"
    init_script = tmp_path / "c300x-native-agent"
    init_script.write_text(
        '#!/bin/sh\n'
        f'DEFAULT_AGENT_DIR="{DEFAULT_REMOTE_DIR}"\n'
        'exec "$DEFAULT_AGENT_DIR/c300x-agent-native"\n',
        encoding="utf-8",
    )
    init_content = device_installer._render_startup_script(init_script, remote_dir)
    env_content = device_installer._render_startup_defaults(remote_dir)
    hashes = {
        f"{remote_dir}/{device_installer.REMOTE_INIT_ENV_NAME}": hashlib.sha256(
            env_content
        ).hexdigest(),
        device_installer.REMOTE_INIT_SCRIPT: hashlib.sha256(init_content).hexdigest(),
    }

    class FakeSshClient:
        def __init__(self) -> None:
            self.commands: list[tuple[str, bytes | None]] = []

        def run(self, command: str, input_data: bytes | None = None) -> str:
            self.commands.append((command, input_data))
            if command.startswith("sha256sum "):
                for path, digest in hashes.items():
                    if path in command:
                        return digest + "\n"
                raise device_installer.C300XDeviceInstallError("device_install_failed")
            if command.startswith("stat -c %a "):
                return "644\n"
            if command.startswith("readlink "):
                return f"{device_installer.REMOTE_INIT_SCRIPT}\n"
            raise AssertionError(f"unexpected command: {command}")

        def put_file(
            self,
            source: Path,
            remote_path: str,
            mode: str | None = None,
        ) -> bool:
            raise AssertionError("not used")

        def close(self) -> None:
            pass

    client = FakeSshClient()

    changed = device_installer._install_startup_script_sync(
        client,
        init_script,
        remote_dir,
    )

    assert changed == ()
    assert not any("ln -sf" in command[0] for command in client.commands)
    assert not any("mount -o remount,rw /" in command[0] for command in client.commands)


def test_ssh_host_unwraps_ipv6_brackets() -> None:
    assert device_installer._ssh_host("[fe80::1]") == "fe80::1"
    assert device_installer._ssh_host("c300x.local") == "c300x.local"


def test_startup_render_and_verify_error_paths(tmp_path: Path) -> None:
    invalid_init = tmp_path / "c300x-native-agent"
    invalid_init.write_text("#!/bin/sh\n", encoding="utf-8")

    try:
        device_installer._render_startup_script(invalid_init, DEFAULT_REMOTE_DIR)
    except device_installer.C300XDeviceInstallError as err:
        assert err.reason == "agent_bundle_missing"
    else:  # pragma: no cover
        raise AssertionError("invalid startup script was accepted")

    class BadStartupClient:
        def run(self, command: str, input_data: bytes | None = None) -> str:
            _ = input_data
            if command.startswith("readlink "):
                return "/wrong\n"
            raise AssertionError(f"unexpected command: {command}")

    try:
        device_installer._verify_startup_sync(BadStartupClient())
    except device_installer.C300XDeviceInstallError as err:
        assert err.reason == "device_install_verify_failed"
    else:  # pragma: no cover
        raise AssertionError("bad startup link was accepted")

    class MissingLinkClient:
        def run(self, command: str, input_data: bytes | None = None) -> str:
            _ = command, input_data
            raise device_installer.C300XDeviceInstallError("device_install_failed")

    try:
        device_installer._verify_startup_sync(MissingLinkClient())
    except device_installer.C300XDeviceInstallError as err:
        assert err.reason == "device_install_verify_failed"
    else:  # pragma: no cover
        raise AssertionError("missing startup link was accepted")

    class BrokenStatusClient:
        def run(self, command: str, input_data: bytes | None = None) -> str:
            _ = input_data
            if command.startswith("readlink "):
                return f"{device_installer.REMOTE_INIT_SCRIPT}\n"
            if command.endswith(" status"):
                raise device_installer.C300XDeviceInstallError("device_install_failed")
            raise AssertionError(f"unexpected command: {command}")

    try:
        device_installer._verify_startup_sync(BrokenStatusClient())
    except device_installer.C300XDeviceInstallError as err:
        assert err.reason == "device_install_verify_failed"
    else:  # pragma: no cover
        raise AssertionError("bad startup status was accepted")


def test_firewall_patch_bootstrap_invokes_project_script() -> None:
    commands: list[str] = []

    class FakeSshClient:
        def run(self, command: str, input_data: bytes | None = None) -> str:
            _ = input_data
            commands.append(command)
            return ""

    device_installer._apply_firewall_patch_sync(
        FakeSshClient(),
        "/home/bticino/cfg/extra/c300x-native-agent",
        8091,
    )

    assert commands == [
        f"C300X_IPTABLES={device_installer.REMOTE_FIREWALL_PATH} "
        f"C300X_IPTABLES_BACKUP={device_installer.REMOTE_FIREWALL_BACKUP} "
        "/home/bticino/cfg/extra/c300x-native-agent/bootstrap_firewall.sh "
        f"8091{FIREWALL_STATUS_TAIL}"
    ]


@pytest.mark.parametrize(("status", "reason"), [
    (0, None), (3, "firewall_hook_changed"), (1, "device_install_failed"),
])
def test_a_firewall_hook_changed_after_patching_is_named(tmp_path: Path, status: int, reason: str | None) -> None:
    """The script's status 3 reaches HA as its own error, not a general failure."""
    script = tmp_path / "bootstrap_firewall.sh"
    script.write_text(f"#!/bin/sh\nprintf 'changed_files=0\\n'\nexit {status}\n")
    script.chmod(0o700)

    class ShellClient:
        def run(self, command: str, input_data: bytes | None = None) -> str:
            result = subprocess.run(["/bin/sh", "-c", command], capture_output=True, text=True, check=False)
            if result.returncode:
                raise C300XDeviceInstallError("device_install_failed")
            return result.stdout

    if reason is None:
        device_installer._apply_firewall_patch_sync(ShellClient(), str(tmp_path), 8091)
        return
    with pytest.raises(C300XDeviceInstallError) as caught:
        device_installer._apply_firewall_patch_sync(ShellClient(), str(tmp_path), 8091)
    assert caught.value.reason == reason


def test_asyncssh_connect_kwargs_force_legacy_ssh_rsa() -> None:
    kwargs = device_installer._asyncssh_connect_kwargs(
        C300XDeviceInstallRequest(
            host="[fe80::1]",
            ssh_username=" root ",
            ssh_password="secret",
        )
    )

    assert kwargs["host"] == "fe80::1"
    assert kwargs["username"] == "root"
    assert kwargs["client_keys"] == []
    assert kwargs["agent_path"] is None
    assert kwargs["config"] is None
    assert kwargs["known_hosts"] is None
    assert kwargs["preferred_auth"] == ["password"]
    # Modern host keys first, the factory station's RSA/SHA-1 last.
    assert kwargs["server_host_key_algs"] == [
        "ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
        "rsa-sha2-512", "rsa-sha2-256", "ssh-rsa",
    ]
    assert kwargs["kex_algs"] == "+diffie-hellman-group1-sha1"
    assert kwargs["encryption_algs"] == "+aes128-cbc,3des-cbc"


@pytest.mark.parametrize(("value", "reported"), [("4.0.0", "4.0.0"), ("private-index-token", "unknown")])
def test_installer_rejects_unvalidated_asyncssh_versions(value, reported, caplog) -> None:
    class FakeAsyncSSH:
        __version__ = value

    try:
        device_installer._validate_asyncssh_version(FakeAsyncSSH)
    except device_installer.C300XDeviceInstallError as err:
        assert err.reason == "installer_dependency_missing"
    else:  # pragma: no cover
        raise AssertionError("Expected installer_dependency_missing")
    assert f"asyncssh==2.24.1 does not match loaded version {reported}" in caplog.text
    assert "private-index-token" not in caplog.text


def test_manifest_does_not_require_optional_asyncssh() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "bticino_c300x" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert not any(
        requirement.startswith("asyncssh") for requirement in manifest["requirements"]
    )


def test_installer_requests_optional_asyncssh_on_demand() -> None:
    assert INSTALLER_REQUIREMENTS == ("asyncssh==2.24.1",)


def test_installer_dependency_processing_uses_homeassistant_requirements(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[object, str, list[str], bool]] = []

    async def process_requirements(
        hass: object,
        name: str,
        requirements: list[str],
        *,
        is_built_in: bool,
    ) -> None:
        calls.append((hass, name, requirements, is_built_in))

    requirements_module = types.ModuleType("homeassistant.requirements")
    requirements_module.RequirementsNotFound = RuntimeError
    requirements_module.async_process_requirements = process_requirements
    monkeypatch.setitem(sys.modules, "homeassistant.requirements", requirements_module)
    homeassistant_module = sys.modules.setdefault(
        "homeassistant",
        types.ModuleType("homeassistant"),
    )
    monkeypatch.setattr(
        homeassistant_module,
        "requirements",
        requirements_module,
        raising=False,
    )
    hass = object()

    asyncio.run(async_ensure_installer_dependencies(hass))  # type: ignore[arg-type]

    assert calls == [(hass, "bticino_c300x", ["asyncssh==2.24.1"], False)]


def test_installer_dependency_failure_can_retry_without_logging_secrets(monkeypatch, caplog):
    from homeassistant import requirements

    import custom_components.bticino_c300x.device_installer as installer

    monkeypatch.setattr(installer, "_installed_asyncssh_version", lambda: None)
    attempts = []

    async def resolve(hass, name, packages, *, is_built_in):
        attempts.append(packages)
        if len(attempts) == 1:
            raise requirements.RequirementsNotFound(name, ["https://user:private-key@index.invalid"])

    monkeypatch.setattr(requirements, "async_process_requirements", resolve)
    hass = object()
    with pytest.raises(C300XDeviceInstallError, match="installer_dependency_missing"):
        asyncio.run(async_ensure_installer_dependencies(hass))
    assert "install optional SSH requirement asyncssh==2.24.1 (RequirementsNotFound)" in caplog.text
    assert "private-key" not in caplog.text
    asyncio.run(async_ensure_installer_dependencies(hass))
    assert attempts == [list(INSTALLER_REQUIREMENTS)] * 2


@pytest.mark.parametrize("installed", ["2.24.1", "2.21.0", None])
def test_installer_uses_pinned_asyncssh_already_installed_when_ha_refuses(monkeypatch, caplog, installed):
    from homeassistant import requirements

    import custom_components.bticino_c300x.device_installer as installer

    async def refuse(hass, name, packages, *, is_built_in):
        # HA keeps a failed install in its history until restart or a config check,
        # even when the package landed on disk.
        raise requirements.RequirementsNotFound(name, packages)

    monkeypatch.setattr(requirements, "async_process_requirements", refuse)
    monkeypatch.setattr(installer, "_installed_asyncssh_version", lambda: installed)
    if installed == "2.24.1":
        asyncio.run(async_ensure_installer_dependencies(object()))
        assert "already installed" in caplog.text
        return
    with pytest.raises(C300XDeviceInstallError, match="installer_dependency_missing"):
        asyncio.run(async_ensure_installer_dependencies(object()))


@pytest.mark.parametrize(("installed", "state"), [(None, "not installed"), ("2.21.0", "2.21.0")])
def test_installer_dependency_failure_logs_what_ha_reported_and_what_is_installed(
    monkeypatch, caplog, installed, state,
):
    from homeassistant import requirements

    import custom_components.bticino_c300x.device_installer as installer

    async def refuse(hass, name, packages, *, is_built_in):
        raise requirements.RequirementsNotFound(name, [*packages, "https://user:private-key@index.invalid"])

    monkeypatch.setattr(requirements, "async_process_requirements", refuse)
    monkeypatch.setattr(installer, "_installed_asyncssh_version", lambda: installed)
    with pytest.raises(C300XDeviceInstallError, match="installer_dependency_missing"):
        asyncio.run(async_ensure_installer_dependencies(object()))
    assert "HA reported asyncssh==2.24.1 and 1 other requirement as not found" in caplog.text
    assert f"installed asyncssh: {state}" in caplog.text
    assert "private-key" not in caplog.text


def test_installed_asyncssh_version_sees_a_package_installed_while_ha_runs(monkeypatch):
    import importlib
    import importlib.metadata

    import custom_components.bticino_c300x.device_installer as installer

    calls = []
    monkeypatch.setattr(importlib, "invalidate_caches", lambda: calls.append("invalidate"))
    monkeypatch.setattr(importlib.metadata, "version", lambda name: calls.append("version") or "2.24.1")
    assert installer._installed_asyncssh_version() == "2.24.1"
    assert calls == ["invalidate", "version"]


def test_installed_asyncssh_version_reads_package_metadata(monkeypatch):
    import importlib.metadata

    import custom_components.bticino_c300x.device_installer as installer

    monkeypatch.setattr(importlib.metadata, "version", lambda name: {"asyncssh": "2.24.1"}[name])
    assert installer._installed_asyncssh_version() == "2.24.1"

    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    assert installer._installed_asyncssh_version() is None


def test_installer_dependency_recovery_text_mentions_pinned_package_in_all_languages():
    component = ROOT / "custom_components/bticino_c300x"
    for path in (component / "strings.json", *(component / "translations").glob("*.json")):
        text = json.loads(path.read_text())["config"]["error"]["installer_dependency_missing"]
        assert INSTALLER_REQUIREMENTS[0] in text, path.name
        assert "YAML" in text, path.name
    # HA keeps the failure until a configuration check or restart: that comes first.
    english = json.loads((component / "translations/en.json").read_text())["config"]["error"]
    text = english["installer_dependency_missing"]
    assert text.index("Check configuration") < text.index("Logs")
    assert "even when the package" in text


def test_dev_requirements_pin_asyncssh_with_legacy_ssh_rsa_support() -> None:
    requirement_files = (
        ROOT / "requirements-dev.txt",
        ROOT / "requirements-dev-min-ha.txt",
    )

    for path in requirement_files:
        assert "asyncssh==2.24.1" in path.read_text(encoding="utf-8").splitlines()


def test_manifest_does_not_require_aiortc() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "bticino_c300x" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert not any(
        requirement.startswith("aiortc") for requirement in manifest["requirements"]
    )


FIREWALL_STATUS_TAIL = (
    "; rc=$?; if [ $rc -eq 3 ]; then printf '\\n%s\\n' firewall_hook_changed; exit 0; fi; exit $rc"
)


def test_bootstrap_firewall_logic_lives_in_project_script() -> None:
    installer = (
        ROOT / "custom_components" / "bticino_c300x" / "device_installer.py"
    ).read_text(encoding="utf-8")
    script = (ROOT / "native_agent" / "scripts" / "bootstrap_firewall.sh").read_text(
        encoding="utf-8"
    )

    assert "iptables -A INPUT" not in installer
    assert "c300x-firewall-base" not in installer
    assert "iptables -A INPUT" in script
    assert "--dport $RTSP_PORT" in script
    assert "--dport $TALKBACK_RTP_PORT" in script
    assert "# c300x-native-agent firewall begin" in script
    assert "# c300x-native-agent ipv6 firewall begin" in script


def test_merge_existing_device_config_keeps_device_owned_sections() -> None:
    template = device_installer._device_config_json(
        api_token="new-api", maintenance_token="new-maint", agent_port=8089
    ).encode()
    existing = {
        "api": {"token": "old-api"},
        "mqtt": {"enabled": True, "host": "broker.lan", "password": "pw"},
        "displayBridge": {"enabled": True},
        "maintenance": {"adminToken": "old-maint"},
    }

    merged = json.loads(device_installer._merge_existing_device_config(template, existing))

    assert merged["mqtt"] == existing["mqtt"]
    assert merged["displayBridge"] == {"enabled": True}
    assert merged["api"]["token"] == "new-api"
    assert merged["maintenance"]["adminToken"] == "new-maint"
    assert merged["memos"]["enabled"] is True
    for odd in (None, [], "x", {"mqtt": "nope"}):
        result = json.loads(device_installer._merge_existing_device_config(template, odd))
        assert result == json.loads(template)


@pytest.mark.parametrize(("kind", "existing", "expected"), [
    ("qt5_ondisk", None, True),
    # An existing video section is kept as it is, as on a C300X.
    ("qt5_ondisk", {"video": {"rtsp": {"port": 7654}}}, None),
    ("qt5_ondisk", {"video": {"enabled": True}}, True),
    ("qt5_ondisk", {"video": {"enabled": True, "rtsp": {"port": 7654}}}, True),
    ("qt5_ondisk", {"video": {"enabled": False}}, False),
    ("qt5_rcc", None, True),
    ("qt4_ondisk", None, True),
])
def test_bootstrap_firewall_uses_final_device_video_config(monkeypatch, kind, existing, expected):
    from types import SimpleNamespace

    commands, configs = [], []
    client = SimpleNamespace(run=lambda command, *_: commands.append(command), close=lambda: None)
    monkeypatch.setattr(device_installer, "_connect_device_client", lambda _: client)
    monkeypatch.setattr(device_installer, "_admit_station_sync", lambda *_: kind)
    monkeypatch.setattr(device_installer, "_read_remote_config_sync", lambda *_: existing)
    monkeypatch.setattr(device_installer, "_firewall_hook_present_sync", lambda *_: True)
    monkeypatch.setattr(device_installer, "_write_remote_file_sync",
                        lambda _c, _p, data, **_: configs.append(json.loads(data)))
    monkeypatch.setattr(device_installer, "_install_startup_script_sync", lambda *_: [])
    monkeypatch.setattr(device_installer, "_render_startup_script", lambda *_: b"")
    monkeypatch.setattr(device_installer, "_verify_startup_sync", lambda *_: None)
    monkeypatch.setattr(device_installer, "_apply_qml_patch_sync", lambda *_: None)
    monkeypatch.setattr(device_installer, "_remove_obsolete_display_source_sync", lambda *_: None)
    request = C300XDeviceInstallRequest(host="unused", ssh_username="unused", ssh_password="unused",
                                        apply_gui_patch=False, apply_firewall_patch=True)
    template = device_installer._device_config_json(
        api_token="unused", maintenance_token="unused", agent_port=request.agent_port,
    ).encode()
    device_installer._install_device_agent_sync(
        request, device_installer._ResolvedBundle((), Path("unused")), template,
    )
    config, = configs
    command, = [cmd for cmd in commands if "/bootstrap_firewall.sh " in cmd]
    assert config["video"].get("enabled") is expected
    if kind == "qt5_ondisk":
        assert f"C300X_VIDEO_ENABLED={int(bool(expected))} " in command
        if expected:
            port = (existing or {}).get("video", {}).get("rtsp", {}).get("port", 6554)
            assert f"C300X_RTSP_PORT={port} " in command
        else:
            assert "C300X_RTSP_PORT=" not in command
        if existing and "rtsp" in existing["video"]:
            assert config["video"]["rtsp"] == existing["video"]["rtsp"]
    else:
        assert "C300X_VIDEO_ENABLED" not in command


@pytest.mark.parametrize("port", [0, 65536, True, "7654"])
def test_bootstrap_rejects_invalid_media_port_before_firewall_command(port):
    from types import SimpleNamespace

    client = SimpleNamespace(run=lambda *_: pytest.fail("Unexpected firewall command"))
    config = {"video": {"enabled": True, "rtsp": {"port": port}}}
    with pytest.raises(C300XDeviceInstallError, match="device_install_failed"):
        device_installer._apply_firewall_patch_sync(
            client, "/agent", 8091, config_bytes=json.dumps(config).encode(),
        )


def test_install_reads_remote_config_and_writes_merged_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Isolate configuration preservation from the C100X package admission test.
    monkeypatch.setattr(device_installer, "_admit_station_sync", lambda *_: "qt4_ondisk")
    old = json.dumps({"mqtt": {"enabled": True, "host": "broker.lan"}})

    class FakeSshClient:
        def __init__(self) -> None:
            self.writes: list[bytes] = []

        def run(self, command: str, input_data: bytes | None = None) -> str:
            if command.startswith("if [ -e "):
                return "F" + old
            if input_data and b"api-token" in input_data:
                self.writes.append(input_data)
            if "qml_patch.sh " in command:
                return json.dumps({
                    "ok": True, "core_patched": True, "gui_running": True,
                    "patched": False,
                })
            return ""

        def put_file(self, source: Path, remote_path: str, mode: str | None = None) -> bool:
            return True

        def close(self) -> None:
            pass

    init_script = tmp_path / "c300x-native-agent"
    init_script.write_text(
        f'DEFAULT_AGENT_DIR="{DEFAULT_REMOTE_DIR}"\n', encoding="utf-8"
    )
    client = FakeSshClient()
    monkeypatch.setattr(
        device_installer,
        "_resolve_bundle",
        lambda _dir: device_installer._ResolvedBundle((), init_script),
    )
    monkeypatch.setattr(device_installer, "_connect_device_client", lambda _r: client)
    monkeypatch.setattr(device_installer, "_verify_startup_sync", lambda _c: None)
    monkeypatch.setattr(device_installer.asyncio, "to_thread", _to_thread_inline)

    asyncio.run(
        async_install_device_agent(
            C300XDeviceInstallRequest(
                host="c300x.local", ssh_username="root", ssh_password="secret",
                apply_firewall_patch=False,
            ),
            api_token="api-token",
            maintenance_token="maintenance-token",
        )
    )

    assert client.writes
    assert json.loads(client.writes[0])["mqtt"]["host"] == "broker.lan"


@pytest.mark.parametrize("response", [
    None, "", "not-json", "[]", "{}", "MM", "Fbroken", "Fnull", "F[]", "F",
])
def test_install_config_read_failure_never_writes_or_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: str | None
) -> None:
    class FakeSshClient:
        def __init__(self) -> None:
            self.commands: list[str] = []
            self.closed = False

        def run(self, command: str, input_data: bytes | None = None) -> str:
            self.commands.append(command)
            assert "config.json" in command and input_data is None
            if response is None:
                raise C300XDeviceInstallError("device_install_failed")
            return response

        def put_file(self, *args: Any, **kwargs: Any) -> bool:
            pytest.fail("Payload upload before successful config read")

        def close(self) -> None:
            self.closed = True

    client = FakeSshClient()
    monkeypatch.setattr(device_installer, "_connect_device_client", lambda _r: client)
    bundle = device_installer._ResolvedBundle(
        (device_installer._PayloadFile(tmp_path / "payload", "/unused-agent", "700"),),
        tmp_path / "unused-init",
    )
    request = C300XDeviceInstallRequest(
        host="c300x.local", ssh_username="root", ssh_password="secret"
    )
    with pytest.raises(C300XDeviceInstallError):
        device_installer._install_device_agent_sync(request, bundle, b"{}")
    assert len(client.commands) == 1
    assert client.closed


class _LocalShellClient:
    """Run the device commands in a local shell, as the device shell would."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    def run(self, command: str, input_data: bytes | None = None) -> str:
        self.commands.append(command)
        result = subprocess.run(
            ["sh", "-c", command], input=input_data or b"",
            capture_output=True, check=False,
        )
        if result.returncode:
            raise C300XDeviceInstallError("device_install_failed")
        return result.stdout.decode("utf-8")


@pytest.mark.parametrize("state", [
    "missing", "missing_dir", "valid", "empty", "malformed", "directory",
    "dangling", "denied", "read_error",
])
def test_config_read_command_local_files(tmp_path: Path, state: str) -> None:
    if state in ("denied", "read_error") and os.geteuid() == 0:
        pytest.skip("root ignores file permissions")
    folder = tmp_path / "agent"
    path = folder / "config.json"
    if state != "missing_dir":
        folder.mkdir()
    if state in ("valid", "read_error"):
        path.write_text('{"mqtt": {"host": "broker.lan"}}', encoding="utf-8")
    elif state == "empty":
        path.write_text("", encoding="utf-8")
    elif state == "malformed":
        path.write_text("Mbroken", encoding="utf-8")
    elif state == "directory":
        path.mkdir()
    elif state == "dangling":
        path.symlink_to(tmp_path / "absent-target")
    if state == "read_error":
        path.chmod(0)
    elif state == "denied":
        folder.chmod(0)

    client = _LocalShellClient()
    try:
        if state in ("missing", "missing_dir"):
            assert device_installer._read_remote_config_sync(client, str(path)) is None
        elif state == "valid":
            assert device_installer._read_remote_config_sync(client, str(path)) == {
                "mqtt": {"host": "broker.lan"}
            }
        else:
            with pytest.raises(C300XDeviceInstallError):
                device_installer._read_remote_config_sync(client, str(path))
    finally:
        folder.chmod(0o755) if folder.exists() else None


def test_config_that_is_not_utf8_is_refused_and_not_rewritten(tmp_path: Path) -> None:
    """The reply is decoded leniently; a damaged value must not be saved."""

    path = tmp_path / "config.json"
    path.write_bytes(b'{"mqtt": {"password": "caf\xe9"}}')

    class LenientClient(_LocalShellClient):
        def run(self, command: str, input_data: bytes | None = None) -> str:
            result = subprocess.run(["sh", "-c", command], capture_output=True, check=True)
            return result.stdout.decode("utf-8", "replace")

    with pytest.raises(C300XDeviceInstallError):
        device_installer._read_remote_config_sync(LenientClient(), str(path))


def test_device_side_steps_use_no_python(tmp_path: Path) -> None:
    """The stock device Python has neither json nor hashlib."""

    path = tmp_path / "config.json"
    path.write_text('{"video": {}}', encoding="utf-8")
    client = _LocalShellClient()

    assert device_installer._read_remote_config_sync(client, str(path)) == {"video": {}}
    assert device_installer._remote_sha256_sync(client, str(path)) == hashlib.sha256(
        b'{"video": {}}'
    ).hexdigest()
    assert device_installer._remote_sha256_sync(client, str(tmp_path / "absent")) is None
    assert client.commands
    assert not any("python" in command for command in client.commands)


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def test_install_resolves_the_bundle_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    def resolve(_remote_dir: str) -> Any:
        seen.append(_on_event_loop())
        raise RuntimeError("stop after the bundle lookup")

    monkeypatch.setattr(device_installer, "_resolve_bundle", resolve)
    request = C300XDeviceInstallRequest(host="c300x.local", ssh_username="root", ssh_password="secret")

    with pytest.raises(RuntimeError, match="stop after the bundle lookup"):
        asyncio.run(async_install_device_agent(request, api_token="api-token", maintenance_token="m"))
    assert seen == [False]
