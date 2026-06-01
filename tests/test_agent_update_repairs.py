from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field
from typing import Any

homeassistant = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
homeassistant.__path__ = []
components = sys.modules.setdefault(
    "homeassistant.components",
    types.ModuleType("homeassistant.components"),
)
components.__path__ = []
repairs_module = types.ModuleType("homeassistant.components.repairs")
core = sys.modules.setdefault("homeassistant.core", types.ModuleType("homeassistant.core"))
config_entries = sys.modules.setdefault(
    "homeassistant.config_entries",
    types.ModuleType("homeassistant.config_entries"),
)
helpers = sys.modules.setdefault(
    "homeassistant.helpers",
    types.ModuleType("homeassistant.helpers"),
)
config_validation = types.ModuleType("homeassistant.helpers.config_validation")
dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
issue_registry = types.ModuleType("homeassistant.helpers.issue_registry")


class RepairsFlow:  # pragma: no cover - import-time stub only
    pass


class HomeAssistant:  # pragma: no cover - import-time stub only
    pass


class ConfigEntry:  # pragma: no cover - import-time stub only
    pass


repairs_module.RepairsFlow = RepairsFlow
core.HomeAssistant = HomeAssistant
core.callback = lambda func: func
config_entries.ConfigEntry = ConfigEntry
issue_registry.async_delete_issue = lambda **_kwargs: None
config_validation.config_entry_only_config_schema = lambda _domain: dict
dispatcher.async_dispatcher_send = lambda *_args, **_kwargs: None
helpers.config_validation = config_validation
helpers.dispatcher = dispatcher
helpers.issue_registry = issue_registry
sys.modules["homeassistant.components.repairs"] = repairs_module
sys.modules["homeassistant.core"] = core
sys.modules["homeassistant.config_entries"] = config_entries
sys.modules["homeassistant.helpers.config_validation"] = config_validation
sys.modules["homeassistant.helpers.dispatcher"] = dispatcher
sys.modules["homeassistant.helpers.issue_registry"] = issue_registry

from custom_components.bticino_c300x.const import CONF_DEVICE_UI_ENABLED  # noqa: E402
from custom_components.bticino_c300x.repairs import (  # noqa: E402
    _AGENT_UPDATE_RESTART_SETTLE_SECONDS,
    DeviceAgentUpdateRepairFlow,
    _async_apply_repaired_agent_setup,
    _async_capture_external_patch_state,
    _async_reload_entry_after_agent_update,
    _async_restore_external_patch_state,
    _async_verify_agent_after_update,
    _ExternalPatchChanges,
    _ExternalPatchState,
)


class FakePatchApi:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.qml_status = {"available": True, "patched": True, "state": "patched"}
        self.firewall_status = {
            "available": True,
            "patched": True,
            "state": "patched",
        }
        self.ipv6_firewall_status = {
            "available": True,
            "patched": True,
            "state": "patched",
        }

    async def async_qml_patch_status(self) -> dict[str, Any]:
        self.calls.append("qml_status")
        return self.qml_status

    async def async_apply_qml_patch(self) -> dict[str, Any]:
        self.calls.append("apply_qml")
        return {"available": True, "patched": True, "state": "patched"}

    async def async_firewall_status(self) -> dict[str, Any]:
        self.calls.append("firewall_status")
        return self.firewall_status

    async def async_apply_firewall(self) -> dict[str, Any]:
        self.calls.append("apply_firewall")
        return {"available": True, "patched": True, "state": "patched"}

    async def async_ipv6_firewall_status(self) -> dict[str, Any]:
        self.calls.append("ipv6_firewall_status")
        return self.ipv6_firewall_status

    async def async_set_ipv6_firewall_enabled(self, enabled: bool) -> dict[str, Any]:
        self.calls.append(f"set_ipv6_firewall_enabled:{enabled}")
        return {"ipv6_firewall_enabled": enabled}

    async def async_apply_ipv6_firewall(self) -> dict[str, Any]:
        self.calls.append("apply_ipv6_firewall")
        return {"available": True, "patched": True, "state": "patched"}


class FakeUpdateVerifyApi:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def async_validate_setup(self) -> dict[str, Any]:
        self.calls.append("validate_setup")
        return {
            "version": "0.3.1",
            "api_version": "1",
            "capabilities": {"system_metrics": {"supported": True, "memory": True}},
            "agent": {
                "version": "0.3.1",
                "self_update_supported": True,
            },
        }


@dataclass(slots=True)
class FakeRuntimeData:
    api: FakePatchApi
    capabilities: dict[str, Any] = field(default_factory=dict)
    agent_info: dict[str, Any] = field(default_factory=dict)
    qml_patch_status: dict[str, Any] = field(default_factory=dict)
    qml_patch_status_updated_at: Any = None
    agent_update_state: Any = None


@dataclass(slots=True)
class FakeEntry:
    runtime_data: FakeRuntimeData
    entry_id: str = "entry-1"
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


class FakeConfigEntries:
    def __init__(self, entry: Any) -> None:
        self._entry = entry
        self.reloads: list[str] = []

    def async_get_entry(self, entry_id: str) -> Any:
        return self._entry

    async def async_reload(self, entry_id: str) -> bool:
        self.reloads.append(entry_id)
        return True


class FakeHass:
    def __init__(self, entry: Any) -> None:
        self.config_entries = FakeConfigEntries(entry)

    async def async_add_executor_job(self, target, *args):  # noqa: ANN001
        return target(*args)


class FakeAgentUpdateState:
    self_update_repair_supported = False

    @property
    def repair_placeholders(self) -> dict[str, str]:
        return {
            "installed_version": "0.2.0",
            "available_version": "0.3.1",
            "installed_api_version": "1",
            "available_api_version": "1",
            "reason": "self_update_not_supported",
        }


def test_repair_flow_init_ignores_internal_flow_data() -> None:
    """Creating a repair flow must not submit the SSH form immediately."""

    runtime_data = FakeRuntimeData(FakePatchApi())
    runtime_data.agent_update_state = FakeAgentUpdateState()
    entry = FakeEntry(runtime_data=runtime_data)
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]

    def show_form(**kwargs: Any) -> dict[str, Any]:
        return {"type": "form", **kwargs}

    flow.async_show_form = show_form  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_init({"issue_id": "from-flow-manager"}))

    assert result["type"] == "form"
    assert result["step_id"] == "ssh_install"
    assert result.get("errors") is None
    assert entry.runtime_data.api.calls == []


def test_apply_repaired_agent_setup_refreshes_runtime_state(monkeypatch) -> None:
    import custom_components.bticino_c300x.agent_update as agent_update
    import custom_components.bticino_c300x.repairs as repairs

    dispatched: list[tuple[str, str]] = []

    async def async_bundle_metadata(_hass: Any) -> dict[str, str]:
        return {"agent_version": "0.3.1", "api_version": "1"}

    monkeypatch.setattr(
        repairs,
        "async_dispatcher_send",
        lambda _hass, signal, entry_id: dispatched.append((signal, entry_id)),
    )
    monkeypatch.setattr(
        agent_update,
        "async_load_packaged_bundle_metadata",
        async_bundle_metadata,
    )
    runtime_data = FakeRuntimeData(FakePatchApi())
    entry = FakeEntry(runtime_data=runtime_data)
    hass = FakeHass(entry)

    asyncio.run(
        _async_apply_repaired_agent_setup(
            hass,  # type: ignore[arg-type]
            entry,
            {
                "version": "0.3.1",
                "api_version": "1",
                "capabilities": {
                    "system_metrics": {"supported": True, "memory": True}
                },
            },
        )
    )

    assert runtime_data.agent_info["version"] == "0.3.1"
    assert runtime_data.capabilities["system_metrics"]["memory"] is True
    assert runtime_data.agent_update_state.update_required is False
    assert dispatched == [("bticino_c300x_agent_info_changed", "entry-1")]


def test_reload_entry_after_agent_update_uses_config_entry_reload() -> None:
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    hass = FakeHass(entry)

    asyncio.run(_async_reload_entry_after_agent_update(hass, "entry-1"))  # type: ignore[arg-type]

    assert hass.config_entries.reloads == ["entry-1"]


def test_capture_external_patch_state_reads_status_without_writes() -> None:
    api = FakePatchApi()
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(api),
        options={CONF_DEVICE_UI_ENABLED: False},
    )

    patch_state = asyncio.run(_async_capture_external_patch_state(entry))

    assert patch_state.qml_patch_required is True
    assert patch_state.firewall_patched is True
    assert patch_state.firewall_status_known is True
    assert patch_state.ipv6_firewall_patched is True
    assert api.calls == [
        "qml_status",
        "firewall_status",
        "ipv6_firewall_status",
    ]


def test_verify_agent_update_waits_for_scheduled_restart(
    monkeypatch,
) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    api = FakeUpdateVerifyApi()
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(repairs.asyncio, "sleep", fake_sleep)

    result = asyncio.run(
        _async_verify_agent_after_update(
            api,
            {"ok": True, "restart_scheduled": True},
        )
    )

    assert result["version"] == "0.3.1"
    assert sleeps == [_AGENT_UPDATE_RESTART_SETTLE_SECONDS]
    assert api.calls == ["validate_setup"]


def test_capture_external_patch_state_marks_unknown_firewall_status() -> None:
    api = FakePatchApi()
    api.firewall_status = {"available": True, "state": "disabled", "patched": None}
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))

    patch_state = asyncio.run(_async_capture_external_patch_state(entry))

    assert patch_state.firewall_patched is False
    assert patch_state.firewall_status_known is False


def test_restore_external_patch_state_skips_active_patches_without_source_changes() -> None:
    api = FakePatchApi()
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))

    asyncio.run(
        _async_restore_external_patch_state(
            entry,
            _ExternalPatchState(
                qml_patch_required=True,
                firewall_patched=True,
                firewall_status_known=True,
                ipv6_firewall_patched=False,
            ),
            _ExternalPatchChanges(),
        )
    )

    assert api.calls == []


def test_restore_external_patch_state_applies_only_changed_active_patches() -> None:
    api = FakePatchApi()
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))

    asyncio.run(
        _async_restore_external_patch_state(
            entry,
            _ExternalPatchState(
                qml_patch_required=True,
                firewall_patched=True,
                firewall_status_known=True,
                ipv6_firewall_patched=False,
            ),
            _ExternalPatchChanges(
                qml_patch_changed=True,
                firewall_patch_changed=True,
            ),
        )
    )

    assert api.calls == [
        "apply_firewall",
        "apply_qml",
        "qml_status",
    ]
    assert entry.runtime_data.qml_patch_status["state"] == "patched"


def test_restore_external_patch_state_reenables_ipv6_endpoint_before_apply() -> None:
    api = FakePatchApi()
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))

    asyncio.run(
        _async_restore_external_patch_state(
            entry,
            _ExternalPatchState(
                qml_patch_required=False,
                firewall_patched=False,
                firewall_status_known=True,
                ipv6_firewall_patched=True,
            ),
            _ExternalPatchChanges(ipv6_firewall_patch_changed=True),
        )
    )

    assert api.calls == [
        "set_ipv6_firewall_enabled:True",
        "apply_ipv6_firewall",
    ]


def test_install_result_config_change_restores_active_ipv6_firewall_patch() -> None:
    changes = _ExternalPatchChanges.from_install_result(
        types.SimpleNamespace(
            changed_files=(
                "/home/bticino/cfg/extra/c300x-native-agent/config.json",
            )
        )
    )

    assert changes.config_schema_changed is True
    assert changes.qml_patch_changed is False
    assert changes.firewall_patch_changed is False
    assert changes.ipv6_firewall_patch_changed is True


def test_install_result_firewall_script_change_restores_firewall_patches() -> None:
    changes = _ExternalPatchChanges.from_install_result(
        types.SimpleNamespace(
            changed_files=(
                "/home/bticino/cfg/extra/c300x-native-agent/bootstrap_firewall.sh",
            )
        )
    )

    assert changes.config_schema_changed is False
    assert changes.firewall_patch_changed is True
    assert changes.ipv6_firewall_patch_changed is True


def test_restore_external_patch_state_skips_inactive_changed_patches() -> None:
    api = FakePatchApi()
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))

    asyncio.run(
        _async_restore_external_patch_state(
            entry,
            _ExternalPatchState(
                qml_patch_required=False,
                firewall_patched=False,
                firewall_status_known=True,
                ipv6_firewall_patched=False,
            ),
            _ExternalPatchChanges(
                qml_patch_changed=True,
                firewall_patch_changed=True,
                ipv6_firewall_patch_changed=True,
            ),
        )
    )

    assert api.calls == []
