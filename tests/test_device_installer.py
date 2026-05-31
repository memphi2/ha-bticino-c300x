from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import custom_components.bticino_c300x.device_installer as device_installer  # noqa: E402
from custom_components.bticino_c300x.device_installer import (  # noqa: E402
    DEFAULT_REMOTE_DIR,
    C300XDeviceInstallRequest,
    _device_config_json,
    _render_startup_defaults,
    async_install_device_agent,
    installer_bundle_status,
)


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
    assert config["video"]["enabled"] is True
    assert config["displayBridge"]["enabled"] is False


def test_installer_bundle_uses_built_agent_without_running_make() -> None:
    status = installer_bundle_status()

    if status["available"]:
        payloads = status["payloads"]
        assert any(payload.endswith("/c300x-agent-native") for payload in payloads)
        assert any(payload.endswith("/qml_patch.sh") for payload in payloads)
        assert any(payload.endswith("/remove_agent.sh") for payload in payloads)
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

    assert config["events"]["subscriptionStorePath"] == f"{remote_dir}/subscriptions.json"
    assert config["maintenance"]["qmlPatch"]["script"] == f"{remote_dir}/qml_patch.sh"
    assert config["maintenance"]["agentRemove"]["script"] == f"{remote_dir}/remove_agent.sh"


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
            return ""

        def put_file(
            self,
            source: Path,
            remote_path: str,
            mode: str | None = None,
        ) -> None:
            self.uploads.append((source.name, remote_path, mode))

        def close(self) -> None:
            self.closed = True

    agent = tmp_path / "c300x-agent-native"
    qml_patch = tmp_path / "qml_patch.sh"
    remove_agent = tmp_path / "remove_agent.sh"
    init_script = tmp_path / "c300x-native-agent"
    alarm_qml = tmp_path / "Alarm.qml"
    for path in (agent, qml_patch, remove_agent, alarm_qml):
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
    assert any(f"{remote_dir}/qml_patch.sh" in command[0] for command in fake_client.commands)
    assert f"{remote_dir}/config.json" in result.installed_files
    assert f"{remote_dir}/c300x-agent.env" in result.installed_files


def test_ssh_host_unwraps_ipv6_brackets() -> None:
    assert device_installer._ssh_host("[fe80::1]") == "fe80::1"
    assert device_installer._ssh_host("c300x.local") == "c300x.local"


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


def test_manifest_pins_paramiko_with_legacy_ssh_rsa_support() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "bticino_c300x" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert "paramiko==3.5.1" in manifest["requirements"]
