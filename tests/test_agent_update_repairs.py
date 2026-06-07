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
IGNORED_ISSUES: list[tuple[str, str, bool]] = []
issue_registry.async_delete_issue = lambda **_kwargs: None
issue_registry.async_ignore_issue = (
    lambda hass, domain, issue_id, ignore: IGNORED_ISSUES.append(
        (domain, issue_id, ignore)
    )
)
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

from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_CALLBACK_BASE_URL,
    CONF_DEVICE_UI_ENABLED,
    CONF_FRONTEND_CARD_SETUP_DISMISSED,
    CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION,
    DOMAIN,
    FRONTEND_CARD_SETUP_REPAIR_VERSION,
)
from custom_components.bticino_c300x.repairs import (  # noqa: E402
    _AGENT_UPDATE_RESTART_SETTLE_SECONDS,
    _LOVELACE_DASHBOARD_FIELD,
    _LOVELACE_VIEW_FIELD,
    CallbackUrlRepairFlow,
    DeviceAgentUpdateRepairFlow,
    DeviceCoreQmlHookRepairFlow,
    FrontendCardSetupRepairFlow,
    _async_apply_repaired_agent_setup,
    _async_capture_external_patch_state,
    _async_reload_entry_after_agent_update,
    _async_restore_external_patch_state,
    _async_setup_lovelace_cards,
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

    async def async_apply_qml_core_patch(self) -> dict[str, Any]:
        self.calls.append("apply_qml_core")
        return {
            "available": True,
            "patched": False,
            "state": "original",
            "core_patched": True,
            "core_state": "patched",
        }

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

    def async_update_entry(self, entry: Any, **kwargs: Any) -> None:
        if "options" in kwargs:
            entry.options = kwargs["options"]


class FakeHass:
    def __init__(self, entry: Any) -> None:
        self.config_entries = FakeConfigEntries(entry)
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


def setup_function() -> None:
    IGNORED_ISSUES.clear()


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


def test_frontend_card_repair_flow_init_ignores_internal_flow_data(monkeypatch) -> None:
    """Starting the Lovelace card repair must not submit the confirm form."""

    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    flow = FrontendCardSetupRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repairs._dashboard_selector",
        lambda _hass: str,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repairs._text_selector",
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


def test_frontend_card_repair_can_be_ignored() -> None:
    """Ignoring the Lovelace card repair persists the dismissal."""

    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    flow = FrontendCardSetupRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]

    def create_entry(**kwargs: Any) -> dict[str, Any]:
        return {"type": "create_entry", **kwargs}

    flow.async_create_entry = create_entry  # type: ignore[method-assign]

    result = asyncio.run(flow.async_step_ignore())

    assert result == {"type": "create_entry", "data": {"ignored": True}}
    assert entry.options[CONF_FRONTEND_CARD_SETUP_DISMISSED] is True
    assert (
        entry.options[CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION]
        == FRONTEND_CARD_SETUP_REPAIR_VERSION
    )
    assert IGNORED_ISSUES == [
        (DOMAIN, "frontend_card_setup_hint_entry-1", True),
    ]


def test_callback_url_repair_flow_stores_valid_override_and_reloads() -> None:
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    entry.data = {"agent_host": "192.0.2.60", "agent_port": 8091}
    hass = FakeHass(entry)
    flow = CallbackUrlRepairFlow(hass, "entry-1")  # type: ignore[arg-type]

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
            assert domain == "camera"
            assert platform == "bticino_c300x"
            assert unique_id == "entry-1_doorbell_camera"
            return "camera.bticino_c300x_doorbell_camera"

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
            "mode": "home_call",
            "name": "C300X Home Call",
            "grid_options": {"columns": 6, "rows": 1},
        },
        {
            "type": "custom:c300x-doorbell-call-card",
            "entity": "camera.bticino_c300x_doorbell_camera",
            "grid_options": {"columns": 12, "rows": 7},
        },
    ]
    assert "state_entity" not in str(cards)


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
            assert domain == "camera"
            assert platform == "bticino_c300x"
            assert unique_id == "entry-1_doorbell_camera"
            return "camera.bticino_c300x_doorbell_camera"

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
        "custom_components.bticino_c300x.repairs.async_setup_frontend",
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
    assert entry.options[CONF_FRONTEND_CARD_SETUP_DISMISSED] is True
    assert (
        entry.options[CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION]
        == FRONTEND_CARD_SETUP_REPAIR_VERSION
    )
    assert default_dashboard.config == {"views": []}
    assert frontend_setups == [hass]
    assert len(selected_dashboard.config["views"]) == 1
    view = selected_dashboard.config["views"][0]
    assert view["path"] == "door"
    assert view["title"] == "C300X"
    assert [card["mode"] for card in view["sections"][0]["cards"][:1]] == [
        "home_call"
    ]
    assert view["sections"][0]["cards"][1]["type"] == "custom:c300x-doorbell-call-card"


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
        "apply_qml_core",
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

    assert api.calls == ["apply_qml_core"]
