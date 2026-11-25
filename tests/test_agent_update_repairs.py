from __future__ import annotations

import asyncio
import json
import re
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from homeassistant.components.lovelace.const import ConfigNotFound

IGNORED_ISSUES: list[tuple[str, str, bool]] = []

from custom_components.bticino_c300x.api import C300XAgentApiError  # noqa: E402
from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_CALLBACK_BASE_URL,
    CONF_DEVICE_UI_ENABLED,
    CONF_DISPLAY_FOLLOWUP_PENDING,
    CONF_FRONTEND_CARD_SETUP_DISMISSED,
    CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION,
    DOMAIN,
    FRONTEND_CARD_SETUP_REPAIR_VERSION,
)
from custom_components.bticino_c300x.repair_flows_frontend import (  # noqa: E402
    _LOVELACE_DASHBOARD_FIELD,
    _LOVELACE_VIEW_FIELD,
    FrontendCardSetupRepairFlow,
    _async_setup_lovelace_cards,
    _c300x_view,
    _cards_for_view,
    _dashboard_select_options,
    _dashboard_selector_value,
    _empty_placeholder_view,
    _lovelace_dashboard_path,
    _LovelaceCardSetupError,
    _normalize_lovelace_target,
    _remove_empty_placeholder_views,
    _submitted_dashboard_path,
    _submitted_view_path,
)
from custom_components.bticino_c300x.repairs import (  # noqa: E402
    _AGENT_UPDATE_RESTART_SETTLE_SECONDS,
    AGENT_CAPABILITY_MISMATCH_ISSUE,
    DEVICE_AGENT_UPDATE_REQUIRED_ISSUE,
    DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
    DEVICE_USER_REQUIRED_ISSUE,
    FRONTEND_CARD_SETUP_HINT_ISSUE,
    MEDIA_SETUP_REPAIR_REQUIRED_ISSUE,
    UNSUPPORTED_CALLBACK_URL_ISSUE,
    CallbackUrlRepairFlow,
    DeviceAgentUpdateRepairFlow,
    DeviceCoreQmlHookRepairFlow,
    DeviceUserRepairFlow,
    MediaSetupRepairFlow,
    _async_apply_repaired_agent_setup,
    _async_capture_external_patch_state,
    _async_reload_entry_after_agent_update,
    _async_repair_media_setup,
    _async_restore_external_patch_state,
    _async_verify_agent_after_update,
    _async_wait_for_agent_after_update,
    _ExternalPatchChanges,
    _ExternalPatchState,
    _media_setup_repair_placeholders,
    _validated_callback_base_url,
    async_create_fix_flow,
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
        self.device_user_status = {"homeassistant_user_present": True}
        self.self_test_status = {"ok": True, "checks": {}}

    async def async_qml_patch_status(self) -> dict[str, Any]:
        self.calls.append("qml_status")
        return self.qml_status

    async def async_apply_qml_patch(
        self,
        *,
        dynamic_homepage: bool = False,
    ) -> dict[str, Any]:
        _ = dynamic_homepage
        self.calls.append("apply_qml")
        return {"available": True, "patched": True, "state": "patched"}

    async def async_apply_qml_core_patch(self) -> dict[str, Any]:
        self.calls.append("apply_qml_core")
        return {
            "available": True,
            "patched": False,
            "state": "original",
            "core_patched": True,
            "core_state": "patched",
        }

    async def async_reload_gui(self, *, display_restart: bool = False) -> dict[str, Any]:
        self.calls.append("reload_gui")
        self.reload_display_restart = display_restart
        return {"ok": True, "action": "reload_gui"}

    async def async_firewall_status(self) -> dict[str, Any]:
        self.calls.append("firewall_status")
        return self.firewall_status

    async def async_apply_firewall(self) -> dict[str, Any]:
        self.calls.append("apply_firewall")
        return {"available": True, "patched": True, "state": "patched"}

    async def async_set_firewall_enabled(self, enabled: bool) -> dict[str, Any]:
        self.calls.append(f"set_firewall_enabled:{enabled}")
        return {"firewall_enabled": enabled}

    async def async_ipv6_firewall_status(self) -> dict[str, Any]:
        self.calls.append("ipv6_firewall_status")
        return self.ipv6_firewall_status

    async def async_set_ipv6_firewall_enabled(self, enabled: bool) -> dict[str, Any]:
        self.calls.append(f"set_ipv6_firewall_enabled:{enabled}")
        return {"ipv6_firewall_enabled": enabled}

    async def async_apply_ipv6_firewall(self) -> dict[str, Any]:
        self.calls.append("apply_ipv6_firewall")
        return {"available": True, "patched": True, "state": "patched"}

    async def async_ensure_homeassistant_user(
        self,
        *,
        account_label: str,
    ) -> dict[str, Any]:
        self.calls.append(f"ensure_homeassistant_user:{account_label}")
        return self.device_user_status

    async def async_self_test(self) -> dict[str, Any]:
        self.calls.append("self_test")
        return self.self_test_status

    async def async_validate_setup(self) -> dict[str, Any]:
        self.calls.append("validate_setup")
        return {"version": "1.1.0", "capabilities": {}}

    async def async_device_user_status(self) -> dict[str, Any]:
        self.calls.append("device_user_status")
        return self.device_user_status

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
                "bundle_hash": "sha256:bundle",
                "self_update_supported": True,
            },
        }


@dataclass(slots=True)
class FakeRuntimeData:
    api: FakePatchApi
    capabilities: dict[str, Any] = field(default_factory=dict)
    agent_info: dict[str, Any] = field(default_factory=dict)
    device_user_status: dict[str, Any] = field(default_factory=dict)
    self_test_status: dict[str, Any] = field(default_factory=dict)
    connection_state: Any = field(
        default_factory=lambda: types.SimpleNamespace(available=True)
    )
    event_state: Any = field(
        default_factory=lambda: types.SimpleNamespace(
            smartphone_forwarding_mode="homeassistant"
        )
    )
    qml_patch_status: dict[str, Any] = field(default_factory=dict)
    qml_patch_status_updated_at: Any = None
    agent_update_state: Any = None
    diagnostics: Any = None


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

    def async_update_entry(self, entry: Any, **kwargs: Any) -> None:
        if "data" in kwargs:
            entry.data = kwargs["data"]
        if "options" in kwargs:
            entry.options = kwargs["options"]


class FakeHass:
    def __init__(self, entry: Any) -> None:
        self.config_entries = FakeConfigEntries(entry)
        self.config = types.SimpleNamespace(location_name="HA Test")
        self.data: dict[Any, Any] = {}

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


class FakeSelfUpdateState:
    self_update_repair_supported = True
    update_required = True

    @property
    def repair_placeholders(self) -> dict[str, str]:
        return {
            "installed_version": "1.0.0",
            "available_version": "1.1.0",
            "installed_api_version": "1",
            "available_api_version": "1",
            "installed_bundle_hash": "old",
            "available_bundle_hash": "new",
            "reason": "version_mismatch",
            "update_path": "self_update",
        }


@pytest.fixture(autouse=True)
def repair_ha_boundary(monkeypatch):
    from custom_components.bticino_c300x import repairs

    IGNORED_ISSUES.clear()
    monkeypatch.setattr(repairs, "async_dispatcher_send", lambda *_: None)
    monkeypatch.setattr(repairs.ir, "async_delete_issue", lambda **_: None)
    monkeypatch.setattr(
        repairs.ir, "async_ignore_issue",
        lambda hass, domain, issue_id, ignore: IGNORED_ISSUES.append((domain, issue_id, ignore)),
    )


def test_create_fix_flow_routes_known_issues() -> None:
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    hass = FakeHass(entry)

    cases = (
        (AGENT_CAPABILITY_MISMATCH_ISSUE, DeviceAgentUpdateRepairFlow),
        (DEVICE_AGENT_UPDATE_REQUIRED_ISSUE, DeviceAgentUpdateRepairFlow),
        (UNSUPPORTED_CALLBACK_URL_ISSUE, CallbackUrlRepairFlow),
        (DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE, DeviceCoreQmlHookRepairFlow),
        (DEVICE_USER_REQUIRED_ISSUE, DeviceUserRepairFlow),
        (MEDIA_SETUP_REPAIR_REQUIRED_ISSUE, MediaSetupRepairFlow),
        (FRONTEND_CARD_SETUP_HINT_ISSUE, FrontendCardSetupRepairFlow),
    )

    for issue_type, expected_type in cases:
        flow = asyncio.run(
            async_create_fix_flow(
                hass,  # type: ignore[arg-type]
                f"{issue_type}_entry-1",
                {"issue_type": issue_type, "entry_id": "entry-1"},
            )
        )

        assert isinstance(flow, expected_type)


def test_create_fix_flow_rejects_unknown_or_incomplete_issue_data() -> None:
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    hass = FakeHass(entry)

    for data in (None, {}, {"issue_type": DEVICE_USER_REQUIRED_ISSUE}):
        try:
            asyncio.run(
                async_create_fix_flow(
                    hass,  # type: ignore[arg-type]
                    "unknown",
                    data,  # type: ignore[arg-type]
                )
            )
        except ValueError as err:
            assert "unknown repair issue" in str(err)
        else:  # pragma: no cover - defensive assertion
            raise AssertionError("unknown repair issue was accepted")


def test_repair_flow_init_ignores_internal_flow_data() -> None:
    """Creating a repair flow must not submit the SSH form immediately."""

    runtime_data = FakeRuntimeData(FakePatchApi())
    runtime_data.agent_update_state = FakeAgentUpdateState()
    entry = FakeEntry(runtime_data=runtime_data)
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]

    def show_form(**kwargs: Any) -> dict[str, Any]:
        return {"type": "form", **kwargs}

    def show_menu(**kwargs: Any) -> dict[str, Any]:
        return {"type": "menu", **kwargs}

    flow.async_show_form = show_form  # type: ignore[method-assign]
    flow.async_show_menu = show_menu  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_init({"issue_id": "from-flow-manager"}))

    assert result["type"] == "form"
    assert result["step_id"] == "ssh_install"
    assert result.get("errors") is None
    assert entry.runtime_data.api.calls == []


@pytest.mark.parametrize("bootstrap", [False, True])
@pytest.mark.parametrize("file_set", [2, 4])
def test_agent_update_repair_self_update_confirm_flow(monkeypatch, bootstrap, file_set) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    entry.runtime_data.agent_update_state = FakeSelfUpdateState()
    entry.runtime_data.agent_update_state.payload_bootstrap_required = bootstrap
    entry.runtime_data.api.qml_status = {"state": "patched", "patched": True}
    hass = FakeHass(entry)
    flow = DeviceAgentUpdateRepairFlow(hass, "entry-1")  # type: ignore[arg-type]
    calls: list[str] = []

    async def apply_update(_hass: Any, _api: Any) -> dict[str, Any]:
        if bootstrap:
            assert entry.data["agent_update_payload_pending"] is True
            # Home Assistant may not live to see the first pass return; the
            # display patch that is active now is already noted as due.
            assert entry.data["agent_update_qml_pending"] is True
        calls.append("apply_update")
        return {
            "ok": True, "restart_scheduled": False,
            "runtime_changed": bootstrap and calls.count("apply_update") == 1,
            "qml_patch_changed": bootstrap and calls.count("apply_update") == 2,
        }

    async def verify_update(
        _hass: Any,
        _api: Any,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        calls.append(f"verify:{result['ok']}")
        return {
            "version": "1.1.0", "capabilities": {},
            "agent": {"self_update_supported": True, "self_update_file_set_version": file_set},
        }

    async def restore_state(*_args: Any) -> None:
        calls.append("restore")
        if bootstrap:
            assert _args[2].runtime_changed
            assert _args[2].qml_patch_changed

    async def migrate_mqtt(_api: Any) -> None:
        calls.append("migrate_mqtt")

    async def apply_setup(_hass: Any, setup_entry: Any, _setup: dict[str, Any]) -> None:
        calls.append("apply_setup")
        setup_entry.runtime_data.agent_update_state = types.SimpleNamespace(
            update_required=False
        )

    monkeypatch.setattr(repairs, "async_apply_packaged_agent_update", apply_update)
    monkeypatch.setattr(repairs, "_async_verify_agent_after_update", verify_update)
    monkeypatch.setattr(repairs, "_async_restore_external_patch_state", restore_state)
    monkeypatch.setattr(repairs, "async_migrate_legacy_mqtt_if_available", migrate_mqtt)
    monkeypatch.setattr(repairs, "_async_apply_repaired_agent_setup", apply_setup)
    async def packaged_bundle(_hass: Any) -> dict[str, Any]:
        return {"agent_version": "1.1.0", "update_file_set_version": file_set}

    monkeypatch.setattr(repairs, "async_load_packaged_bundle_metadata", packaged_bundle)
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]

    form = asyncio.run(flow.async_step_confirm())
    result = asyncio.run(flow.async_step_confirm({}))

    assert form["type"] == "form"
    assert form["step_id"] == "confirm"
    assert result == {"type": "create_entry", "data": {}}
    assert calls == ["apply_update", "verify:True"] * (2 if bootstrap else 1) + [
        "restore",
        "migrate_mqtt",
        "apply_setup",
    ]
    assert hass.config_entries.reloads == ["entry-1"]
    assert "agent_update_payload_pending" not in entry.data


@pytest.mark.parametrize("bootstrap", [False, True])
def test_agent_update_repair_self_update_reports_failures(monkeypatch, bootstrap, caplog) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    entry.runtime_data.agent_update_state = FakeSelfUpdateState()
    entry.runtime_data.agent_update_state.payload_bootstrap_required = bootstrap
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]

    async def apply_update(_hass: Any, _api: Any) -> dict[str, Any]:
        raise C300XAgentApiError("upload failed")

    monkeypatch.setattr(repairs, "async_apply_packaged_agent_update", apply_update)
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result["type"] == "form"
    assert result["step_id"] == "confirm"
    assert result["errors"] == {"base": "update_failed"}
    assert entry.data.get("agent_update_payload_pending", False) is bootstrap
    # The user sees a translated form; the cause has to be in the log.
    assert any(
        "agent update failed" in record.getMessage() and "upload failed" in record.getMessage()
        for record in caplog.records
    )


def test_failed_second_transaction_remains_repairable_after_reload(monkeypatch) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    entry.runtime_data.agent_update_state = FakeSelfUpdateState()
    entry.runtime_data.agent_update_state.payload_bootstrap_required = True
    hass = FakeHass(entry)
    flow = DeviceAgentUpdateRepairFlow(hass, "entry-1")  # type: ignore[arg-type]
    setup = {"version": "1.9.9", "agent": {
        "bundle_hash": "sha256:abc", "self_update_supported": True,
        "self_update_file_set_version": 2,
    }}
    bundle = {"agent_version": "1.9.9", "bundle_hash": "sha256:abc",
              "update_file_set_version": 2}
    calls = 0

    async def apply_update(*_args: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise C300XAgentApiError("upload interrupted")
        return {"ok": True}

    async def verify(*_args: Any) -> dict[str, Any]:
        return setup

    async def packaged_bundle(*_args: Any) -> dict[str, Any]:
        return bundle

    monkeypatch.setattr(repairs, "async_apply_packaged_agent_update", apply_update)
    monkeypatch.setattr(repairs, "_async_verify_agent_after_update", verify)
    monkeypatch.setattr(repairs, "async_load_packaged_bundle_metadata", packaged_bundle)
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))
    assert result["errors"] == {"base": "update_failed"}
    assert calls == 2
    assert entry.data["agent_update_payload_pending"] is True
    asyncio.run(repairs._async_apply_repaired_agent_setup(hass, entry, setup))  # type: ignore[arg-type]
    assert entry.runtime_data.agent_update_state.update_required
    assert entry.runtime_data.agent_update_state.self_update_repair_supported
    assert not entry.runtime_data.agent_update_state.payload_bootstrap_required


def test_agent_update_repair_self_update_normalizes_changed_config(
    monkeypatch,
) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    class NormalizingApi(FakePatchApi):
        async def async_normalize_agent_config(self) -> dict[str, Any]:
            self.calls.append("normalize_config")
            return {"ok": True}

    entry = FakeEntry(runtime_data=FakeRuntimeData(NormalizingApi()))
    entry.runtime_data.agent_update_state = FakeSelfUpdateState()
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]

    async def apply_update(_hass: Any, _api: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "restart_scheduled": False,
            "config_schema_changed": True,
        }

    async def bundle_metadata(_hass: Any) -> dict[str, str]:
        return {"agent_version": "1.1.0", "api_version": "1"}

    async def restore_state(*_args: Any) -> None:
        return None

    async def migrate_mqtt(_api: Any) -> None:
        return None

    async def apply_setup(_hass: Any, setup_entry: Any, _setup: dict[str, Any]) -> None:
        setup_entry.runtime_data.agent_update_state = types.SimpleNamespace(
            update_required=False
        )

    monkeypatch.setattr(repairs, "async_apply_packaged_agent_update", apply_update)
    monkeypatch.setattr(repairs, "async_load_packaged_bundle_metadata", bundle_metadata)
    monkeypatch.setattr(repairs, "_async_restore_external_patch_state", restore_state)
    monkeypatch.setattr(repairs, "async_migrate_legacy_mqtt_if_available", migrate_mqtt)
    monkeypatch.setattr(repairs, "_async_apply_repaired_agent_setup", apply_setup)
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result == {"type": "create_entry", "data": {}}
    assert entry.runtime_data.api.calls.count("validate_setup") == 3
    assert "normalize_config" in entry.runtime_data.api.calls


def test_agent_update_repair_self_update_reports_verify_failure(monkeypatch) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    entry.runtime_data.agent_update_state = FakeSelfUpdateState()
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]

    async def apply_update(_hass: Any, _api: Any) -> dict[str, Any]:
        return {"ok": True}

    async def verify_update(
        _hass: Any,
        _api: Any,
        _result: dict[str, Any],
    ) -> dict[str, Any]:
        return {"version": "1.1.0", "capabilities": {}}

    async def apply_setup(_hass: Any, setup_entry: Any, _setup: dict[str, Any]) -> None:
        setup_entry.runtime_data.agent_update_state = FakeSelfUpdateState()

    async def restore_state(*_args: Any) -> None:
        return None

    async def migrate_mqtt(_api: Any) -> None:
        return None

    monkeypatch.setattr(repairs, "async_apply_packaged_agent_update", apply_update)
    monkeypatch.setattr(repairs, "_async_verify_agent_after_update", verify_update)
    monkeypatch.setattr(repairs, "_async_restore_external_patch_state", restore_state)
    monkeypatch.setattr(repairs, "async_migrate_legacy_mqtt_if_available", migrate_mqtt)
    monkeypatch.setattr(repairs, "_async_apply_repaired_agent_setup", apply_setup)
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result["type"] == "form"
    assert result["errors"] == {"base": "update_verify_failed"}


def test_agent_update_repair_aborts_when_entry_is_unloaded() -> None:
    flow = DeviceAgentUpdateRepairFlow(FakeHass(None), "entry-1")  # type: ignore[arg-type]
    flow.async_abort = lambda **kwargs: {"type": "abort", **kwargs}  # type: ignore[method-assign]

    confirm = asyncio.run(flow.async_step_confirm({}))
    ssh_install = asyncio.run(flow.async_step_ssh_install({}))

    assert confirm == {"type": "abort", "reason": "entry_not_loaded"}
    assert ssh_install == {"type": "abort", "reason": "entry_not_loaded"}


def test_agent_update_repair_ssh_install_success(monkeypatch) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    entry = FakeEntry(
        runtime_data=FakeRuntimeData(FakePatchApi()),
        data={
            "agent_host": "192.0.2.60",
            "agent_port": 8091,
            "agent_token": "agent-token",
            "maintenance_token": "maintenance-token",
        },
    )
    entry.runtime_data.agent_update_state = FakeAgentUpdateState()
    hass = FakeHass(entry)
    flow = DeviceAgentUpdateRepairFlow(hass, "entry-1")  # type: ignore[arg-type]
    calls: list[str] = []

    async def install_agent(request: Any, *, api_token: str, maintenance_token: str) -> Any:
        calls.append(
            f"install:{request.host}:{request.ssh_username}:{api_token}:{maintenance_token}"
        )
        return types.SimpleNamespace(changed_files=())

    async def ensure_installer_dependencies(_hass: Any) -> None:
        calls.append("ensure_deps")

    async def wait_for_agent(_api: Any) -> dict[str, Any]:
        calls.append("wait")
        return {"version": "1.1.0", "capabilities": {}}

    async def migrate_mqtt(_api: Any) -> None:
        calls.append("migrate_mqtt")

    async def apply_setup(_hass: Any, setup_entry: Any, _setup: dict[str, Any]) -> None:
        calls.append("apply_setup")
        setup_entry.runtime_data.agent_update_state = types.SimpleNamespace(
            update_required=False
        )

    monkeypatch.setattr(repairs, "async_install_device_agent", install_agent)
    monkeypatch.setattr(
        repairs,
        "async_ensure_installer_dependencies",
        ensure_installer_dependencies,
    )
    monkeypatch.setattr(repairs, "_async_wait_for_agent_after_update", wait_for_agent)
    monkeypatch.setattr(repairs, "async_migrate_legacy_mqtt_if_available", migrate_mqtt)
    monkeypatch.setattr(repairs, "_async_apply_repaired_agent_setup", apply_setup)
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(
        flow.async_step_ssh_install(
            {
                "bootstrap_ssh_username": "root",
                "bootstrap_ssh_password": "secret",
            }
        )
    )

    assert result == {"type": "create_entry", "data": {}}
    assert calls == [
        "ensure_deps",
        "install:192.0.2.60:root:agent-token:maintenance-token",
        "wait",
        "migrate_mqtt",
        "apply_setup",
    ]
    assert hass.config_entries.reloads == ["entry-1"]


def test_ssh_install_retry_runs_the_follow_up_steps_of_the_first_attempt(
    monkeypatch,
) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    api = FakePatchApi()
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(api),
        data={"agent_host": "192.0.2.60", "agent_token": "agent-token"},
    )
    entry.runtime_data.agent_update_state = FakeAgentUpdateState()
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    installs: list[tuple[str, ...]] = [
        ("/home/bticino/c300x/config.json", "/home/bticino/c300x/bootstrap_firewall.sh"),
        (),
    ]
    waits = [RuntimeError("agent did not come back"), {"version": "1.1.0", "capabilities": {}}]

    async def install_agent(*_args: Any, **_kwargs: Any) -> Any:
        changed = installs.pop(0)
        if not changed:
            # The first install replaced the config, so the device no longer
            # reports the IPv6 firewall as patched.
            api.ipv6_firewall_status = {"available": True, "patched": False}
        return types.SimpleNamespace(changed_files=changed)

    async def ensure_installer_dependencies(_hass: Any) -> None:
        return None

    async def wait_for_agent(_api: Any) -> dict[str, Any]:
        result = waits.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def migrate_mqtt(_api: Any) -> None:
        return None

    async def apply_setup(_hass: Any, setup_entry: Any, _setup: dict[str, Any]) -> None:
        setup_entry.runtime_data.agent_update_state = types.SimpleNamespace(
            update_required=False
        )

    monkeypatch.setattr(repairs, "async_install_device_agent", install_agent)
    monkeypatch.setattr(
        repairs, "async_ensure_installer_dependencies", ensure_installer_dependencies
    )
    monkeypatch.setattr(repairs, "_async_wait_for_agent_after_update", wait_for_agent)
    monkeypatch.setattr(repairs, "async_migrate_legacy_mqtt_if_available", migrate_mqtt)
    monkeypatch.setattr(repairs, "_async_apply_repaired_agent_setup", apply_setup)
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]
    credentials = {"bootstrap_ssh_username": "root", "bootstrap_ssh_password": "secret"}

    first = asyncio.run(flow.async_step_ssh_install(credentials))
    assert first["errors"] == {"base": "ssh_install_failed"}
    assert "apply_firewall" not in api.calls

    second = asyncio.run(flow.async_step_ssh_install(credentials))
    assert second == {"type": "create_entry", "data": {}}
    assert "apply_firewall" in api.calls
    assert "apply_ipv6_firewall" in api.calls

    # A later install in the same flow starts without the old follow-up.
    assert flow._ssh_install_followup is None


def test_ssh_install_retry_after_a_failed_installer_runs_every_follow_up_step(
    monkeypatch,
) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    api = FakePatchApi()
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(api),
        data={"agent_host": "192.0.2.60", "agent_token": "agent-token"},
    )
    entry.runtime_data.agent_update_state = FakeAgentUpdateState()
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    attempts: list[int] = []

    async def install_agent(*_args: Any, **_kwargs: Any) -> Any:
        attempts.append(1)
        if len(attempts) == 1:
            # The files are on the device, then the restart check fails.
            raise RuntimeError("startup verification failed")
        return types.SimpleNamespace(changed_files=())

    async def nothing(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def wait_for_agent(_api: Any) -> dict[str, Any]:
        return {"version": "1.1.0", "capabilities": {}}

    async def apply_setup(_hass: Any, setup_entry: Any, _setup: dict[str, Any]) -> None:
        setup_entry.runtime_data.agent_update_state = types.SimpleNamespace(
            update_required=False
        )

    monkeypatch.setattr(repairs, "async_install_device_agent", install_agent)
    monkeypatch.setattr(repairs, "async_ensure_installer_dependencies", nothing)
    monkeypatch.setattr(repairs, "_async_wait_for_agent_after_update", wait_for_agent)
    monkeypatch.setattr(repairs, "async_migrate_legacy_mqtt_if_available", nothing)
    monkeypatch.setattr(repairs, "_async_apply_repaired_agent_setup", apply_setup)
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]
    credentials = {"bootstrap_ssh_username": "root", "bootstrap_ssh_password": "secret"}

    first = asyncio.run(flow.async_step_ssh_install(credentials))
    assert first["errors"] == {"base": "ssh_install_failed"}

    second = asyncio.run(flow.async_step_ssh_install(credentials))
    assert second == {"type": "create_entry", "data": {}}
    assert "apply_firewall" in api.calls
    assert "apply_ipv6_firewall" in api.calls
    assert flow._ssh_install_followup is None


def test_agent_update_repair_ssh_install_reports_failures(monkeypatch, caplog) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    entry = FakeEntry(
        runtime_data=FakeRuntimeData(FakePatchApi()),
        data={
            "agent_host": "192.0.2.60",
            "agent_token": "agent-token",
            "maintenance_token": "maintenance-token",
        },
    )
    entry.runtime_data.agent_update_state = FakeAgentUpdateState()
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]

    async def install_agent(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("ssh failed")

    async def ensure_installer_dependencies(_hass: Any) -> None:
        return None

    monkeypatch.setattr(repairs, "async_install_device_agent", install_agent)
    monkeypatch.setattr(
        repairs,
        "async_ensure_installer_dependencies",
        ensure_installer_dependencies,
    )
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(
        flow.async_step_ssh_install(
            {
                "bootstrap_ssh_username": "root",
                "bootstrap_ssh_password": "secret",
            }
        )
    )

    assert result["type"] == "form"
    assert result["step_id"] == "ssh_install"
    assert result["errors"] == {"base": "ssh_install_failed"}
    assert any(
        "SSH install failed" in record.getMessage() and "ssh failed" in record.getMessage()
        for record in caplog.records
    )
    # The password the user typed is never part of the log.
    assert not any("secret" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("method", ["async_qml_patch_status", "async_firewall_status", "async_ipv6_firewall_status"])
def test_update_patch_capture_retries_busy_preserving_active_state(monkeypatch, method) -> None:
    from unittest.mock import AsyncMock

    from custom_components.bticino_c300x import agent_update
    from custom_components.bticino_c300x.api_errors import C300XAgentApiConnectionError

    api = FakePatchApi()
    busy = C300XAgentApiConnectionError("device agent returned HTTP 409: maintenance_busy")
    read = AsyncMock(side_effect=[busy, {"patched": True, "state": "patched"}])
    monkeypatch.setattr(api, method, read)
    monkeypatch.setattr(agent_update.asyncio, "sleep", AsyncMock())
    entry = FakeEntry(runtime_data=FakeRuntimeData(api), options={CONF_DEVICE_UI_ENABLED: False})
    entry.runtime_data.qml_patch_status = {"patched": False}

    state = asyncio.run(_async_capture_external_patch_state(entry, require_reliable=True))

    assert read.await_count == 2
    assert state.qml_patch_required is True
    assert state.firewall_patched is True
    assert state.firewall_status_known is True
    assert state.ipv6_firewall_patched is True
    assert entry.runtime_data.qml_patch_status["patched"] is True


@pytest.mark.parametrize("failure", ["busy", "transport"])
@pytest.mark.parametrize("method", ["async_qml_patch_status", "async_firewall_status", "async_ipv6_firewall_status"])
def test_update_does_not_prepare_without_reliable_patch_capture(monkeypatch, failure, method) -> None:
    from unittest.mock import AsyncMock

    from custom_components.bticino_c300x import agent_update, repairs
    from custom_components.bticino_c300x.api_errors import C300XAgentApiConnectionError

    clock = [0.0]

    async def sleep(delay):
        clock[0] += delay

    monkeypatch.setattr(agent_update, "monotonic", lambda: clock[0])
    monkeypatch.setattr(agent_update.asyncio, "sleep", sleep)
    api = FakePatchApi()
    read = AsyncMock(side_effect=C300XAgentApiConnectionError(
        "device agent returned HTTP 409: maintenance_busy" if failure == "busy"
        else "device-agent request timed out"
    ))
    monkeypatch.setattr(api, method, read)
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))
    entry.runtime_data.agent_update_state = FakeSelfUpdateState()
    update = AsyncMock()
    monkeypatch.setattr(repairs, "async_apply_packaged_agent_update", update)
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")
    flow.async_show_form = lambda **kwargs: kwargs

    result = asyncio.run(flow.async_step_confirm({}))

    assert result["errors"] == {"base": "update_failed"}
    update.assert_not_awaited()
    # One-second pauses for the whole busy wait, then a last try.
    wait = agent_update.MAINTENANCE_BUSY_WAIT_SECONDS
    assert read.await_count == (int(wait) + 1 if failure == "busy" else 1)
    assert clock[0] == (wait if failure == "busy" else 0)


@pytest.mark.parametrize("optional", ["unsupported", "unavailable", "core_only"])
@pytest.mark.parametrize("method", ["async_qml_patch_status", "async_firewall_status", "async_ipv6_firewall_status"])
def test_update_optional_patch_status_does_not_block_prepare(monkeypatch, optional, method) -> None:
    from unittest.mock import AsyncMock

    from custom_components.bticino_c300x import repairs
    from custom_components.bticino_c300x._api_normalize import (
        normalize_firewall_status,
        normalize_qml_patch_status,
    )
    from custom_components.bticino_c300x.api_errors import C300XAgentApiUnsupportedError

    api = FakePatchApi()
    raw = {"available": False} if optional == "unavailable" else {"core_patched": True}
    normalize = normalize_qml_patch_status if method == "async_qml_patch_status" else normalize_firewall_status
    status = normalize(raw)
    assert status["patched"] is None
    read = AsyncMock(return_value=status)
    if optional == "unsupported":
        read.side_effect = C300XAgentApiUnsupportedError("device agent returned HTTP 404")
    monkeypatch.setattr(api, method, read)
    entry = FakeEntry(runtime_data=FakeRuntimeData(api), options={CONF_DEVICE_UI_ENABLED: False})
    entry.runtime_data.qml_patch_status = {"patched": True}
    entry.runtime_data.agent_update_state = FakeSelfUpdateState()

    state = asyncio.run(_async_capture_external_patch_state(entry, require_reliable=True))
    if method == "async_qml_patch_status":
        assert state.qml_patch_required is (optional == "unsupported")
    else:
        assert state.qml_patch_required is True
    if method == "async_firewall_status":
        assert state.firewall_status_known is False
    # Stop at the update boundary: optional status must not prevent reaching prepare.
    update = AsyncMock(side_effect=RuntimeError("test stops before device update"))
    monkeypatch.setattr(repairs, "async_apply_packaged_agent_update", update)
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")
    flow.async_show_form = lambda **kwargs: kwargs
    asyncio.run(flow.async_step_confirm({}))
    update.assert_awaited_once()


def test_capture_external_patch_state_tolerates_agent_status_errors() -> None:
    class ErrorStatusApi(FakePatchApi):
        async def async_qml_patch_status(self) -> dict[str, Any]:
            self.calls.append("qml_status_error")
            raise C300XAgentApiError("qml unavailable")

        async def async_firewall_status(self) -> dict[str, Any]:
            self.calls.append("firewall_status_error")
            raise C300XAgentApiError("firewall unavailable")

        async def async_ipv6_firewall_status(self) -> dict[str, Any]:
            self.calls.append("ipv6_firewall_status_error")
            raise C300XAgentApiError("ipv6 unavailable")

    entry = FakeEntry(
        runtime_data=FakeRuntimeData(ErrorStatusApi()),
        options={CONF_DEVICE_UI_ENABLED: True},
    )

    patch_state = asyncio.run(_async_capture_external_patch_state(entry))

    assert patch_state.qml_patch_required is True
    assert patch_state.firewall_patched is False
    assert patch_state.firewall_status_known is False
    assert patch_state.ipv6_firewall_patched is False


def test_frontend_card_repair_flow_init_ignores_internal_flow_data(monkeypatch) -> None:
    """Starting the Lovelace card repair must not submit the confirm form."""

    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    flow = FrontendCardSetupRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_flows_frontend._dashboard_selector",
        lambda _hass: str,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_flows_frontend._text_selector",
        lambda: str,
    )

    def show_form(**kwargs: Any) -> dict[str, Any]:
        return {"type": "form", **kwargs}

    def show_menu(**kwargs: Any) -> dict[str, Any]:
        return {"type": "menu", **kwargs}

    flow.async_show_form = show_form  # type: ignore[method-assign]
    flow.async_show_menu = show_menu  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_init({"issue_id": "from-flow-manager"}))

    assert result["type"] == "menu"
    assert result["step_id"] == "init"
    assert tuple(result["menu_options"]) == ("confirm", "ignore")
    assert result["description_placeholders"] == {
        "dashboard_path": "/lovelace/c300x",
        "entry_title": "entry-1",
    }


def test_frontend_card_repair_confirm_shows_form(monkeypatch) -> None:
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    flow = FrontendCardSetupRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_flows_frontend._dashboard_selector",
        lambda _hass: str,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_flows_frontend._text_selector",
        lambda: str,
    )
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm())

    assert result["type"] == "form"
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {
        "dashboard_path": "/lovelace/c300x",
        "entry_title": "entry-1",
    }


def test_frontend_card_repair_confirm_reports_invalid_target(monkeypatch) -> None:
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    flow = FrontendCardSetupRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_flows_frontend._dashboard_selector",
        lambda _hass: str,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_flows_frontend._text_selector",
        lambda: str,
    )
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(
        flow.async_step_confirm(
            {
                _LOVELACE_DASHBOARD_FIELD: "dashboard-test",
                _LOVELACE_VIEW_FIELD: "door/camera",
            }
        )
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": "lovelace_config_invalid"}


def test_frontend_card_repair_steps_abort_when_entry_missing() -> None:
    flow = FrontendCardSetupRepairFlow(FakeHass(None), "missing")  # type: ignore[arg-type]
    flow.async_abort = lambda **kwargs: {"type": "abort", **kwargs}  # type: ignore[method-assign]

    assert asyncio.run(flow.async_step_init()) == {
        "type": "abort",
        "reason": "entry_not_loaded",
    }
    assert asyncio.run(flow.async_step_confirm({})) == {
        "type": "abort",
        "reason": "entry_not_loaded",
    }
    assert asyncio.run(flow.async_step_ignore()) == {
        "type": "abort",
        "reason": "entry_not_loaded",
    }


def test_frontend_card_repair_confirm_reports_lovelace_setup_errors(
    monkeypatch,
) -> None:
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    flow = FrontendCardSetupRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_flows_frontend._dashboard_selector",
        lambda _hass: str,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_flows_frontend._text_selector",
        lambda: str,
    )

    async def fail_setup(*_args: Any, **_kwargs: Any) -> str:
        raise _LovelaceCardSetupError("lovelace_storage_unavailable")

    async def setup_frontend(_hass: Any) -> None:
        return None

    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_flows_frontend._async_setup_lovelace_cards",
        fail_setup,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_flows_frontend.async_setup_frontend",
        setup_frontend,
    )
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(
        flow.async_step_confirm(
            {
                _LOVELACE_DASHBOARD_FIELD: "/dashboard-test/door",
                _LOVELACE_VIEW_FIELD: "door",
            }
        )
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": "lovelace_storage_unavailable"}
    assert result["data_schema"] is not None


def test_frontend_card_repair_can_be_ignored() -> None:
    """Ignoring the Lovelace card repair persists the dismissal."""

    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    flow = FrontendCardSetupRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]

    def create_entry(**kwargs: Any) -> dict[str, Any]:
        return {"type": "create_entry", **kwargs}

    flow.async_create_entry = create_entry  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_ignore())

    assert result == {"type": "create_entry", "data": {"ignored": True}}
    assert entry.data[CONF_FRONTEND_CARD_SETUP_DISMISSED] is True
    assert (
        entry.data[CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION]
        == FRONTEND_CARD_SETUP_REPAIR_VERSION
    )
    assert IGNORED_ISSUES == [
        (DOMAIN, "frontend_card_setup_hint_entry-1", True),
    ]


def test_frontend_card_helpers_reject_invalid_lovelace_cards_container() -> None:
    with pytest.raises(_LovelaceCardSetupError) as err:
        _cards_for_view({"sections": [{"cards": "not-a-list"}], "cards": "bad"})

    assert err.value.error_key == "lovelace_config_invalid"


def test_frontend_card_helpers_cover_lovelace_view_shapes() -> None:
    keep = {"type": "sections", "path": "c300x", "sections": []}
    placeholder = {
        "sections": [
            {"cards": [{"type": "heading", "heading": "New section"}]},
        ],
    }
    invalid_placeholder = {"sections": [{"cards": [{"type": "button"}]}]}
    views: list[Any] = [
        {"ignored": True},
        placeholder,
        invalid_placeholder,
        keep,
    ]

    assert _c300x_view([{"title": "C300X"}], "c300x") == {"title": "C300X"}
    assert _empty_placeholder_view(views) is placeholder
    assert _remove_empty_placeholder_views(views, keep=keep) is True
    assert placeholder not in views
    assert invalid_placeholder in views
    assert _cards_for_view({"cards": []}) == []


def test_frontend_card_helpers_normalize_dashboard_targets(monkeypatch) -> None:
    lovelace_const = types.ModuleType("homeassistant.components.lovelace.const")
    lovelace_const.LOVELACE_DATA = "lovelace"
    lovelace_const.MODE_STORAGE = "storage"

    default_dashboard = types.SimpleNamespace(
        mode="storage",
        config={"title": "Default dashboard"},
    )
    selected_dashboard = types.SimpleNamespace(
        mode="storage",
        config={"title": "Wall tablet"},
    )
    yaml_dashboard = types.SimpleNamespace(
        mode="yaml",
        config={"title": "YAML"},
    )
    hass = FakeHass(FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi())))
    hass.data["lovelace"] = types.SimpleNamespace(
        dashboards={
            None: default_dashboard,
            "wall": selected_dashboard,
            "yaml": yaml_dashboard,
        }
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.lovelace.const",
        lovelace_const,
    )

    assert _dashboard_select_options(hass) == [
        {"value": "__default__", "label": "Default dashboard (/lovelace)"},
        {"value": "wall", "label": "Wall tablet (/wall)"},
    ]
    assert _dashboard_selector_value(None) == "__default__"
    assert _dashboard_selector_value("wall") == "wall"
    assert _lovelace_dashboard_path(None) == "/lovelace/c300x"
    assert _lovelace_dashboard_path("wall", "door") == "/wall/door"
    assert _normalize_lovelace_target("__default__", "/wall/door") == (
        "wall",
        "door",
    )
    assert _normalize_lovelace_target("wall", "/lovelace/door") == (
        None,
        "door",
    )
    assert (
        _submitted_dashboard_path({_LOVELACE_DASHBOARD_FIELD: "/wall/"})
        == "wall"
    )
    assert _submitted_dashboard_path({_LOVELACE_DASHBOARD_FIELD: "__default__"}) is None
    assert _submitted_view_path({_LOVELACE_VIEW_FIELD: ""}) == "c300x"
    assert _submitted_view_path({_LOVELACE_VIEW_FIELD: "/door/"}) == "door"


def test_frontend_card_repair_initializes_missing_lovelace_config(monkeypatch) -> None:
    lovelace_package = types.ModuleType("homeassistant.components.lovelace")
    lovelace_const = types.ModuleType("homeassistant.components.lovelace.const")
    lovelace_const.LOVELACE_DATA = "lovelace"
    lovelace_const.MODE_STORAGE = "storage"
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")

    class FakeEntityRegistry:
        def async_get_entity_id(
            self,
            domain: str,
            platform: str,
            unique_id: str,
        ) -> str | None:
            assert platform == "bticino_c300x"
            if domain == "camera" and unique_id == "entry-1_doorbell_camera":
                return "camera.bticino_c300x_doorbell_camera"
            return None

    class FailingLoadDashboard:
        mode = "storage"

        def __init__(self) -> None:
            self.saved: dict[str, Any] | None = None

        async def async_load(self, _force: bool) -> dict[str, Any]:
            raise ConfigNotFound

        async def async_save(self, config: dict[str, Any]) -> None:
            self.saved = config

    dashboard = FailingLoadDashboard()
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    hass = FakeHass(entry)
    hass.entity_registry = FakeEntityRegistry()
    hass.data["lovelace"] = types.SimpleNamespace(dashboards={None: dashboard})
    monkeypatch.setitem(sys.modules, "homeassistant.components.lovelace", lovelace_package)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.lovelace.const",
        lovelace_const,
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry,
    )
    monkeypatch.setattr(
        sys.modules["homeassistant.helpers"],
        "entity_registry",
        entity_registry,
        raising=False,
    )
    entity_registry.async_get = lambda _hass: hass.entity_registry

    path = asyncio.run(_async_setup_lovelace_cards(hass, entry))  # type: ignore[arg-type]

    assert path == "/lovelace/c300x"
    assert dashboard.saved is not None
    assert dashboard.saved["views"][0]["sections"][0]["cards"][0]["mode"] == "auto"


def test_frontend_card_repair_rejects_invalid_lovelace_configs(monkeypatch) -> None:
    lovelace_package = types.ModuleType("homeassistant.components.lovelace")
    lovelace_const = types.ModuleType("homeassistant.components.lovelace.const")
    lovelace_const.LOVELACE_DATA = "lovelace"
    lovelace_const.MODE_STORAGE = "storage"
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")

    class FakeEntityRegistry:
        def async_get_entity_id(
            self,
            domain: str,
            platform: str,
            unique_id: str,
        ) -> str | None:
            assert platform == "bticino_c300x"
            if domain == "camera" and unique_id == "entry-1_doorbell_camera":
                return "camera.bticino_c300x_doorbell_camera"
            return None

    class FakeLovelaceDashboard:
        mode = "storage"

        def __init__(self, config: Any) -> None:
            self.config = config

        async def async_load(self, _force: bool) -> Any:
            return self.config

        async def async_save(self, _config: dict[str, Any]) -> None:
            raise AssertionError("invalid config must not be saved")

    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    hass = FakeHass(entry)
    hass.entity_registry = FakeEntityRegistry()
    monkeypatch.setitem(sys.modules, "homeassistant.components.lovelace", lovelace_package)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.lovelace.const",
        lovelace_const,
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry,
    )
    monkeypatch.setattr(
        sys.modules["homeassistant.helpers"],
        "entity_registry",
        entity_registry,
        raising=False,
    )
    entity_registry.async_get = lambda _hass: hass.entity_registry

    for config in ("bad", {"views": "bad"}):
        hass.data["lovelace"] = types.SimpleNamespace(
            dashboards={None: FakeLovelaceDashboard(config)}
        )
        with pytest.raises(_LovelaceCardSetupError) as err:
            asyncio.run(_async_setup_lovelace_cards(hass, entry))  # type: ignore[arg-type]
        assert err.value.error_key == "lovelace_config_invalid"


def test_frontend_card_repair_reports_missing_camera_entity(monkeypatch) -> None:
    lovelace_const = types.ModuleType("homeassistant.components.lovelace.const")
    lovelace_const.LOVELACE_DATA = "lovelace"
    lovelace_const.MODE_STORAGE = "storage"
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")

    class FakeEntityRegistry:
        def async_get_entity_id(
            self,
            _domain: str,
            _platform: str,
            _unique_id: str,
        ) -> None:
            return None

    class FakeLovelaceDashboard:
        mode = "storage"

        async def async_load(self, _force: bool) -> dict[str, Any]:
            return {"views": []}

        async def async_save(self, _config: dict[str, Any]) -> None:
            raise AssertionError("dashboard must not be saved without a camera entity")

    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    hass = FakeHass(entry)
    hass.entity_registry = FakeEntityRegistry()
    hass.data["lovelace"] = types.SimpleNamespace(
        dashboards={None: FakeLovelaceDashboard()}
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.lovelace.const",
        lovelace_const,
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry,
    )
    monkeypatch.setattr(
        sys.modules["homeassistant.helpers"],
        "entity_registry",
        entity_registry,
        raising=False,
    )
    entity_registry.async_get = lambda _hass: hass.entity_registry

    with pytest.raises(_LovelaceCardSetupError) as err:
        asyncio.run(_async_setup_lovelace_cards(hass, entry))  # type: ignore[arg-type]

    assert err.value.error_key == "camera_entity_missing"


def test_callback_url_repair_flow_stores_valid_override_and_reloads(monkeypatch) -> None:
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    entry.data = {"agent_host": "192.0.2.60", "agent_port": 8091}
    hass = FakeHass(entry)
    flow = CallbackUrlRepairFlow(hass, "entry-1")  # type: ignore[arg-type]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.callback_url._select_non_link_local_source_ip",
        lambda *_args: "192.0.2.10",
    )

    def show_form(**kwargs: Any) -> dict[str, Any]:
        return {"type": "form", **kwargs}

    def create_entry(**kwargs: Any) -> dict[str, Any]:
        return {"type": "create_entry", **kwargs}

    flow.async_show_form = show_form  # type: ignore[method-assign]
    flow.async_create_entry = create_entry  # type: ignore[method-assign]

    invalid = asyncio.run(
        flow.async_step_configure({CONF_CALLBACK_BASE_URL: "https://ha.local:8123"})
    )
    assert invalid["type"] == "form"
    assert invalid["errors"] == {
        CONF_CALLBACK_BASE_URL: "invalid_callback_base_url",
    }

    result = asyncio.run(
        flow.async_step_configure({CONF_CALLBACK_BASE_URL: "http://192.0.2.10:8123"})
    )

    assert result["type"] == "create_entry"
    assert entry.options[CONF_CALLBACK_BASE_URL] == "http://192.0.2.10:8123"
    assert hass.config_entries.reloads == ["entry-1"]


def test_callback_url_repair_flow_aborts_when_entry_missing() -> None:
    flow = CallbackUrlRepairFlow(FakeHass(None), "entry-1")  # type: ignore[arg-type]
    flow.async_abort = lambda **kwargs: {"type": "abort", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_configure({}))

    assert result == {"type": "abort", "reason": "entry_not_loaded"}


def test_callback_url_helper_reports_validation_errors() -> None:
    errors: dict[str, str] = {}

    assert _validated_callback_base_url({CONF_CALLBACK_BASE_URL: "ftp://bad"}, errors) == ""
    assert errors == {CONF_CALLBACK_BASE_URL: "invalid_callback_base_url"}


def test_core_qml_hook_repair_flow_applies_only_core_patch() -> None:
    api = FakePatchApi()
    api.qml_status = {
        "available": True,
        "patched": False,
        "state": "original",
        "core_patched": True,
        "core_state": "patched",
    }
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            api,
            capabilities={
                "maintenance": {
                    "supported": True,
                    "qml_core_patch": True,
                }
            },
            qml_patch_status={
                "available": True,
                "patched": False,
                "state": "original",
                "core_patched": False,
                "core_state": "original",
            },
        )
    )
    flow = DeviceCoreQmlHookRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]

    def show_form(**kwargs: Any) -> dict[str, Any]:
        return {"type": "form", **kwargs}

    def create_entry(**kwargs: Any) -> dict[str, Any]:
        return {"type": "create_entry", **kwargs}

    flow.async_show_form = show_form  # type: ignore[method-assign]
    flow.async_create_entry = create_entry  # type: ignore[method-assign]

    form = asyncio.run(flow.async_step_init())
    result = asyncio.run(flow.async_step_confirm({}))

    assert form["type"] == "form"
    assert result["type"] == "create_entry"
    assert api.calls == ["apply_qml_core", "qml_status"]
    assert entry.runtime_data.qml_patch_status["core_state"] == "patched"


def test_core_qml_hook_repair_flow_aborts_when_unsupported_or_missing() -> None:
    missing_flow = DeviceCoreQmlHookRepairFlow(FakeHass(None), "entry-1")  # type: ignore[arg-type]
    missing_flow.async_abort = lambda **kwargs: {"type": "abort", **kwargs}  # type: ignore[method-assign]

    missing = asyncio.run(missing_flow.async_step_confirm({}))

    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    unsupported_flow = DeviceCoreQmlHookRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    unsupported_flow.async_abort = lambda **kwargs: {"type": "abort", **kwargs}  # type: ignore[method-assign]

    unsupported = asyncio.run(unsupported_flow.async_step_confirm({}))

    assert missing == {"type": "abort", "reason": "entry_not_loaded"}
    assert unsupported == {"type": "abort", "reason": "core_patch_unsupported"}


def test_device_user_repair_flow_creates_user_and_clears_issue() -> None:
    api = FakePatchApi()
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))
    hass = FakeHass(entry)
    hass.config.location_name = "HA Test"
    flow = DeviceUserRepairFlow(hass, "entry-1")  # type: ignore[arg-type]

    def show_form(**kwargs: Any) -> dict[str, Any]:
        return {"type": "form", **kwargs}

    def create_entry(**kwargs: Any) -> dict[str, Any]:
        return {"type": "create_entry", **kwargs}

    flow.async_show_form = show_form  # type: ignore[method-assign]
    flow.async_create_entry = create_entry  # type: ignore[method-assign]

    form = asyncio.run(flow.async_step_confirm())
    result = asyncio.run(flow.async_step_confirm({}))

    assert form == {"type": "form", "step_id": "confirm"}
    assert result == {"type": "create_entry", "data": {}}
    assert api.calls == ["ensure_homeassistant_user:Home Assistant HA Test"]
    assert entry.runtime_data.device_user_status == api.device_user_status


def test_device_user_repair_flow_aborts_when_entry_missing() -> None:
    flow = DeviceUserRepairFlow(FakeHass(None), "entry-1")  # type: ignore[arg-type]
    flow.async_abort = lambda **kwargs: {"type": "abort", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result == {"type": "abort", "reason": "entry_not_loaded"}


def test_media_setup_repair_runs_confirmed_fixable_actions() -> None:
    """Media setup repair applies only confirmed fixable media prerequisites."""

    api = FakePatchApi()
    runtime_data = FakeRuntimeData(
        api,
        capabilities={
            "doorbell_video": {"supported": True},
            "doorbell_call": {"supported": True},
        },
        self_test_status={
            "ok": False,
            "checks": {
                "capabilities": {"ok": True},
                "firewall": {"ok": False, "reason": "ipv4_media_ports_missing"},
                "rtsp": {"ok": True},
                "talkback_rtp": {"ok": True},
                "homeassistant_user": {"ok": False},
                "device_routing": {"ok": False},
                "startup": {"ok": True},
            },
        },
    )
    runtime_data.event_state.smartphone_forwarding_mode = "enabled"
    entry = FakeEntry(runtime_data=runtime_data, options={"video_enabled": True})
    flow = MediaSetupRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]

    def show_form(**kwargs: Any) -> dict[str, Any]:
        return {"type": "form", **kwargs}

    def create_entry(**kwargs: Any) -> dict[str, Any]:
        return {"type": "create_entry", **kwargs}

    flow.async_show_form = show_form  # type: ignore[method-assign]
    flow.async_create_entry = create_entry  # type: ignore[method-assign]

    init_result = asyncio.run(flow.async_step_init({"issue_id": "from-flow-manager"}))
    assert init_result["type"] == "form"
    assert api.calls == []

    result = asyncio.run(flow.async_step_confirm({}))

    assert result == {
        "type": "create_entry",
        "data": {"repaired": ["firewall", "homeassistant_user"]},
    }
    assert api.calls == [
        "set_firewall_enabled:True",
        "apply_firewall",
        "ensure_homeassistant_user:Home Assistant HA Test",
        "self_test",
        "device_user_status",
    ]
    assert entry.runtime_data.device_user_status == api.device_user_status
    assert entry.runtime_data.self_test_status == api.self_test_status
    assert entry.runtime_data.event_state.smartphone_forwarding_mode == "enabled"


def test_media_setup_repair_keeps_the_issue_when_the_check_still_fails(
    monkeypatch,
) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    checks = {
        "capabilities": {"ok": True},
        "firewall": {"ok": False, "reason": "ipv4_media_ports_missing"},
        "rtsp": {"ok": True},
        "talkback_rtp": {"ok": True},
        "homeassistant_user": {"ok": True},
        "device_routing": {"ok": True},
        "startup": {"ok": True},
    }
    api = FakePatchApi()
    # The firewall action answers without an error, but the device still
    # fails the check afterwards.
    api.self_test_status = {"ok": False, "checks": dict(checks)}
    runtime_data = FakeRuntimeData(
        api,
        capabilities={
            "doorbell_video": {"supported": True},
            "doorbell_call": {"supported": True},
        },
        self_test_status={"ok": False, "checks": dict(checks)},
    )
    entry = FakeEntry(runtime_data=runtime_data, options={"video_enabled": True})
    flow = MediaSetupRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    deleted: list[str] = []
    monkeypatch.setattr(
        repairs.ir, "async_delete_issue", lambda **kwargs: deleted.append(kwargs["issue_id"])
    )
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert "apply_firewall" in api.calls
    assert result["type"] == "form"
    assert result["errors"] == {"base": "media_setup_repair_failed"}
    assert "firewall" in result["description_placeholders"]["failed_checks"]
    assert deleted == []

    # Once the device passes the check, the same flow closes the issue.
    api.self_test_status = {"ok": True, "checks": {**checks, "firewall": {"ok": True}}}
    result = asyncio.run(flow.async_step_confirm({}))
    assert result["type"] == "create_entry"
    assert len(deleted) == 1


def test_media_setup_repair_does_not_change_forwarding() -> None:
    api = FakePatchApi()
    runtime_data = FakeRuntimeData(
        api,
        capabilities={
            "doorbell_call": {"supported": True},
            "smartphone_forwarding": {"supported": True},
        },
        self_test_status={
            "ok": True,
            "checks": {
                "capabilities": {"ok": True},
                "firewall": {"ok": True},
                "rtsp": {"ok": True},
                "talkback_rtp": {"ok": True},
                "homeassistant_user": {"ok": True},
                "device_routing": {"ok": True},
                "startup": {"ok": True},
            },
        },
    )
    runtime_data.event_state.smartphone_forwarding_mode = "enabled"
    entry = FakeEntry(runtime_data=runtime_data, options={"video_enabled": True})
    flow = MediaSetupRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]

    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result == {
        "type": "create_entry",
        "data": {"repaired": []},
    }
    assert api.calls == []
    assert entry.runtime_data.event_state.smartphone_forwarding_mode == "enabled"


def test_media_setup_repair_noops_when_media_is_ready() -> None:
    api = FakePatchApi()
    runtime_data = FakeRuntimeData(
        api,
        capabilities={
            "doorbell_video": {"supported": True},
            "doorbell_call": {"supported": True},
            "home_call": {"supported": True},
        },
        device_user_status={
            "homeassistant_user_present": True,
            "device_routing_applied": True,
            "media_user_label_applied": True,
        },
        self_test_status={
            "ok": True,
            "checks": {
                "capabilities": {"ok": True},
                "firewall": {"ok": True},
                "rtsp": {"ok": True},
                "talkback_rtp": {"ok": True},
                "homeassistant_user": {"ok": True},
                "device_routing": {"ok": True},
                "startup": {"ok": True},
            },
        },
    )
    entry = FakeEntry(runtime_data=runtime_data, options={"video_enabled": True})
    flow = MediaSetupRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result == {"type": "create_entry", "data": {"repaired": []}}
    assert api.calls == []


def test_media_setup_repair_aborts_when_entry_missing() -> None:
    flow = MediaSetupRepairFlow(FakeHass(None), "entry-1")  # type: ignore[arg-type]
    flow.async_abort = lambda **kwargs: {"type": "abort", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result == {"type": "abort", "reason": "entry_not_loaded"}


def test_media_setup_repair_placeholders_handle_empty_details() -> None:
    assert _media_setup_repair_placeholders({}) == {
        "failed_checks": "unknown",
        "warnings": "none",
        "recommended_action": "unknown",
    }


def test_media_setup_repair_unreachable_agent_only_reloads_entry() -> None:
    api = FakePatchApi()
    runtime_data = FakeRuntimeData(api)
    runtime_data.connection_state.available = False
    entry = FakeEntry(runtime_data=runtime_data, options={"video_enabled": True})
    hass = FakeHass(entry)

    repaired = asyncio.run(_async_repair_media_setup(hass, entry))  # type: ignore[arg-type]

    assert repaired == ["agent_reachable_check"]
    assert hass.config_entries.reloads == ["entry-1"]
    assert api.calls == []


def test_callback_url_repair_aborts_when_entry_is_unloaded() -> None:
    flow = CallbackUrlRepairFlow(FakeHass(None), "entry-1")  # type: ignore[arg-type]
    flow.async_abort = lambda **kwargs: {"type": "abort", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_configure({}))

    assert result == {"type": "abort", "reason": "entry_not_loaded"}


def test_core_qml_hook_repair_aborts_when_unsupported() -> None:
    runtime_data = FakeRuntimeData(FakePatchApi())
    runtime_data.capabilities = {"maintenance": {"supported": True}}
    entry = FakeEntry(runtime_data=runtime_data)
    flow = DeviceCoreQmlHookRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    flow.async_abort = lambda **kwargs: {"type": "abort", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result == {"type": "abort", "reason": "core_patch_unsupported"}


def test_core_qml_hook_repair_reports_agent_failure(monkeypatch) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    runtime_data = FakeRuntimeData(FakePatchApi())
    runtime_data.capabilities = {
        "maintenance": {"supported": True, "qml_core_patch": True}
    }
    runtime_data.qml_patch_status = {"core_state": "original"}
    entry = FakeEntry(runtime_data=runtime_data)
    flow = DeviceCoreQmlHookRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]

    async def apply_core_patch(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise C300XAgentApiError("patch failed")

    monkeypatch.setattr(
        repairs,
        "async_apply_qml_core_patch_and_confirm",
        apply_core_patch,
    )
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result["type"] == "form"
    assert result["step_id"] == "confirm"
    assert result["errors"] == {"base": "core_patch_failed"}
    assert result["description_placeholders"] == {"qml_patch_status": "original", "entry_title": "entry-1"}


def test_core_qml_hook_repair_reports_verify_failure(monkeypatch) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    runtime_data = FakeRuntimeData(FakePatchApi())
    runtime_data.capabilities = {
        "maintenance": {"supported": True, "qml_core_patch": True}
    }
    runtime_data.qml_patch_status = {"state": "patched"}
    entry = FakeEntry(runtime_data=runtime_data)
    flow = DeviceCoreQmlHookRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]

    async def apply_core_patch(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"core_patched": False, "core_state": "original"}

    monkeypatch.setattr(
        repairs,
        "async_apply_qml_core_patch_and_confirm",
        apply_core_patch,
    )
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result["type"] == "form"
    assert result["step_id"] == "confirm"
    assert result["errors"] == {"base": "core_patch_verify_failed"}
    assert result["description_placeholders"] == {"qml_patch_status": "patched", "entry_title": "entry-1"}


def test_owed_display_steps_repair_fills_every_placeholder_of_its_text() -> None:
    """The issue has no description of its own: the confirm step names the entry."""

    strings = json.loads(
        (Path(__file__).resolve().parents[1] / "custom_components/bticino_c300x/strings.json").read_text()
    )
    text = strings["issues"]["device_display_followup_pending"]["fix_flow"]["step"]["confirm"]["description"]
    runtime_data = FakeRuntimeData(FakePatchApi())
    runtime_data.capabilities = {"maintenance": {"supported": True, "qml_core_patch": True}}
    entry = FakeEntry(runtime_data=runtime_data, data={CONF_DISPLAY_FOLLOWUP_PENDING: True})
    flow = DeviceCoreQmlHookRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm(None))

    assert result["step_id"] == "confirm"
    assert set(re.findall(r"\{(\w+)\}", text)) == {"entry_title"}
    assert result["description_placeholders"]["entry_title"] == "entry-1"


def test_core_qml_hook_repair_success_finishes_repair(monkeypatch) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    runtime_data = FakeRuntimeData(FakePatchApi())
    runtime_data.capabilities = {
        "maintenance": {"supported": True, "qml_core_patch": True}
    }
    entry = FakeEntry(runtime_data=runtime_data)
    hass = FakeHass(entry)
    flow = DeviceCoreQmlHookRepairFlow(hass, "entry-1")  # type: ignore[arg-type]
    dispatched: list[tuple[Any, ...]] = []

    async def apply_core_patch(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"core_patched": True, "core_state": "patched"}

    monkeypatch.setattr(
        repairs,
        "async_apply_qml_core_patch_and_confirm",
        apply_core_patch,
    )
    monkeypatch.setattr(
        repairs,
        "async_dispatcher_send",
        lambda *args: dispatched.append(args),
    )
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result == {"type": "create_entry", "data": {}}
    assert hass.config_entries.reloads == []
    assert dispatched == []


def test_media_setup_repair_capability_failure_refreshes_agent_setup(
    monkeypatch,
) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    api = FakePatchApi()
    calls: list[str] = []

    async def validate_setup() -> dict[str, Any]:
        api.calls.append("validate_setup")
        return {
            "version": "0.3.1",
            "api_version": "1",
            "capabilities": {"doorbell_video": {"supported": True}},
        }

    async def apply_setup(_hass: Any, target_entry: Any, setup_data: dict[str, Any]) -> None:
        calls.append(f"apply_setup:{setup_data['version']}:{target_entry.entry_id}")

    api.async_validate_setup = validate_setup  # type: ignore[method-assign]
    runtime_data = FakeRuntimeData(
        api,
        capabilities={"doorbell_video": {"supported": True}},
        self_test_status={
            "ok": False,
            "checks": {
                "capabilities": {"ok": False, "reason": "missing_required"},
                "firewall": {"ok": True},
                "rtsp": {"ok": False, "reason": "rtsp_not_ready"},
                "talkback_rtp": {"ok": True},
                "homeassistant_user": {"ok": True},
                "device_routing": {"ok": True},
                "startup": {"ok": True},
            },
        },
    )
    entry = FakeEntry(runtime_data=runtime_data, options={"video_enabled": True})
    monkeypatch.setattr(repairs, "_async_apply_repaired_agent_setup", apply_setup)

    repaired = asyncio.run(_async_repair_media_setup(FakeHass(entry), entry))  # type: ignore[arg-type]

    assert repaired == ["agent_update_check"]
    assert api.calls == ["validate_setup", "self_test", "device_user_status"]
    assert calls == ["apply_setup:0.3.1:entry-1"]


def test_media_setup_repair_reports_api_failures_on_form() -> None:
    class FailingFirewallApi(FakePatchApi):
        async def async_set_firewall_enabled(self, enabled: bool) -> dict[str, Any]:
            self.calls.append(f"set_firewall_enabled:{enabled}")
            raise C300XAgentApiError("failed")

    api = FailingFirewallApi()
    runtime_data = FakeRuntimeData(
        api,
        capabilities={"doorbell_video": {"supported": True}},
        self_test_status={
            "ok": False,
            "checks": {
                "capabilities": {"ok": True},
                "firewall": {"ok": False, "reason": "ipv4_media_ports_missing"},
                "rtsp": {"ok": True},
                "talkback_rtp": {"ok": True},
                "homeassistant_user": {"ok": True},
                "device_routing": {"ok": True},
                "startup": {"ok": True},
            },
        },
    )
    entry = FakeEntry(runtime_data=runtime_data, options={"video_enabled": True})
    flow = MediaSetupRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result["type"] == "form"
    assert result["step_id"] == "confirm"
    assert result["errors"] == {"base": "media_setup_repair_failed"}
    assert result["description_placeholders"]["failed_checks"] == "firewall"
    assert api.calls == ["set_firewall_enabled:True"]


def test_device_user_repair_flow_reports_agent_failures() -> None:
    class FailingDeviceUserApi(FakePatchApi):
        async def async_ensure_homeassistant_user(
            self,
            *,
            account_label: str,
        ) -> dict[str, Any]:
            self.calls.append(f"ensure_homeassistant_user:{account_label}")
            raise C300XAgentApiError("failed")

    api = FailingDeviceUserApi()
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))
    hass = FakeHass(entry)
    hass.config.location_name = "HA Test"
    flow = DeviceUserRepairFlow(hass, "entry-1")  # type: ignore[arg-type]

    def show_form(**kwargs: Any) -> dict[str, Any]:
        return {"type": "form", **kwargs}

    flow.async_show_form = show_form  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result == {
        "type": "form",
        "step_id": "confirm",
        "errors": {"base": "device_user_setup_failed"},
    }


@pytest.mark.parametrize(
    "status",
    [
        {"homeassistant_user_present": False},
        {"homeassistant_user_present": True, "routes_consistent": False},
        {"available": False},
    ],
)
def test_device_user_repair_keeps_the_issue_when_the_user_is_still_missing(
    monkeypatch, status
) -> None:
    import custom_components.bticino_c300x.repair_flows_device_user as device_user_flow

    api = FakePatchApi()
    api.device_user_status = status
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))
    hass = FakeHass(entry)
    hass.config.location_name = "HA Test"
    flow = DeviceUserRepairFlow(hass, "entry-1")  # type: ignore[arg-type]
    deleted: list[str] = []
    monkeypatch.setattr(
        device_user_flow.ir,
        "async_delete_issue",
        lambda **kwargs: deleted.append(kwargs["issue_id"]),
    )
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result == {
        "type": "form",
        "step_id": "confirm",
        "errors": {"base": "device_user_setup_failed"},
    }
    assert deleted == []


def test_frontend_card_repair_adds_storage_lovelace_view(monkeypatch) -> None:
    lovelace_package = types.ModuleType("homeassistant.components.lovelace")
    lovelace_const = types.ModuleType("homeassistant.components.lovelace.const")
    lovelace_const.LOVELACE_DATA = "lovelace"
    lovelace_const.MODE_STORAGE = "storage"
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")

    class FakeEntityRegistry:
        def async_get_entity_id(
            self,
            domain: str,
            platform: str,
            unique_id: str,
        ) -> str | None:
            assert platform == "bticino_c300x"
            if domain == "camera" and unique_id == "entry-1_doorbell_camera":
                return "camera.bticino_c300x_doorbell_camera"
            if domain == "sensor" and unique_id == "entry-1_doorbell_state":
                return "sensor.bticino_c300x_tuerklingel_status"
            if domain == "binary_sensor" and unique_id == "entry-1_home_call_active":
                return "binary_sensor.bticino_c300x_hausanruf_aktiv"
            return None

    class FakeLovelaceDashboard:
        mode = "storage"

        def __init__(self) -> None:
            self.config: dict[str, Any] = {"views": []}

        async def async_load(self, _force: bool) -> dict[str, Any]:
            return self.config

        async def async_save(self, config: dict[str, Any]) -> None:
            self.config = config

    dashboard = FakeLovelaceDashboard()
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    hass = FakeHass(entry)
    hass.entity_registry = FakeEntityRegistry()
    hass.data["lovelace"] = types.SimpleNamespace(dashboards={None: dashboard})
    monkeypatch.setitem(sys.modules, "homeassistant.components.lovelace", lovelace_package)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.lovelace.const",
        lovelace_const,
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry,
    )
    monkeypatch.setattr(
        sys.modules["homeassistant.helpers"],
        "entity_registry",
        entity_registry,
        raising=False,
    )
    entity_registry.async_get = lambda _hass: hass.entity_registry

    path = asyncio.run(_async_setup_lovelace_cards(hass, entry))  # type: ignore[arg-type]
    second_path = asyncio.run(_async_setup_lovelace_cards(hass, entry))  # type: ignore[arg-type]

    assert path == "/lovelace/c300x"
    assert second_path == "/lovelace/c300x"
    view = dashboard.config["views"][0]
    assert view["type"] == "sections"
    assert view["path"] == "c300x"
    cards = view["sections"][0]["cards"]
    assert cards == [
        {
            "type": "custom:c300x-doorbell-call-card",
            "entity": "camera.bticino_c300x_doorbell_camera",
            "mode": "auto",
            "grid_options": {"columns": 12},
        },
    ]
    assert "'state_entity':" not in str(cards)
    assert "home_call_entity" not in str(cards)
    assert "doorbell_state_entity" not in str(cards)


def test_frontend_card_repair_replaces_legacy_split_cards(monkeypatch) -> None:
    lovelace_package = types.ModuleType("homeassistant.components.lovelace")
    lovelace_const = types.ModuleType("homeassistant.components.lovelace.const")
    lovelace_const.LOVELACE_DATA = "lovelace"
    lovelace_const.MODE_STORAGE = "storage"
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")

    class FakeEntityRegistry:
        def async_get_entity_id(
            self,
            domain: str,
            platform: str,
            unique_id: str,
        ) -> str | None:
            assert platform == "bticino_c300x"
            if domain == "camera" and unique_id == "entry-1_doorbell_camera":
                return "camera.bticino_c300x_doorbell_camera"
            return None

    class FakeLovelaceDashboard:
        mode = "storage"

        def __init__(self) -> None:
            self.config: dict[str, Any] = {
                "views": [
                    {
                        "type": "sections",
                        "title": "C300X",
                        "path": "c300x",
                        "sections": [
                            {
                                "type": "grid",
                                "cards": [
                                    {
                                        "type": "custom:c300x-doorbell-call-card",
                                        "entity": "camera.bticino_c300x_doorbell_camera",
                                        "mode": "doorbell_call",
                                    },
                                    {
                                        "type": "custom:c300x-doorbell-call-card",
                                        "entity": "camera.bticino_c300x_doorbell_camera",
                                        "mode": "home_call",
                                    },
                                ],
                            }
                        ],
                    }
                ]
            }

        async def async_load(self, _force: bool) -> dict[str, Any]:
            return self.config

        async def async_save(self, config: dict[str, Any]) -> None:
            self.config = config

    dashboard = FakeLovelaceDashboard()
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    hass = FakeHass(entry)
    hass.entity_registry = FakeEntityRegistry()
    hass.data["lovelace"] = types.SimpleNamespace(dashboards={None: dashboard})
    monkeypatch.setitem(sys.modules, "homeassistant.components.lovelace", lovelace_package)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.lovelace.const",
        lovelace_const,
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry,
    )
    monkeypatch.setattr(
        sys.modules["homeassistant.helpers"],
        "entity_registry",
        entity_registry,
        raising=False,
    )
    entity_registry.async_get = lambda _hass: hass.entity_registry

    path = asyncio.run(_async_setup_lovelace_cards(hass, entry))  # type: ignore[arg-type]

    assert path == "/lovelace/c300x"
    cards = dashboard.config["views"][0]["sections"][0]["cards"]
    assert cards == [
        {
            "type": "custom:c300x-doorbell-call-card",
            "entity": "camera.bticino_c300x_doorbell_camera",
            "mode": "auto",
            "grid_options": {"columns": 12},
        }
    ]


def test_frontend_card_repair_cleans_all_lovelace_views(monkeypatch) -> None:
    lovelace_package = types.ModuleType("homeassistant.components.lovelace")
    lovelace_const = types.ModuleType("homeassistant.components.lovelace.const")
    lovelace_const.LOVELACE_DATA = "lovelace"
    lovelace_const.MODE_STORAGE = "storage"
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")

    class FakeEntityRegistry:
        def async_get_entity_id(
            self,
            domain: str,
            platform: str,
            unique_id: str,
        ) -> str | None:
            assert platform == "bticino_c300x"
            if domain == "camera" and unique_id == "entry-1_doorbell_camera":
                return "camera.bticino_c300x_doorbell_camera"
            return None

    class FakeLovelaceDashboard:
        mode = "storage"

        def __init__(self) -> None:
            self.config: dict[str, Any] = {
                "views": [
                    {
                        "type": "sections",
                        "title": "C300X",
                        "path": "c300x",
                        "sections": [
                            {
                                "type": "grid",
                                "cards": [
                                    {
                                        "type": "custom:c300x-doorbell-call-card",
                                        "entity": "camera.bticino_c300x_doorbell_camera",
                                        "mode": "auto",
                                        "doorbell_state_entity": "sensor.old",
                                        "home_call_entity": "binary_sensor.old",
                                    },
                                ],
                            }
                        ],
                    },
                    {
                        "type": "sections",
                        "title": "C300X More",
                        "path": "c300x-more",
                        "sections": [
                            {
                                "type": "grid",
                                "cards": [
                                    {
                                        "type": "custom:c300x-doorbell-call-card",
                                        "entity": "camera.bticino_c300x_doorbell_camera",
                                        "mode": "home_call",
                                    },
                                    {
                                        "type": "custom:c300x-doorbell-call-card",
                                        "entity": "camera.bticino_c300x_doorbell_camera",
                                        "mode": "doorbell_call",
                                    },
                                ],
                            }
                        ],
                    },
                ]
            }

        async def async_load(self, _force: bool) -> dict[str, Any]:
            return self.config

        async def async_save(self, config: dict[str, Any]) -> None:
            self.config = config

    dashboard = FakeLovelaceDashboard()
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    hass = FakeHass(entry)
    hass.entity_registry = FakeEntityRegistry()
    hass.data["lovelace"] = types.SimpleNamespace(dashboards={None: dashboard})
    monkeypatch.setitem(sys.modules, "homeassistant.components.lovelace", lovelace_package)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.lovelace.const",
        lovelace_const,
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry,
    )
    monkeypatch.setattr(
        sys.modules["homeassistant.helpers"],
        "entity_registry",
        entity_registry,
        raising=False,
    )
    entity_registry.async_get = lambda _hass: hass.entity_registry

    path = asyncio.run(_async_setup_lovelace_cards(hass, entry))  # type: ignore[arg-type]

    assert path == "/lovelace/c300x"
    dashboard_text = str(dashboard.config)
    assert "doorbell_state_entity" not in dashboard_text
    assert "home_call_entity" not in dashboard_text
    assert "'mode': 'doorbell_call'" not in dashboard_text
    assert "'mode': 'home_call'" not in dashboard_text
    assert dashboard_text.count("'mode': 'auto'") == 1


def test_frontend_card_repair_adds_cards_to_selected_dashboard_and_view(
    monkeypatch,
) -> None:
    lovelace_package = types.ModuleType("homeassistant.components.lovelace")
    lovelace_const = types.ModuleType("homeassistant.components.lovelace.const")
    lovelace_const.LOVELACE_DATA = "lovelace"
    lovelace_const.MODE_STORAGE = "storage"
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")

    class FakeEntityRegistry:
        def async_get_entity_id(
            self,
            domain: str,
            platform: str,
            unique_id: str,
        ) -> str | None:
            assert platform == "bticino_c300x"
            if domain == "camera" and unique_id == "entry-1_doorbell_camera":
                return "camera.bticino_c300x_doorbell_camera"
            if domain == "sensor" and unique_id == "entry-1_doorbell_state":
                return "sensor.bticino_c300x_tuerklingel_status"
            if domain == "binary_sensor" and unique_id == "entry-1_home_call_active":
                return "binary_sensor.bticino_c300x_hausanruf_aktiv"
            return None

    class FakeLovelaceDashboard:
        mode = "storage"

        def __init__(self) -> None:
            self.title = "Test"
            self.config: dict[str, Any] = {"views": []}

        async def async_load(self, _force: bool) -> dict[str, Any]:
            return self.config

        async def async_save(self, config: dict[str, Any]) -> None:
            self.config = config

    default_dashboard = FakeLovelaceDashboard()
    selected_dashboard = FakeLovelaceDashboard()
    selected_dashboard.config = {
        "views": [
            {
                "type": "sections",
                "sections": [
                    {
                        "type": "grid",
                        "cards": [{"type": "heading", "heading": "New section"}],
                    }
                ],
            }
        ]
    }
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    hass = FakeHass(entry)
    frontend_setups: list[Any] = []
    hass.entity_registry = FakeEntityRegistry()
    hass.data["lovelace"] = types.SimpleNamespace(
        dashboards={None: default_dashboard, "dashboard-test": selected_dashboard}
    )
    monkeypatch.setitem(sys.modules, "homeassistant.components.lovelace", lovelace_package)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.lovelace.const",
        lovelace_const,
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry,
    )
    monkeypatch.setattr(
        sys.modules["homeassistant.helpers"],
        "entity_registry",
        entity_registry,
        raising=False,
    )
    entity_registry.async_get = lambda _hass: hass.entity_registry

    async def fake_async_setup_frontend(setup_hass: Any) -> None:
        frontend_setups.append(setup_hass)

    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_flows_frontend.async_setup_frontend",
        fake_async_setup_frontend,
    )

    flow = FrontendCardSetupRepairFlow(hass, "entry-1")  # type: ignore[arg-type]

    def create_entry(**kwargs: Any) -> dict[str, Any]:
        return {"type": "create_entry", **kwargs}

    flow.async_create_entry = create_entry  # type: ignore[method-assign]

    result = asyncio.run(
        flow.async_step_confirm(
            {
                _LOVELACE_DASHBOARD_FIELD: "dashboard-test",
                _LOVELACE_VIEW_FIELD: "door",
            }
        )
    )

    assert result == {
        "type": "create_entry",
        "data": {"dashboard_path": "/dashboard-test/door"},
    }
    assert entry.data[CONF_FRONTEND_CARD_SETUP_DISMISSED] is True
    assert (
        entry.data[CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION]
        == FRONTEND_CARD_SETUP_REPAIR_VERSION
    )
    assert default_dashboard.config == {"views": []}
    assert frontend_setups == [hass]
    assert len(selected_dashboard.config["views"]) == 1
    view = selected_dashboard.config["views"][0]
    assert view["path"] == "door"
    assert view["title"] == "C300X"
    assert [card["mode"] for card in view["sections"][0]["cards"][:1]] == ["auto"]
    assert "home_call_entity" not in view["sections"][0]["cards"][0]
    assert view["sections"][0]["cards"][0]["type"] == "custom:c300x-doorbell-call-card"
    assert "doorbell_state_entity" not in view["sections"][0]["cards"][0]


def test_apply_repaired_agent_setup_refreshes_runtime_state(monkeypatch) -> None:
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
        repairs,
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
    hass = FakeHass(FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi())))
    sleeps: list[float] = []

    async def bundle_metadata(_hass: Any) -> dict[str, str]:
        return {
            "agent_version": "0.3.1",
            "api_version": "1",
            "bundle_hash": "sha256:bundle",
        }

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(repairs, "async_load_packaged_bundle_metadata", bundle_metadata)
    monkeypatch.setattr(repairs.asyncio, "sleep", fake_sleep)

    result = asyncio.run(
        _async_verify_agent_after_update(
            hass,  # type: ignore[arg-type]
            api,
            {"ok": True, "restart_scheduled": True},
        )
    )

    assert result["version"] == "0.3.1"
    assert sleeps == [_AGENT_UPDATE_RESTART_SETTLE_SECONDS]
    assert api.calls == ["validate_setup"]


def test_verify_agent_update_restarts_when_running_agent_is_stale(
    monkeypatch,
) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    class StaleThenUpdatedApi:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.restarted = False

        async def async_validate_setup(self) -> dict[str, Any]:
            self.calls.append("validate_setup")
            version = "0.3.0" if not self.restarted else "0.3.1"
            return {
                "version": version,
                "api_version": "1",
                "agent": {
                    "version": version,
                    "bundle_hash": "sha256:bundle",
                    "self_update_supported": True,
                },
                "capabilities": {},
            }

        async def async_restart_agent(self) -> dict[str, Any]:
            self.calls.append("restart_agent")
            self.restarted = True
            return {"ok": True, "action": "restart_agent", "scheduled": True}

    async def bundle_metadata(_hass: Any) -> dict[str, str]:
        return {
            "agent_version": "0.3.1",
            "api_version": "1",
            "bundle_hash": "sha256:bundle",
        }

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    api = StaleThenUpdatedApi()
    hass = FakeHass(FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi())))
    monkeypatch.setattr(repairs, "async_load_packaged_bundle_metadata", bundle_metadata)
    monkeypatch.setattr(repairs.asyncio, "sleep", fake_sleep)

    result = asyncio.run(
        _async_verify_agent_after_update(
            hass,  # type: ignore[arg-type]
            api,
            {"ok": True, "restart_scheduled": False},
        )
    )

    assert result["version"] == "0.3.1"
    assert api.calls == ["validate_setup", "restart_agent", "validate_setup"]
    assert sleeps == [_AGENT_UPDATE_RESTART_SETTLE_SECONDS]


def test_wait_for_agent_after_update_retries_until_setup_succeeds(
    monkeypatch,
) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    class RestartingApi:
        def __init__(self) -> None:
            self.calls = 0

        async def async_validate_setup(self) -> dict[str, Any]:
            self.calls += 1
            if self.calls < 3:
                raise C300XAgentApiError("not ready")
            return {"version": "0.3.1"}

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    api = RestartingApi()
    monkeypatch.setattr(repairs.asyncio, "sleep", fake_sleep)

    result = asyncio.run(_async_wait_for_agent_after_update(api, initial_delay=0.5))

    assert result == {"version": "0.3.1"}
    assert api.calls == 3
    assert sleeps == [0.5, 1, 1]


def test_wait_for_agent_after_update_raises_last_error(
    monkeypatch,
) -> None:
    import custom_components.bticino_c300x.repairs as repairs

    class OfflineApi:
        async def async_validate_setup(self) -> dict[str, Any]:
            raise C300XAgentApiError("offline")

    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(repairs.asyncio, "sleep", fake_sleep)

    try:
        asyncio.run(_async_wait_for_agent_after_update(OfflineApi()))
    except C300XAgentApiError as err:
        assert "offline" in str(err)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("offline agent wait did not raise")


def test_capture_external_patch_state_marks_unknown_firewall_status() -> None:
    api = FakePatchApi()
    api.firewall_status = {"available": True, "state": "disabled", "patched": None}
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))

    patch_state = asyncio.run(_async_capture_external_patch_state(entry))

    assert patch_state.firewall_patched is False
    assert patch_state.firewall_status_known is False


@pytest.mark.parametrize("runtime_changed", [False, True])
def test_unconfirmed_display_followup_is_a_check_without_a_forced_restart(
    monkeypatch, runtime_changed,
):
    """An update whose follow-up never finished: the answer of this run does not cover it."""

    import custom_components.bticino_c300x.repairs as repairs

    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    state = _ExternalPatchState(qml_patch_required=True, firewall_patched=False,
                               firewall_status_known=True, ipv6_firewall_patched=False)
    changes = _ExternalPatchChanges(runtime_changed=runtime_changed)
    changes.display_unconfirmed = True
    calls = []

    async def restore(_entry, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(repairs, "async_restore_display_after_update", restore)
    asyncio.run(_async_restore_external_patch_state(entry, state, changes))

    # Active pages are restarted for a new agent; current pages otherwise are not.
    assert calls == [{"apply_full_patch": True, "reload_unchanged": runtime_changed}]


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
        "apply_qml_core",
        "apply_qml",
        "qml_status",
        "reload_gui",
        "qml_status",
    ]
    assert entry.runtime_data.qml_patch_status["state"] == "patched"


def test_restore_external_patch_state_reloads_gui_after_runtime_update_when_ui_active() -> None:
    api = FakePatchApi()
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))

    asyncio.run(
        _async_restore_external_patch_state(
            entry,
            _ExternalPatchState(
                qml_patch_required=True,
                firewall_patched=False,
                firewall_status_known=True,
                ipv6_firewall_patched=False,
            ),
            _ExternalPatchChanges(runtime_changed=True),
        )
    )

    assert api.calls == ["reload_gui"]


def test_restore_external_patch_state_skips_gui_reload_after_runtime_update_when_ui_inactive() -> None:
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
            _ExternalPatchChanges(runtime_changed=True),
        )
    )

    assert api.calls == []


@pytest.mark.parametrize("full_patch", [False, True])
def test_restore_external_patch_state_reconciles_qt5_runtime_even_without_optional_pages(full_patch) -> None:
    api = FakePatchApi()
    api.qml_status["qt5_overlay"] = "active"
    api.qml_status["gui_running"] = True
    api.qml_status["core_patched"] = True
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))
    # The status the update flow read just before the update.
    entry.runtime_data.qml_patch_status = dict(api.qml_status)
    state = _ExternalPatchState(
        qml_patch_required=full_patch, firewall_patched=False,
        firewall_status_known=True, ipv6_firewall_patched=False,
    )
    asyncio.run(_async_restore_external_patch_state(
        entry, state, _ExternalPatchChanges(runtime_changed=True),
    ))
    # Qt 5: the full apply carries the core files; one restart for the new runtime.
    assert api.calls == ["apply_qml" if full_patch else "apply_qml_core", "reload_gui", "qml_status"]


@pytest.mark.parametrize("full_patch", [False, True])
def test_a_qt4_runtime_update_reads_no_display_status(full_patch) -> None:
    """1.7.x/2.0.2 as in 2.9.2: a status read that would fail fails nothing."""

    class _NoStatus(FakePatchApi):
        async def async_qml_patch_status(self) -> dict[str, Any]:
            self.calls.append("qml_status")
            raise C300XAgentApiError("status read failed")

    api = _NoStatus()
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))
    entry.runtime_data.qml_patch_status = {"patched": full_patch, "core_patched": True}
    state = _ExternalPatchState(
        qml_patch_required=full_patch, firewall_patched=False,
        firewall_status_known=True, ipv6_firewall_patched=False,
    )
    outcome = asyncio.run(_async_restore_external_patch_state(
        entry, state, _ExternalPatchChanges(runtime_changed=True),
    ))
    assert outcome is None
    assert api.calls == (["reload_gui"] if full_patch else [])
    if full_patch:
        assert api.reload_display_restart is False


@pytest.mark.parametrize("full_patch", [False, True])
def test_a_failed_qt5_display_followup_completes_the_update_and_stays_owed(monkeypatch, full_patch):
    """The agent update is done; the display steps keep their own record."""

    from custom_components.bticino_c300x import qml_patch, repairs
    from custom_components.bticino_c300x.agent_update_followup import clear_followup
    from custom_components.bticino_c300x.api_errors import C300XDisplayNotConfirmedError
    api = FakePatchApi()
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))
    entry.runtime_data.qml_patch_status = {"qt5_overlay": "failed"}
    hass = FakeHass(entry)
    state = _ExternalPatchState(qml_patch_required=full_patch, firewall_patched=False,
                               firewall_status_known=True, ipv6_firewall_patched=False)
    # The mark as the update stored it before the apply.
    entry.data = {**entry.data, "agent_update_qml_pending": full_patch}
    async def quarantined(_entry, *, apply_full_patch, **_kwargs):
        assert apply_full_patch is full_patch
        raise C300XDisplayNotConfirmedError("quarantined")
    monkeypatch.setattr(qml_patch, "async_restore_qml_patches_after_update", quarantined)
    full = repairs._display_followup_full(entry, state)
    # On Qt 5 a runtime-only update changes the display (the preload library).
    outcome = asyncio.run(_async_restore_external_patch_state(
        entry, state, _ExternalPatchChanges(runtime_changed=True)))
    assert outcome is False
    repairs._settle_display_followup(hass, entry, outcome, full=full)
    clear_followup(hass, entry)
    assert "agent_update_qml_pending" not in entry.data
    assert entry.data["display_followup_pending"] is full_patch
    assert api.calls[-1:] == ["qml_status"]


def test_owed_display_steps_run_again_with_the_next_followup_and_are_cleared(monkeypatch):
    from custom_components.bticino_c300x import qml_patch, repairs
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    entry.data = {**entry.data, "display_followup_pending": True}
    hass = FakeHass(entry)
    seen = []
    async def confirmed(_entry, *, apply_full_patch, **_kwargs):
        seen.append(apply_full_patch)
    monkeypatch.setattr(qml_patch, "async_restore_qml_patches_after_update", confirmed)
    state = _ExternalPatchState(qml_patch_required=False, firewall_patched=False,
                               firewall_status_known=True, ipv6_firewall_patched=False)
    outcome = asyncio.run(_async_restore_external_patch_state(entry, state, _ExternalPatchChanges()))
    repairs._settle_display_followup(hass, entry, outcome, full=False)
    assert seen == [True]
    assert "display_followup_pending" not in entry.data


@pytest.mark.parametrize("case", ["qt4", "unreachable", "busy", "rejected"])
def test_a_display_followup_that_did_not_run_still_fails_the_update(monkeypatch, case):
    """Only a step that ran and failed on the Qt 5 display is owed; the rest fails as before."""

    from custom_components.bticino_c300x import qml_patch
    from custom_components.bticino_c300x.api_errors import (
        C300XAgentApiAuthError,
        C300XAgentApiConnectionError,
        C300XDisplayNotConfirmedError,
    )
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    entry.runtime_data.qml_patch_status = {} if case == "qt4" else {"qt5_overlay": "failed"}
    error = {
        "qt4": C300XDisplayNotConfirmedError("qt4"),
        "unreachable": C300XAgentApiConnectionError("gone"),
        "busy": C300XAgentApiConnectionError(
            "device agent returned HTTP 409: maintenance_busy", http_status=409),
        "rejected": C300XAgentApiAuthError(maintenance=True),
    }[case]
    async def failing(_entry, *, apply_full_patch, **_kwargs):
        raise error
    monkeypatch.setattr(qml_patch, "async_restore_qml_patches_after_update", failing)
    state = _ExternalPatchState(qml_patch_required=True, firewall_patched=False,
                               firewall_status_known=True, ipv6_firewall_patched=False)
    with pytest.raises(C300XAgentApiError):
        asyncio.run(_async_restore_external_patch_state(
            entry, state, _ExternalPatchChanges(qml_patch_changed=True)))


def test_a_display_write_the_agent_ran_and_failed_is_owed(monkeypatch):
    from custom_components.bticino_c300x import qml_patch
    from custom_components.bticino_c300x.api_errors import C300XAgentApiConnectionError
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    entry.runtime_data.qml_patch_status = {"qt5_overlay": "active"}
    async def failing(_entry, *, apply_full_patch, **_kwargs):
        raise C300XAgentApiConnectionError("device agent returned HTTP 502: reload_failed", http_status=502)
    monkeypatch.setattr(qml_patch, "async_restore_qml_patches_after_update", failing)
    state = _ExternalPatchState(qml_patch_required=True, firewall_patched=False,
                               firewall_status_known=True, ipv6_firewall_patched=False)
    assert asyncio.run(_async_restore_external_patch_state(
        entry, state, _ExternalPatchChanges(qml_patch_changed=True))) is False


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


def test_lovelace_repair_helpers_normalize_paths_and_fallback_options() -> None:
    hass = FakeHass(FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi())))

    assert _dashboard_select_options(hass) == [
        {"value": "__default__", "label": "Lovelace (/lovelace)"}
    ]
    assert _normalize_lovelace_target("__default__", "/lovelace/front-door") == (
        None,
        "front-door",
    )
    assert _normalize_lovelace_target("panel", "/panel/c300x") == ("panel", "c300x")

    try:
        _normalize_lovelace_target("panel", "bad/path")
    except Exception as err:  # noqa: BLE001 - private helper raises setup error
        assert str(err) == "lovelace_config_invalid"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("invalid Lovelace target was accepted")


def test_install_result_config_change_restores_active_ipv6_firewall_patch() -> None:
    changes = _ExternalPatchChanges.from_install_result(
        types.SimpleNamespace(
            changed_files=(
                "/home/bticino/cfg/extra/c300x-native-agent/config.json",
            )
        )
    )

    assert changes.config_schema_changed is True
    assert changes.runtime_changed is False
    assert changes.qml_patch_changed is False
    assert changes.firewall_patch_changed is False
    assert changes.ipv6_firewall_patch_changed is True


def test_install_result_agent_runtime_change_refreshes_active_device_ui() -> None:
    changes = _ExternalPatchChanges.from_install_result(
        types.SimpleNamespace(
            changed_files=(
                "/home/bticino/cfg/extra/c300x-native-agent/c300x-agent-native",
            )
        )
    )

    assert changes.runtime_changed is True
    assert changes.qml_patch_changed is False
    assert changes.firewall_patch_changed is False
    assert changes.ipv6_firewall_patch_changed is False


def test_update_result_agent_runtime_change_refreshes_active_device_ui() -> None:
    changes = _ExternalPatchChanges.from_update_result(
        {
            "runtime_changed": True,
            "qml_patch_changed": False,
            "firewall_patch_changed": False,
        }
    )

    assert changes.runtime_changed is True
    assert changes.qml_patch_changed is False
    assert changes.firewall_patch_changed is False
    assert changes.ipv6_firewall_patch_changed is False


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

    assert api.calls == ["apply_qml_core", "reload_gui", "qml_status"]


@pytest.mark.parametrize("flow_class", [DeviceUserRepairFlow, MediaSetupRepairFlow])
def test_repair_flows_abort_cleanly_when_the_entry_never_set_up(flow_class) -> None:
    """A failed or disabled entry has no runtime data; Fix must not raise.

    The issue can still be listed, and the user can press Fix on it.
    """

    entry = types.SimpleNamespace(entry_id="entry-1", data={}, options={})
    assert not hasattr(entry, "runtime_data")
    flow = flow_class(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    flow.async_abort = lambda **kwargs: {"type": "abort", **kwargs}  # type: ignore[method-assign]
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    assert asyncio.run(flow.async_step_confirm()) == {
        "type": "abort", "reason": "entry_not_loaded",
    }
    assert asyncio.run(flow.async_step_confirm({})) == {
        "type": "abort", "reason": "entry_not_loaded",
    }


def test_update_repair_confirm_without_self_update_opens_the_ssh_form_without_an_error() -> None:
    """The empty confirm form is not a set of SSH credentials."""

    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    entry.runtime_data.agent_update_state = FakeAgentUpdateState()
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result["step_id"] == "ssh_install"
    assert not result.get("errors")


def test_core_qml_hook_repair_clears_the_failed_status_read_that_raised_the_issue() -> None:
    from custom_components.bticino_c300x.data import C300XOperationDiagnostics

    api = FakePatchApi()
    api.qml_status = {"available": True, "core_patched": True, "core_state": "patched"}
    status_read = C300XOperationDiagnostics(last_error="timeout")
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            api,
            capabilities={"maintenance": {"supported": True, "qml_core_patch": True}},
            qml_patch_status={"available": True, "core_state": "unknown"},
            diagnostics=types.SimpleNamespace(qml_patch_diagnostics=status_read),
        )
    )
    flow = DeviceCoreQmlHookRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result["type"] == "create_entry"
    assert status_read.last_error is None


def test_ssh_install_log_text_names_the_kind_of_the_cause_but_not_its_text() -> None:
    from custom_components.bticino_c300x.repairs import _install_error_log_text

    try:
        try:
            raise TimeoutError("timed out talking to 192.0.2.60")
        except TimeoutError as cause:
            raise RuntimeError("device_install_failed") from cause
    except RuntimeError as err:
        text = _install_error_log_text(err)

    assert text == "RuntimeError: device_install_failed (cause: TimeoutError)"
    assert _install_error_log_text(RuntimeError("invalid_ssh_username")) == (
        "RuntimeError: invalid_ssh_username"
    )


@pytest.mark.parametrize(("changes", "expected"), [
    (
        {"firewall_patch_changed": True, "ipv6_firewall_patch_changed": True},
        ["apply_firewall", "set_ipv6_firewall_enabled:True", "apply_ipv6_firewall"],
    ),
    ({"runtime_changed": True}, ["reload_gui"]),
])
def test_patch_restore_after_update_waits_while_the_agent_is_busy(
    monkeypatch, changes, expected
) -> None:
    from unittest.mock import AsyncMock

    from custom_components.bticino_c300x import agent_update
    from custom_components.bticino_c300x.api_errors import C300XAgentApiConnectionError

    class BusyFirstApi(FakePatchApi):
        def __init__(self) -> None:
            super().__init__()
            self.rejected: list[str] = []

        def __getattribute__(self, name: str) -> Any:
            value = super().__getattribute__(name)
            if not name.startswith("async_"):
                return value

            async def busy_first(*args: Any, **kwargs: Any) -> Any:
                if name not in self.rejected:
                    self.rejected.append(name)
                    raise C300XAgentApiConnectionError(
                        "device agent returned HTTP 409: maintenance_busy"
                    )
                return await value(*args, **kwargs)

            return busy_first

    monkeypatch.setattr(agent_update.asyncio, "sleep", AsyncMock())
    api = BusyFirstApi()
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))
    state = _ExternalPatchState(
        qml_patch_required=True, firewall_patched=True,
        firewall_status_known=True, ipv6_firewall_patched=True,
    )

    asyncio.run(
        _async_restore_external_patch_state(entry, state, _ExternalPatchChanges(**changes))
    )

    assert api.calls == expected
    assert len(api.rejected) == len(expected)


def test_update_mqtt_migration_waits_for_a_busy_agent(monkeypatch) -> None:
    from unittest.mock import AsyncMock

    from custom_components.bticino_c300x import agent_update, repairs
    from custom_components.bticino_c300x.api_errors import C300XAgentApiConnectionError

    # The last step of an update: a status read of Home Assistant itself can
    # be running on the device just then, and everything before it succeeded.
    busy = C300XAgentApiConnectionError("device agent returned HTTP 409: maintenance_busy")
    migrate = AsyncMock(side_effect=[busy, {"ok": True}])
    api = types.SimpleNamespace(async_migrate_legacy_mqtt_to_native=migrate)
    monkeypatch.setattr(agent_update.asyncio, "sleep", AsyncMock())

    asyncio.run(repairs._async_migrate_mqtt_after_update(api))

    assert migrate.await_count == 2

    with open(repairs.__file__, encoding="utf-8") as handle:
        source = handle.read()
    assert source.count("await _async_migrate_mqtt_after_update(entry.runtime_data.api)") == 2
    assert source.count("async_migrate_legacy_mqtt_if_available(") == 1


@pytest.mark.parametrize("cause", ["agent_error", "status"])
def test_device_user_repair_asks_to_add_an_unregistered_device_in_the_app(
    monkeypatch, cause
) -> None:
    """A device never added in the Door Entry app has no SIP domain yet."""

    import custom_components.bticino_c300x.repair_flows_device_user as device_user_flow
    from custom_components.bticino_c300x.api_errors import C300XDeviceNotRegisteredError

    class UnregisteredDeviceApi(FakePatchApi):
        async def async_ensure_homeassistant_user(self, *, account_label: str) -> dict[str, Any]:
            if cause == "agent_error":
                raise C300XDeviceNotRegisteredError("device_domain_missing")
            return {"homeassistant_user_present": True, "media_identity_available": False}

    entry = FakeEntry(runtime_data=FakeRuntimeData(UnregisteredDeviceApi()))
    hass = FakeHass(entry)
    hass.config.location_name = "HA Test"
    flow = DeviceUserRepairFlow(hass, "entry-1")  # type: ignore[arg-type]
    deleted: list[str] = []
    monkeypatch.setattr(
        device_user_flow.ir, "async_delete_issue", lambda **kwargs: deleted.append(kwargs["issue_id"])
    )
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_confirm({}))

    assert result["errors"] == {"base": "device_not_registered"}
    assert deleted == []


@pytest.mark.parametrize(
    ("maintenance", "restored"),
    [
        ({"supported": True, "qml_core_patch": True}, [True]),
        ({"supported": True, "qml_core_patch": False}, []),
        # No answer about the Display patch: it is restored as before.
        (None, [True]),
    ],
)
def test_display_restore_follows_the_new_agent_capabilities(monkeypatch, maintenance, restored):
    """A Qt 5 display (firmware 3.0.x) has no Display patch to restore."""

    import custom_components.bticino_c300x.repairs as repairs

    api = FakePatchApi()
    entry = FakeEntry(runtime_data=FakeRuntimeData(api))
    state = _ExternalPatchState(qml_patch_required=True, firewall_patched=True,
                               firewall_status_known=True, ipv6_firewall_patched=False)
    calls = []

    async def restore(_entry, *, apply_full_patch, reload_unchanged=True):
        calls.append(apply_full_patch)

    monkeypatch.setattr(repairs, "async_restore_display_after_update", restore)
    # The setup payload as async_validate_setup returns it.
    setup_data = asyncio.run(FakeUpdateVerifyApi().async_validate_setup())
    if maintenance is not None:
        setup_data["capabilities"]["maintenance"] = maintenance
    asyncio.run(_async_restore_external_patch_state(
        entry, state, _ExternalPatchChanges(qml_patch_changed=True, firewall_patch_changed=True),
        setup_data,
    ))

    assert calls == restored
    # The firewall is restored on every display.
    assert "apply_firewall" in api.calls


def test_ssh_install_uses_the_factory_login_and_asks_only_after_a_refusal(monkeypatch) -> None:
    import custom_components.bticino_c300x.repairs as repairs
    from custom_components.bticino_c300x.device_installer import C300XDeviceInstallError
    from custom_components.bticino_c300x.factory_login import factory_ssh_login

    entry = FakeEntry(
        runtime_data=FakeRuntimeData(FakePatchApi()),
        data={"agent_host": "192.0.2.60", "agent_token": "t", "maintenance_token": "m"},
    )
    entry.runtime_data.agent_update_state = FakeAgentUpdateState()
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    logins: list[tuple[str, str]] = []

    async def install_agent(request: Any, **_kwargs: Any) -> Any:
        logins.append((request.ssh_username, request.ssh_password))
        raise C300XDeviceInstallError("ssh_login_refused")

    async def ensure_installer_dependencies(_hass: Any) -> None:
        return None

    monkeypatch.setattr(repairs, "async_install_device_agent", install_agent)
    monkeypatch.setattr(repairs, "async_ensure_installer_dependencies", ensure_installer_dependencies)
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    # Nothing to type at first: the form only confirms the install.
    first = asyncio.run(flow.async_step_ssh_install(None))
    assert first["data_schema"].schema == {}
    refused = asyncio.run(flow.async_step_ssh_install({}))
    assert logins == [factory_ssh_login()]
    assert refused["errors"] == {"base": "ssh_login_refused"}
    asked = refused["data_schema"]({})
    assert set(asked) == {"bootstrap_ssh_username", "bootstrap_ssh_password"}

    asyncio.run(flow.async_step_ssh_install({
        "bootstrap_ssh_username": "admin", "bootstrap_ssh_password": "typed",
    }))
    assert logins[-1] == ("admin", "typed")
    # The fields stay once asked for, also after another kind of failure.
    assert set(asyncio.run(flow.async_step_ssh_install(None))["data_schema"]({})) == set(asked)


def test_the_core_repair_runs_the_whole_owed_display_followup_and_clears_it() -> None:
    """Steps an update left undone: core, full Display patch, restart, confirmation."""

    api = FakePatchApi()
    api.qml_status = {"available": True, "patched": True, "state": "patched",
                      "core_patched": True, "core_state": "patched"}
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(
            api,
            capabilities={"maintenance": {"supported": True, "qml_core_patch": True}},
            qml_patch_status=dict(api.qml_status),
        ),
        data={"display_followup_pending": True},
    )
    flow = DeviceCoreQmlHookRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]
    result = asyncio.run(flow.async_step_confirm({}))
    assert result["type"] == "create_entry", result
    assert api.calls[:2] == ["apply_qml_core", "apply_qml"]
    assert "reload_gui" in api.calls
    assert "display_followup_pending" not in entry.data


def test_a_display_write_timeout_during_the_ssh_install_is_shown_on_the_form(monkeypatch) -> None:
    """The flow itself, not only its helper: the form carries the display
    time-out, a text of the repair exists for it in every language, and no
    other login is asked for."""

    import json
    from pathlib import Path

    import custom_components.bticino_c300x.repairs as repairs
    from custom_components.bticino_c300x.device_installer import C300XDeviceInstallError

    entry = FakeEntry(
        runtime_data=FakeRuntimeData(FakePatchApi()),
        data={"agent_host": "192.0.2.60", "agent_token": "t", "maintenance_token": "m"},
    )
    entry.runtime_data.agent_update_state = FakeAgentUpdateState()
    flow = DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    installs: list[Any] = []

    async def install_agent(request: Any, **_kwargs: Any) -> Any:
        installs.append(request)
        raise C300XDeviceInstallError("device_display_timeout")

    async def ensure_installer_dependencies(_hass: Any) -> None:
        return None

    monkeypatch.setattr(repairs, "async_install_device_agent", install_agent)
    monkeypatch.setattr(repairs, "async_ensure_installer_dependencies", ensure_installer_dependencies)
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_ssh_install({}))

    assert len(installs) == 1
    assert result["type"] == "form" and result["step_id"] == "ssh_install"
    assert result["errors"] == {"base": "device_display_timeout"}
    assert result["data_schema"].schema == {}
    integration = Path(repairs.__file__).parent
    for path in (integration / "strings.json", *(integration / "translations").glob("*.json")):
        texts = json.loads(path.read_text(encoding="utf-8"))
        errors = texts["issues"]["device_agent_update_required"]["fix_flow"]["error"]
        assert errors.get("device_display_timeout"), path.name


def test_a_display_write_timeout_of_the_ssh_install_keeps_its_own_error() -> None:
    import json
    from pathlib import Path

    from custom_components.bticino_c300x import repairs
    from custom_components.bticino_c300x.device_installer import C300XDeviceInstallError

    assert repairs._ssh_install_error(C300XDeviceInstallError("device_display_timeout")) == (
        "device_display_timeout")
    assert repairs._ssh_install_error(C300XDeviceInstallError("ssh_login_refused")) == "ssh_login_refused"
    assert repairs._ssh_install_error(C300XDeviceInstallError("device_install_failed")) == "ssh_install_failed"
    assert repairs._ssh_install_error(RuntimeError("x")) == "ssh_install_failed"
    strings = json.loads((Path(repairs.__file__).parent / "strings.json").read_text(encoding="utf-8"))
    assert "device_display_timeout" in strings["config"]["error"]
