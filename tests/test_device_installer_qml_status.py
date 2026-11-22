"""Verify bootstrap patch results through the production install sequence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.bticino_c300x import device_installer as installer


def _success(action: str) -> str:
    return json.dumps({
        "ok": True,
        "core_patched": True,
        "gui_running": True,
        "patched": action == "apply",
    })


class FakeClient:
    def __init__(self) -> None:
        self.responses = {action: _success(action) for action in ("core-apply", "apply")}
        self.actions: list[str] = []
        self.closed = False

    def run(self, command: str) -> str:
        if "qml_patch.sh " in command:
            action = command.rsplit(" ", 1)[1]
            self.actions.append(action)
            return self.responses[action]
        if command == f"readlink {installer.REMOTE_INIT_LINK}":
            return installer.REMOTE_INIT_SCRIPT
        return ""

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    client = FakeClient()
    monkeypatch.setattr(installer, "_connect_device_client", lambda _r: client)
    monkeypatch.setattr(installer, "_read_remote_config_sync", lambda *_a: {})
    monkeypatch.setattr(installer, "_write_remote_file_sync", lambda *_a, **_k: False)
    monkeypatch.setattr(installer, "_install_startup_script_sync", lambda *_a: [])
    return client


def _install(*, apply_gui_patch: bool = True) -> tuple[str, ...]:
    request = installer.C300XDeviceInstallRequest(
        host="unused.local", ssh_username="root", ssh_password="unused",
        apply_firewall_patch=False, apply_gui_patch=apply_gui_patch,
    )
    return installer._install_device_agent_sync(
        request, installer._ResolvedBundle((), Path("unused-init")), b"{}"
    )


@pytest.mark.parametrize("action", ["core-apply", "apply"])
@pytest.mark.parametrize("response", [
    "", "not-json", "[]", "null", "{}",
    json.dumps({"ok": False, "state": "reload_failed", "core_patched": None,
                "gui_running": False}),
    json.dumps({"ok": True, "core_patched": False, "gui_running": True, "patched": True}),
    json.dumps({"ok": True, "core_patched": True, "gui_running": False, "patched": True}),
    json.dumps({"ok": 1, "core_patched": True, "gui_running": True, "patched": True}),
    *[json.dumps({"ok": True, "core_patched": True, "gui_running": True,
                  "patched": True, "qt5_overlay": overlay})
      for overlay in ("failed", "incomplete", "off", "unknown")],
])
def test_unsuccessful_patch_cannot_report_install_success(
    client: FakeClient, action: str, response: str
) -> None:
    client.responses[action] = response

    with pytest.raises(installer.C300XDeviceInstallError, match="device_install_verify_failed"):
        _install()

    assert client.closed
    assert client.actions == (["core-apply"] if action == "core-apply" else ["core-apply", "apply"])


@pytest.mark.parametrize("patched", [False, None, 1, "true"])
def test_full_patch_requires_complete_feature_patch(client: FakeClient, patched: object) -> None:
    result = json.loads(_success("apply"))
    result["patched"] = patched
    client.responses["apply"] = json.dumps(result)

    with pytest.raises(installer.C300XDeviceInstallError, match="device_install_verify_failed"):
        _install()

    assert client.closed
    assert client.actions == ["core-apply", "apply"]


@pytest.mark.parametrize("apply_gui_patch", [False, True])
def test_verified_core_and_optional_full_patch_succeed(
    client: FakeClient, apply_gui_patch: bool
) -> None:
    assert _install(apply_gui_patch=apply_gui_patch) == ()
    assert client.closed
    assert client.actions == (["core-apply", "apply"] if apply_gui_patch else ["core-apply"])


def test_verified_qt5_activation_succeeds(client: FakeClient) -> None:
    for action in client.responses:
        client.responses[action] = json.dumps({**json.loads(_success(action)), "qt5_overlay": "active"})
    assert _install() == ()
