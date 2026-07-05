from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import types
from pathlib import Path
from typing import Any

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
    C300XDeviceInstallError,
    C300XDeviceInstallRequest,
    _device_config_json,
    _render_startup_defaults,
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
    remote_dir = "/home/bticino/cfg/extra/custom-agent"

    class FakeSshClient:
        def __init__(self) -> None:
            self.commands: list[tuple[str, bytes | None]] = []
            self.uploads: list[tuple[str, str, str | None]] = []
            self.closed = False

        def run(self, command: str, input_data: bytes | None = None) -> str:
            self.commands.append((command, input_data))
            if command == f"readlink {device_installer.REMOTE_INIT_LINK}":
                return f"{device_installer.REMOTE_INIT_SCRIPT}\n"
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
    assert f"{remote_dir}/.c300x-native-agent-init.new" in init_write[0]
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
    assert f"{remote_dir}/config.json.new" in config_write[0]
    assert any(command[0] == "/etc/init.d/c300x-native-agent restart" for command in fake_client.commands)
    assert any(command[0] == f"readlink {device_installer.REMOTE_INIT_LINK}" for command in fake_client.commands)
    assert any(command[0] == f"{device_installer.REMOTE_INIT_SCRIPT} status" for command in fake_client.commands)
    assert any(
        command[0]
        == (
            f"C300X_QML_SOURCE_DIR={remote_dir}/qml "
            f"{remote_dir}/qml_patch.sh core-apply"
        )
        for command in fake_client.commands
    )
    assert any(
        command[0]
        == (
            "C300X_IPTABLES=/etc/network/if-pre-up.d/iptables "
            "C300X_IPTABLES_BACKUP=/home/bticino/cfg/extra/c300x-device-file-backups/original"
            "/etc/network/if-pre-up.d/iptables "
            f"{remote_dir}/bootstrap_firewall.sh 8091"
        )
        for command in fake_client.commands
    )
    assert any(
        command[0]
        == (
            f"C300X_QML_SOURCE_DIR={remote_dir}/qml "
            f"{remote_dir}/qml_patch.sh apply"
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
    remote_dir = "/home/bticino/cfg/extra/custom-agent"

    class FakeSshClient:
        def run(self, command: str, input_data: bytes | None = None) -> str:
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
            if command.startswith("python - "):
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
            if command.startswith("python - "):
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
            if command.startswith("python - "):
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
    assert "config.json.new" in write_command
    assert "chmod 600" in write_command
    assert "mv -f" in write_command
    assert input_data == content


def test_remote_helpers_treat_invalid_or_missing_remote_state_as_mismatch() -> None:
    class FakeSshClient:
        def __init__(self) -> None:
            self.commands: list[str] = []

        def run(self, command: str, input_data: bytes | None = None) -> str:
            self.commands.append(command)
            if command.startswith("python - "):
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


def test_first_and_optional_existing_helpers(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    present = tmp_path / "present"
    present.write_text("payload", encoding="utf-8")

    assert device_installer._first_existing(missing, present) == present
    assert device_installer._optional_existing(missing, present) == present
    assert device_installer._optional_existing(missing) is None
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

    client = object.__new__(device_installer._ParamikoDeviceSshClient)

    def fake_run(command: str, input_data: bytes | None = None) -> str:
        commands.append((command, input_data))
        if command.startswith("python - "):
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


def test_paramiko_client_run_streams_stdout_and_input() -> None:
    class FakeChannel:
        def __init__(self) -> None:
            self.input_data: bytes | None = None
            self.closed = False
            self.stdout = [b"ok\n"]

        def settimeout(self, _timeout: float) -> None:
            return None

        def exec_command(self, command: str) -> None:
            assert command == "agent status"

        def sendall(self, input_data: bytes) -> None:
            self.input_data = input_data

        def shutdown_write(self) -> None:
            return None

        def recv_ready(self) -> bool:
            return bool(self.stdout)

        def recv(self, _size: int) -> bytes:
            return self.stdout.pop(0)

        def recv_stderr_ready(self) -> bool:
            return False

        def recv_stderr(self, _size: int) -> bytes:
            return b""

        def exit_status_ready(self) -> bool:
            return True

        def recv_exit_status(self) -> int:
            return 0

        def close(self) -> None:
            self.closed = True

    class FakeTransport:
        def __init__(self, channel: FakeChannel) -> None:
            self.channel = channel

        def is_active(self) -> bool:
            return True

        def open_session(self, *, timeout: float) -> FakeChannel:
            assert timeout > 0
            return self.channel

    channel = FakeChannel()
    client = object.__new__(device_installer._ParamikoDeviceSshClient)
    client._paramiko = types.SimpleNamespace(SSHException=RuntimeError)
    client._client = types.SimpleNamespace(
        get_transport=lambda: FakeTransport(channel)
    )

    assert client.run("agent status", b"payload") == "ok\n"
    assert channel.input_data == b"payload"
    assert channel.closed is True


def test_paramiko_client_run_fails_when_transport_inactive() -> None:
    client = object.__new__(device_installer._ParamikoDeviceSshClient)
    client._client = types.SimpleNamespace(get_transport=lambda: None)

    try:
        client.run("agent status")
    except device_installer.C300XDeviceInstallError as err:
        assert err.reason == "device_install_failed"
    else:  # pragma: no cover
        raise AssertionError("inactive transport was accepted")


def test_paramiko_client_run_reports_nonzero_exit() -> None:
    class FakeChannel:
        def __init__(self) -> None:
            self.stderr = [b"failed"]

        def settimeout(self, _timeout: float) -> None:
            return None

        def exec_command(self, _command: str) -> None:
            return None

        def shutdown_write(self) -> None:
            return None

        def recv_ready(self) -> bool:
            return False

        def recv(self, _size: int) -> bytes:
            return b""

        def recv_stderr_ready(self) -> bool:
            return bool(self.stderr)

        def recv_stderr(self, _size: int) -> bytes:
            return self.stderr.pop(0)

        def exit_status_ready(self) -> bool:
            return True

        def recv_exit_status(self) -> int:
            return 1

        def close(self) -> None:
            return None

    class FakeTransport:
        def is_active(self) -> bool:
            return True

        def open_session(self, *, timeout: float) -> FakeChannel:
            assert timeout > 0
            return FakeChannel()

    client = object.__new__(device_installer._ParamikoDeviceSshClient)
    client._paramiko = types.SimpleNamespace(SSHException=RuntimeError)
    client._client = types.SimpleNamespace(get_transport=lambda: FakeTransport())

    try:
        client.run("agent status")
    except device_installer.C300XDeviceInstallError as err:
        assert err.reason == "device_install_failed"
    else:  # pragma: no cover
        raise AssertionError("nonzero command exit was accepted")


def test_paramiko_put_file_replaces_changed_payload(tmp_path: Path) -> None:
    payload = tmp_path / "config.json"
    payload.write_bytes(b"new")
    commands: list[tuple[str, bytes | None]] = []

    client = object.__new__(device_installer._ParamikoDeviceSshClient)

    def fake_run(command: str, input_data: bytes | None = None) -> str:
        commands.append((command, input_data))
        if command.startswith("python - "):
            return "not-a-valid-sha\n"
        if ".new" in command and "mv -f" in command:
            return ""
        raise AssertionError(f"unexpected command: {command}")

    client.run = fake_run

    assert client.put_file(payload, "/remote/config.json", "600") is True
    assert commands[-1] == (
        "umask 077 && cat > /remote/config.json.new && "
        "chmod 600 /remote/config.json.new && "
        "mv -f /remote/config.json.new /remote/config.json",
        b"new",
    )


def test_paramiko_client_init_connects_with_legacy_options(monkeypatch: Any) -> None:
    events: list[tuple[str, Any]] = []

    class FakeSSHClient:
        def set_missing_host_key_policy(self, policy: Any) -> None:
            events.append(("policy", type(policy).__name__))

        def connect(self, **kwargs: Any) -> None:
            events.append(("connect", kwargs))

        def close(self) -> None:
            events.append(("close", None))

    class FakeParamiko:
        __version__ = "3.5.1"
        AuthenticationException = RuntimeError
        SSHException = RuntimeError
        SSHClient = FakeSSHClient

        class AutoAddPolicy:
            pass

    monkeypatch.setitem(sys.modules, "paramiko", FakeParamiko)

    client = device_installer._ParamikoDeviceSshClient(
        C300XDeviceInstallRequest(
            host="[fe80::1]",
            ssh_username=" root ",
            ssh_password="secret",
        )
    )
    client.close()

    assert events[0] == ("policy", "AutoAddPolicy")
    assert events[1][0] == "connect"
    assert events[1][1]["hostname"] == "fe80::1"
    assert events[1][1]["username"] == "root"
    assert events[2] == ("close", None)


def test_paramiko_client_init_reports_connect_failures(monkeypatch: Any) -> None:
    class FakeParamiko:
        __version__ = "3.5.1"

        class AuthenticationException(Exception):
            pass

        class SSHException(Exception):
            pass

        class AutoAddPolicy:
            pass

        class SSHClient:
            def set_missing_host_key_policy(self, _policy: Any) -> None:
                return None

            def connect(self, **_kwargs: Any) -> None:
                raise FakeParamiko.AuthenticationException("denied")

    monkeypatch.setitem(sys.modules, "paramiko", FakeParamiko)

    try:
        device_installer._ParamikoDeviceSshClient(
            C300XDeviceInstallRequest(
                host="c300x.local",
                ssh_username="root",
                ssh_password="secret",
            )
        )
    except device_installer.C300XDeviceInstallError as err:
        assert err.reason == "device_install_failed"
    else:  # pragma: no cover
        raise AssertionError("connect failure was accepted")


def test_paramiko_client_init_reports_missing_dependency(monkeypatch: Any) -> None:
    monkeypatch.delitem(sys.modules, "paramiko", raising=False)

    original_import = __import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "paramiko":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    try:
        device_installer._ParamikoDeviceSshClient(
            C300XDeviceInstallRequest(
                host="c300x.local",
                ssh_username="root",
                ssh_password="secret",
            )
        )
    except device_installer.C300XDeviceInstallError as err:
        assert err.reason == "installer_dependency_missing"
    else:  # pragma: no cover
        raise AssertionError("missing Paramiko dependency was accepted")


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
            if command.startswith("python - "):
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
    assert ".c300x-native-agent-init.new" not in link_repair
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
            if command.startswith("python - "):
                for path, digest in hashes.items():
                    if path in command:
                        return digest + "\n"
                raise device_installer.C300XDeviceInstallError("device_install_failed")
            if command.startswith("stat -c %a "):
                return "644\n"
            if command.startswith("readlink "):
                raise device_installer.C300XDeviceInstallError("device_install_failed")
            if command.startswith("umask 077 && cat > "):
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
    assert update_command.endswith("mount -o remount,ro /; fi; exit $rc")


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
            if command.startswith("python - "):
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
        "8091"
    ]


def test_paramiko_connect_kwargs_force_legacy_ssh_rsa() -> None:
    kwargs = device_installer._paramiko_connect_kwargs(
        C300XDeviceInstallRequest(
            host="[fe80::1]",
            ssh_username=" root ",
            ssh_password="secret",
        )
    )

    assert kwargs["hostname"] == "fe80::1"
    assert kwargs["username"] == "root"
    assert kwargs["look_for_keys"] is False
    assert kwargs["allow_agent"] is False
    assert kwargs["disabled_algorithms"] == {
        "keys": ("rsa-sha2-512", "rsa-sha2-256"),
        "pubkeys": ("rsa-sha2-512", "rsa-sha2-256"),
    }


def test_installer_rejects_unvalidated_paramiko_versions() -> None:
    class FakeParamiko:
        __version__ = "4.0.0"

    try:
        device_installer._validate_paramiko_version(FakeParamiko)
    except device_installer.C300XDeviceInstallError as err:
        assert err.reason == "installer_dependency_missing"
    else:  # pragma: no cover
        raise AssertionError("Expected installer_dependency_missing")


def test_manifest_does_not_require_optional_paramiko() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "bticino_c300x" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert not any(
        requirement.startswith("paramiko") for requirement in manifest["requirements"]
    )


def test_dev_requirements_pin_paramiko_with_legacy_ssh_rsa_support() -> None:
    requirement_files = (
        ROOT / "requirements-dev.in",
        ROOT / "requirements-dev.txt",
        ROOT / "requirements-dev-min-ha.txt",
    )

    for path in requirement_files:
        assert "paramiko==3.5.1" in path.read_text(encoding="utf-8").splitlines()


def test_manifest_does_not_require_aiortc() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "bticino_c300x" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert not any(
        requirement.startswith("aiortc") for requirement in manifest["requirements"]
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
