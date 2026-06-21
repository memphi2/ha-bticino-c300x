from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

if "homeassistant.components.switch" not in sys.modules:
    homeassistant = sys.modules.setdefault(
        "homeassistant",
        types.ModuleType("homeassistant"),
    )
    components = sys.modules.setdefault(
        "homeassistant.components",
        types.ModuleType("homeassistant.components"),
    )
    switch = types.ModuleType("homeassistant.components.switch")
    config_entries = sys.modules.setdefault(
        "homeassistant.config_entries",
        types.ModuleType("homeassistant.config_entries"),
    )
    core = sys.modules.setdefault(
        "homeassistant.core",
        types.ModuleType("homeassistant.core"),
    )
    const = sys.modules.setdefault(
        "homeassistant.const",
        types.ModuleType("homeassistant.const"),
    )
    exceptions = sys.modules.setdefault(
        "homeassistant.exceptions",
        types.ModuleType("homeassistant.exceptions"),
    )
    helpers = sys.modules.setdefault(
        "homeassistant.helpers",
        types.ModuleType("homeassistant.helpers"),
    )
    entity = sys.modules.setdefault(
        "homeassistant.helpers.entity",
        types.ModuleType("homeassistant.helpers.entity"),
    )
    dispatcher = sys.modules.setdefault(
        "homeassistant.helpers.dispatcher",
        types.ModuleType("homeassistant.helpers.dispatcher"),
    )
    config_validation = types.ModuleType("homeassistant.helpers.config_validation")
    entity_platform = sys.modules.setdefault(
        "homeassistant.helpers.entity_platform",
        types.ModuleType("homeassistant.helpers.entity_platform"),
    )

    class SwitchEntity:  # pragma: no cover - import-time stub only
        def async_write_ha_state(self) -> None:
            self.wrote_state = True

    class ConfigEntry:  # pragma: no cover - import-time stub only
        pass

    class HomeAssistant:  # pragma: no cover - import-time stub only
        pass

    class Entity:  # pragma: no cover - import-time stub only
        pass

    class DeviceInfo(dict):  # pragma: no cover - import-time stub only
        pass

    class EntityCategory:  # pragma: no cover - import-time stub only
        CONFIG = "config"

    class HomeAssistantError(Exception):  # pragma: no cover - import-time stub only
        pass

    switch.SwitchEntity = SwitchEntity
    config_entries.ConfigEntry = ConfigEntry
    const.EntityCategory = EntityCategory
    core.HomeAssistant = HomeAssistant
    core.callback = lambda func: func
    exceptions.HomeAssistantError = HomeAssistantError
    config_validation.config_entry_only_config_schema = lambda _domain: dict
    dispatcher.async_dispatcher_connect = lambda *args, **kwargs: (lambda: None)
    dispatcher.async_dispatcher_send = lambda *args, **kwargs: None
    helpers.config_validation = config_validation
    entity.Entity = Entity
    entity.DeviceInfo = DeviceInfo
    entity_platform.AddEntitiesCallback = object
    helpers.entity = entity
    helpers.dispatcher = dispatcher
    helpers.entity_platform = entity_platform
    components.switch = switch
    homeassistant.components = components
    sys.modules["homeassistant.components.switch"] = switch
    sys.modules["homeassistant.helpers.config_validation"] = config_validation

from custom_components.bticino_c300x.api import (
    C300XAgentApiConnectionError,  # noqa: E402
    C300XAgentApiUnsupportedError,  # noqa: E402
)
from custom_components.bticino_c300x.switch import (  # noqa: E402
    C300XAnsweringMachineSwitch,
    C300XFirewallPatchSwitch,
    C300XGuiFunctionPatchSwitch,
    C300XHomeAssistantMediaUserSetupSwitch,
    C300XIpv6FirewallPatchSwitch,
    C300XLegacyMqttBridgeSwitch,
    C300XMaintenanceNoAuthSwitch,
    C300XMaintenanceSshSwitch,
    C300XMdnsDiscoverySwitch,
    C300XNativeMqttBridgeSwitch,
    C300XNoAuthSwitch,
    C300XRingerMuteSwitch,
    _async_refresh_initial_states,
    async_setup_entry,
)


def test_config_switches_are_disabled_by_default() -> None:
    config_switch_classes = (
        C300XHomeAssistantMediaUserSetupSwitch,
        C300XMaintenanceSshSwitch,
        C300XGuiFunctionPatchSwitch,
        C300XFirewallPatchSwitch,
        C300XIpv6FirewallPatchSwitch,
        C300XNativeMqttBridgeSwitch,
        C300XLegacyMqttBridgeSwitch,
        C300XNoAuthSwitch,
        C300XMdnsDiscoverySwitch,
        C300XMaintenanceNoAuthSwitch,
    )

    for switch_class in config_switch_classes:
        assert switch_class._attr_entity_registry_enabled_default is False


class _FakeApi:
    def __init__(self) -> None:
        self.active_smartphone_reads = 0
        self.cached_smartphone_reads = 0
        self.ringer_reads = 0
        self.ringer_sets: list[bool] = []
        self.ringer_status_error = False
        self.answering_machine_reads = 0
        self.answering_machine_sets: list[bool] = []
        self.answering_machine_status_error = False
        self.ssh_reads = 0
        self.ssh_sets: list[bool] = []
        self.ssh_status_error = False
        self.qml_patch_status_reads = 0
        self.qml_patch_actions: list[str] = []
        self.qml_patch_status_error = False
        self.firewall_status_reads = 0
        self.firewall_actions: list[str] = []
        self.firewall_supported = True
        self.firewall_config_enabled = True
        self.maintenance_config_enabled = True
        self.firewall_enable_sets: list[bool] = []
        self.ipv6_firewall_status_reads = 0
        self.ipv6_firewall_actions: list[str] = []
        self.ipv6_firewall_supported = True
        self.ipv6_firewall_config_enabled = True
        self.ipv6_firewall_enable_sets: list[bool] = []
        self.auth_config_reads = 0
        self.auth_config_error = False
        self.device_user_status_reads = 0
        self.device_user_actions: list[str] = []
        self.device_user_status_error = False
        self.no_auth_sets: list[tuple[bool, str | None, str | None, bool | None]] = []
        self.maintenance_no_auth_sets: list[bool] = []
        self.mdns_sets: list[bool] = []
        self.mqtt_status_reads = 0
        self.mqtt_enabled_sets: list[bool] = []
        self.mqtt_enabled = False
        self.mqtt_status_error = False
        self.legacy_mqtt_status_reads = 0
        self.legacy_mqtt_enabled_sets: list[bool] = []
        self.legacy_mqtt_enabled = True
        self.legacy_mqtt_status_error = False

    async def async_smartphone_forwarding_status(self) -> dict[str, Any]:
        self.active_smartphone_reads += 1
        return {"mode": 2, "state": "blocked"}

    async def async_smartphone_forwarding_cached_status(self) -> dict[str, Any]:
        self.cached_smartphone_reads += 1
        return {"mode": None, "state": "unknown"}

    async def async_ringer_status(self) -> dict[str, Any]:
        self.ringer_reads += 1
        if self.ringer_status_error:
            raise C300XAgentApiConnectionError("offline")
        return {"muted": False}

    async def async_set_ringer_muted(self, muted: bool) -> dict[str, Any]:
        self.ringer_sets.append(muted)
        return {"muted": muted}

    async def async_answering_machine_status(self) -> dict[str, Any]:
        self.answering_machine_reads += 1
        if self.answering_machine_status_error:
            raise C300XAgentApiConnectionError("offline")
        return {"enabled": True, "greeting_message_enabled": False}

    async def async_set_answering_machine_enabled(self, enabled: bool) -> dict[str, Any]:
        self.answering_machine_sets.append(enabled)
        return {"enabled": enabled, "greeting_message_enabled": False}

    async def async_ssh_status(self) -> dict[str, Any]:
        self.ssh_reads += 1
        if self.ssh_status_error:
            raise C300XAgentApiConnectionError("offline")
        return {"running": True}

    async def async_set_ssh_enabled(self, enabled: bool) -> dict[str, Any]:
        self.ssh_sets.append(enabled)
        return {"running": enabled}

    async def async_qml_patch_status(self) -> dict[str, Any]:
        self.qml_patch_status_reads += 1
        if self.qml_patch_status_error:
            raise C300XAgentApiConnectionError("offline")
        if self.qml_patch_actions[-1:] == ["apply"]:
            return {"available": True, "patched": True, "state": "patched"}
        if self.qml_patch_actions[-1:] == ["restore"]:
            return {"available": True, "patched": False, "state": "original"}
        return {"available": True, "patched": False, "state": "original"}

    async def async_apply_qml_patch(
        self,
        *,
        dynamic_homepage: bool = False,
    ) -> dict[str, Any]:
        _ = dynamic_homepage
        self.qml_patch_actions.append("apply")
        return {"available": True, "patched": True, "state": "patched"}

    async def async_restore_qml_patch(self) -> dict[str, Any]:
        self.qml_patch_actions.append("restore")
        return {"available": True, "patched": False, "state": "original"}

    async def async_firewall_status(self) -> dict[str, Any]:
        self.firewall_status_reads += 1
        if not self.maintenance_config_enabled:
            raise C300XAgentApiConnectionError("device agent returned HTTP 403")
        if not self.firewall_supported:
            raise C300XAgentApiUnsupportedError("firewall disabled")
        if self.firewall_actions[-1:] == ["apply"]:
            patched = True
            state = "patched"
        else:
            patched = False
            state = "original"
        return {
            "available": True,
            "family": "ipv4",
            "patched": patched,
            "state": state,
            "exists": True,
            "backup_available": True,
            "api_port": 8091,
        }

    async def async_apply_firewall(self) -> dict[str, Any]:
        self.firewall_actions.append("apply")
        return {
            "available": True,
            "family": "ipv4",
            "patched": True,
            "state": "patched",
            "exists": True,
            "backup_available": True,
            "api_port": 8091,
            "changed_files": 1,
        }

    async def async_restore_firewall(self) -> dict[str, Any]:
        self.firewall_actions.append("restore")
        return {
            "available": True,
            "family": "ipv4",
            "patched": False,
            "state": "original",
            "exists": True,
            "backup_available": True,
            "api_port": 8091,
            "changed_files": 1,
        }

    async def async_ipv6_firewall_status(self) -> dict[str, Any]:
        self.ipv6_firewall_status_reads += 1
        if not self.maintenance_config_enabled:
            raise C300XAgentApiConnectionError("device agent returned HTTP 403")
        if not self.ipv6_firewall_supported:
            raise C300XAgentApiUnsupportedError("ipv6 firewall disabled")
        if self.ipv6_firewall_actions[-1:] == ["apply"]:
            patched = True
            state = "patched"
        else:
            patched = False
            state = "original"
        return {
            "available": True,
            "family": "ipv6",
            "patched": patched,
            "state": state,
            "exists": True,
            "backup_available": True,
            "api_port": 8091,
        }

    async def async_apply_ipv6_firewall(self) -> dict[str, Any]:
        self.ipv6_firewall_actions.append("apply")
        return {
            "available": True,
            "family": "ipv6",
            "patched": True,
            "state": "patched",
            "exists": True,
            "backup_available": True,
            "api_port": 8091,
            "changed_files": 1,
        }

    async def async_restore_ipv6_firewall(self) -> dict[str, Any]:
        self.ipv6_firewall_actions.append("restore")
        return {
            "available": True,
            "family": "ipv6",
            "patched": False,
            "state": "original",
            "exists": True,
            "backup_available": True,
            "api_port": 8091,
            "changed_files": 1,
        }

    async def async_auth_config_status(self) -> dict[str, Any]:
        self.auth_config_reads += 1
        if self.auth_config_error:
            raise C300XAgentApiConnectionError("offline")
        return {
            "no_auth": True,
            "api_token_configured": False,
            "maintenance_token_configured": True,
            "maintenance_enabled": self.maintenance_config_enabled,
            "maintenance_no_auth_allowed": False,
            "mdns_enabled": True,
            "firewall_enabled": self.firewall_config_enabled,
            "ipv6_firewall_enabled": self.ipv6_firewall_config_enabled,
        }

    async def async_device_user_status(self) -> dict[str, Any]:
        self.device_user_status_reads += 1
        if self.device_user_status_error:
            raise C300XAgentApiConnectionError("offline")
        return {
            "homeassistant_user_present": True,
            "routes_consistent": True,
            "device_routing_applied": True,
            "media_user_label_applied": True,
        }

    async def async_ensure_homeassistant_user(
        self,
        *,
        account_label: str | None = None,
    ) -> dict[str, Any]:
        self.device_user_actions.append(f"ensure:{account_label or ''}")
        return {
            "homeassistant_user_present": True,
            "routes_consistent": True,
            "media_identity_available": True,
            "device_routing_applied": True,
            "device_routing_state": "patched",
            "device_routing_backup_present": True,
            "media_user_label_applied": True,
            "media_user_label_state": "patched",
            "account_label": account_label,
        }

    async def async_restore_homeassistant_media_user_setup(self) -> dict[str, Any]:
        self.device_user_actions.append("restore")
        return {
            "homeassistant_user_present": False,
            "routes_consistent": False,
            "media_identity_available": False,
            "device_routing_applied": False,
            "device_routing_state": "original",
            "media_user_label_applied": False,
            "media_user_label_state": "original",
        }

    async def async_set_no_auth_enabled(
        self,
        enabled: bool,
        *,
        api_token: str | None = None,
        maintenance_token: str | None = None,
        maintenance_no_auth_allowed: bool | None = None,
    ) -> dict[str, Any]:
        self.no_auth_sets.append(
            (enabled, api_token, maintenance_token, maintenance_no_auth_allowed)
        )
        return {
            "no_auth": enabled,
            "api_token_configured": True,
            "maintenance_token_configured": True,
            "maintenance_no_auth_allowed": bool(maintenance_no_auth_allowed),
            "mdns_enabled": True,
        }

    async def async_set_mdns_enabled(self, enabled: bool) -> dict[str, Any]:
        self.mdns_sets.append(enabled)
        return {
            "no_auth": True,
            "api_token_configured": True,
            "maintenance_token_configured": True,
            "maintenance_no_auth_allowed": False,
            "mdns_enabled": enabled,
        }

    async def async_set_maintenance_no_auth_allowed(
        self,
        enabled: bool,
    ) -> dict[str, Any]:
        self.maintenance_no_auth_sets.append(enabled)
        return {
            "no_auth": True,
            "api_token_configured": True,
            "maintenance_token_configured": True,
            "maintenance_no_auth_allowed": enabled,
            "mdns_enabled": True,
        }

    async def async_set_firewall_enabled(self, enabled: bool) -> dict[str, Any]:
        self.firewall_enable_sets.append(enabled)
        self.firewall_config_enabled = enabled
        if enabled:
            self.firewall_supported = True
            self.maintenance_config_enabled = True
        return {
            "no_auth": True,
            "api_token_configured": True,
            "maintenance_token_configured": True,
            "maintenance_enabled": self.maintenance_config_enabled,
            "maintenance_no_auth_allowed": False,
            "mdns_enabled": True,
            "firewall_enabled": enabled,
        }

    async def async_set_ipv6_firewall_enabled(self, enabled: bool) -> dict[str, Any]:
        self.ipv6_firewall_enable_sets.append(enabled)
        self.ipv6_firewall_config_enabled = enabled
        if enabled:
            self.ipv6_firewall_supported = True
            self.maintenance_config_enabled = True
        return {
            "no_auth": True,
            "api_token_configured": True,
            "maintenance_token_configured": True,
            "maintenance_enabled": self.maintenance_config_enabled,
            "maintenance_no_auth_allowed": False,
            "mdns_enabled": True,
            "ipv6_firewall_enabled": enabled,
        }

    async def async_mqtt_status(self) -> dict[str, Any]:
        self.mqtt_status_reads += 1
        if self.mqtt_status_error:
            raise C300XAgentApiConnectionError("offline")
        return {
            "available": True,
            "enabled": self.mqtt_enabled,
            "configured": True,
            "connected": self.mqtt_enabled,
            "subscribed": self.mqtt_enabled,
            "host_configured": True,
            "username_configured": True,
            "password_configured": True,
            "port": 1883,
            "client_id": "c300x-native-agent",
            "command_host": "127.0.0.1",
            "command_port": 30006,
            "command_topic": "Bticino/rx",
            "event_topic": "Bticino/tx",
            "json_event_topic": None,
            "status_topic": "Bticino/start_date",
            "availability_topic": "Bticino/LastWillT",
            "qos": 0,
            "keepalive_seconds": 120,
        }

    async def async_set_mqtt_enabled(self, enabled: bool) -> dict[str, Any]:
        self.mqtt_enabled_sets.append(enabled)
        self.mqtt_enabled = enabled
        if enabled:
            self.legacy_mqtt_enabled = False
        return await self.async_mqtt_status()

    async def async_legacy_mqtt_status(self) -> dict[str, Any]:
        self.legacy_mqtt_status_reads += 1
        if self.legacy_mqtt_status_error:
            raise C300XAgentApiConnectionError("offline")
        return {
            "available": True,
            "enabled": self.legacy_mqtt_enabled,
            "installed": self.legacy_mqtt_enabled,
            "running": self.legacy_mqtt_enabled,
            "backup_available": True,
            "native_enabled": self.mqtt_enabled,
            "exclusive": True,
            "script_path": "/etc/tcpdump2mqtt/TcpDump2Mqtt.sh",
            "init_link": "/etc/rc5.d/S99TcpDump2Mqtt",
            "flexisip_backup_available": True,
            "flexisip_restart_marker": True,
            "flexisip_reference_state": "legacy_mqtt_patch",
        }

    async def async_set_legacy_mqtt_enabled(self, enabled: bool) -> dict[str, Any]:
        self.legacy_mqtt_enabled_sets.append(enabled)
        self.legacy_mqtt_enabled = enabled
        if enabled:
            self.mqtt_enabled = False
        return await self.async_legacy_mqtt_status()


@dataclass
class _FakeConnectionState:
    available: bool = True


@dataclass
class _FakeRuntimeData:
    capabilities: dict[str, Any] = field(default_factory=dict)
    api: _FakeApi = field(default_factory=_FakeApi)
    connection_state: _FakeConnectionState = field(default_factory=_FakeConnectionState)
    qml_patch_status: dict[str, Any] = field(default_factory=dict)
    qml_patch_status_updated_at: Any = None
    device_user_status: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    runtime_data: _FakeRuntimeData = field(default_factory=_FakeRuntimeData)


def test_setup_entry_adds_capability_backed_switches() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "ringer": {"supported": True},
                "answering_machine": {"supported": True},
                "device_user": {"supported": True},
                "doorbell_video": {"supported": True},
            }
        ),
        options={"video_enabled": True},
    )
    entities: list[Any] = []

    asyncio.run(async_setup_entry(None, entry, entities.extend))  # type: ignore[arg-type]

    assert any(isinstance(entity, C300XRingerMuteSwitch) for entity in entities)
    assert any(isinstance(entity, C300XAnsweringMachineSwitch) for entity in entities)
    assert any(
        isinstance(entity, C300XHomeAssistantMediaUserSetupSwitch)
        for entity in entities
    )


def test_ringer_unmuted_event_updates_switch_state() -> None:
    entity = C300XRingerMuteSwitch(_FakeEntry())  # type: ignore[arg-type]

    entity._handle_agent_event(
        SimpleNamespace(data={"entry_id": "entry-1", "event_type": "ringer_unmuted"})
    )

    assert entity.is_on is False


def test_ringer_switch_refreshes_and_updates_mute_state() -> None:
    entry = _FakeEntry()
    entity = C300XRingerMuteSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())
    asyncio.run(entity.async_turn_on())
    asyncio.run(entity.async_turn_off())

    assert entry.runtime_data.api.ringer_reads == 1
    assert entry.runtime_data.api.ringer_sets == [True, False]
    assert entity.is_on is False
    assert entity.available is True


def test_ringer_switch_marks_unavailable_when_refresh_fails() -> None:
    entry = _FakeEntry()
    entry.runtime_data.api.ringer_status_error = True
    entity = C300XRingerMuteSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False
    assert entity.is_on is None


def test_ringer_event_ignores_foreign_or_unrelated_updates() -> None:
    entity = C300XRingerMuteSwitch(_FakeEntry())  # type: ignore[arg-type]
    entity._muted = True

    entity._handle_agent_event(
        SimpleNamespace(data={"entry_id": "other", "event_type": "ringer_unmuted"})
    )
    entity._handle_agent_event(
        SimpleNamespace(data={"entry_id": "entry-1", "event_type": "doorbell_pressed"})
    )

    assert entity.is_on is True


def test_answering_machine_switch_refreshes_and_updates_state() -> None:
    entry = _FakeEntry()
    entity = C300XAnsweringMachineSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())
    asyncio.run(entity.async_turn_off())
    asyncio.run(entity.async_turn_on())

    assert entry.runtime_data.api.answering_machine_reads == 1
    assert entry.runtime_data.api.answering_machine_sets == [False, True]
    assert entity.is_on is True
    assert entity.extra_state_attributes == {"greeting_message_enabled": False}
    assert entity.available is True


def test_answering_machine_switch_marks_unavailable_when_refresh_fails() -> None:
    entry = _FakeEntry()
    entry.runtime_data.api.answering_machine_status_error = True
    entity = C300XAnsweringMachineSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False
    assert entity.is_on is None


def test_maintenance_ssh_switch_refreshes_running_state() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"maintenance": {"supported": True, "ssh_start": True}},
        )
    )
    entity = C300XMaintenanceSshSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entry.runtime_data.api.ssh_reads == 1
    assert entity.is_on is True


def test_maintenance_ssh_switch_stops_ssh() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"maintenance": {"supported": True, "ssh_start": True}},
        )
    )
    entity = C300XMaintenanceSshSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_turn_off())

    assert entry.runtime_data.api.ssh_sets == [False]
    assert entity.is_on is False


def test_maintenance_ssh_switch_starts_ssh() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"maintenance": {"supported": True, "ssh_start": True}},
        )
    )
    entity = C300XMaintenanceSshSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_turn_on())

    assert entry.runtime_data.api.ssh_sets == [True]
    assert entity.is_on is True


def test_maintenance_ssh_switch_marks_unavailable_when_refresh_fails() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"maintenance": {"supported": True, "ssh_start": True}},
        )
    )
    entry.runtime_data.api.ssh_status_error = True
    entity = C300XMaintenanceSshSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False


def test_homeassistant_media_user_setup_refreshes_before_hass_is_bound() -> None:
    entry = _FakeEntry()
    entity = C300XHomeAssistantMediaUserSetupSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entry.runtime_data.api.device_user_status_reads == 1
    assert entry.runtime_data.device_user_status["homeassistant_user_present"] is True
    assert entity.available is True
    assert entity.is_on is True


def test_homeassistant_media_user_setup_applies_and_restores_with_hass_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _FakeEntry()
    entity = C300XHomeAssistantMediaUserSetupSwitch(entry)  # type: ignore[arg-type]
    entity.hass = SimpleNamespace(config=SimpleNamespace(location_name="Test"))
    repair_calls: list[str] = []
    repair_issues = types.ModuleType("custom_components.bticino_c300x.repair_issues")
    repair_issues.async_sync_entry_repair_issues = (
        lambda hass, entry: repair_calls.append("repair")
    )

    monkeypatch.setitem(
        sys.modules,
        "custom_components.bticino_c300x.repair_issues",
        repair_issues,
    )

    async def refresh_diagnostics(hass: object, entry: object) -> None:
        repair_calls.append("diagnostics")

    monkeypatch.setattr(
        "custom_components.bticino_c300x.switch.async_refresh_agent_diagnostics",
        refresh_diagnostics,
    )

    asyncio.run(entity.async_turn_on())
    assert entry.runtime_data.api.device_user_actions == [
        "ensure:Home Assistant Test"
    ]
    assert entity.is_on is True
    assert entity.extra_state_attributes["media_identity_available"] is True

    asyncio.run(entity.async_turn_off())
    assert entry.runtime_data.api.device_user_actions == [
        "ensure:Home Assistant Test",
        "restore",
    ]
    assert entity.is_on is False
    assert entity.extra_state_attributes["media_identity_available"] is False
    assert repair_calls == ["repair", "diagnostics", "repair", "diagnostics"]


def test_homeassistant_media_user_setup_marks_unavailable_when_refresh_fails() -> None:
    entry = _FakeEntry()
    entry.runtime_data.api.device_user_status_error = True
    entity = C300XHomeAssistantMediaUserSetupSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False
    assert entity.is_on is None


def test_homeassistant_media_user_setup_translates_agent_errors() -> None:
    entry = _FakeEntry()
    entity = C300XHomeAssistantMediaUserSetupSwitch(entry)  # type: ignore[arg-type]
    entity.hass = SimpleNamespace(config=SimpleNamespace(location_name="Test"))

    async def unsupported_ensure(*, account_label: str | None = None) -> dict[str, Any]:
        _ = account_label
        raise C300XAgentApiUnsupportedError("unsupported")

    async def failed_restore() -> dict[str, Any]:
        raise C300XAgentApiConnectionError("offline")

    entry.runtime_data.api.async_ensure_homeassistant_user = unsupported_ensure  # type: ignore[method-assign]
    with pytest.raises(Exception, match="does not support device-user setup"):
        asyncio.run(entity.async_turn_on())

    entry.runtime_data.api.async_restore_homeassistant_media_user_setup = failed_restore  # type: ignore[method-assign]
    with pytest.raises(Exception, match="media user restore failed"):
        asyncio.run(entity.async_turn_off())


def test_gui_function_patch_switch_uses_read_only_status() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "qml_status": True,
                    "qml_patch": True,
                    "qml_restore": True,
                }
            },
        )
    )
    entity = C300XGuiFunctionPatchSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entry.runtime_data.api.qml_patch_status_reads == 1
    assert entry.runtime_data.api.qml_patch_actions == []
    assert entity.is_on is False
    assert entity.extra_state_attributes["state"] == "original"


def test_gui_function_patch_switch_applies_and_restores_patch() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "qml_status": True,
                    "qml_patch": True,
                    "qml_restore": True,
                }
            },
        )
    )
    entity = C300XGuiFunctionPatchSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_turn_on())
    asyncio.run(entity.async_turn_off())

    assert entry.runtime_data.api.qml_patch_actions == ["apply", "restore"]
    assert entry.runtime_data.qml_patch_status["state"] == "original"
    assert entity.is_on is False


def test_gui_function_patch_switch_marks_unavailable_when_refresh_fails() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "qml_status": True,
                    "qml_patch": True,
                    "qml_restore": True,
                }
            },
        )
    )
    entry.runtime_data.api.qml_patch_status_error = True
    entity = C300XGuiFunctionPatchSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False


def test_gui_function_patch_dispatch_is_noop_without_hass() -> None:
    entity = C300XGuiFunctionPatchSwitch(_FakeEntry())  # type: ignore[arg-type]

    entity._dispatch_qml_patch_changed()

    assert not getattr(entity, "wrote_state", False)


def test_gui_function_patch_dispatch_sends_entry_signal_when_hass_is_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, str, str]] = []
    monkeypatch.setattr(
        "custom_components.bticino_c300x.switch.async_dispatcher_send",
        lambda hass, signal, entry_id: calls.append((hass, signal, entry_id)),
    )
    entity = C300XGuiFunctionPatchSwitch(_FakeEntry())  # type: ignore[arg-type]
    entity.hass = SimpleNamespace()

    entity._dispatch_qml_patch_changed()

    assert calls == [(entity.hass, "bticino_c300x_qml_patch_changed", "entry-1")]


def test_gui_function_patch_push_updates_matching_entry_only() -> None:
    entry = _FakeEntry()
    entity = C300XGuiFunctionPatchSwitch(entry)  # type: ignore[arg-type]

    entity._handle_qml_patch_changed("other")
    assert entity.is_on is None

    entry.runtime_data.qml_patch_status = {"available": True, "patched": True}
    entity._handle_qml_patch_changed("entry-1")

    assert entity.is_on is True
    assert getattr(entity, "wrote_state", False) is True


def test_firewall_patch_switch_uses_read_only_status() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "firewall_status": True,
                    "firewall_apply": True,
                    "firewall_restore": True,
                }
            },
        )
    )
    entity = C300XFirewallPatchSwitch(entry)  # type: ignore[arg-type]

    assert entity._attr_entity_registry_enabled_default is False
    asyncio.run(entity.async_update())

    assert entry.runtime_data.api.firewall_status_reads == 1
    assert entry.runtime_data.api.firewall_actions == []
    assert entity.is_on is False
    assert entity.extra_state_attributes["family"] == "ipv4"


def test_firewall_patch_switch_applies_and_restores_patch() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "firewall_status": True,
                    "firewall_apply": True,
                    "firewall_restore": True,
                }
            },
        )
    )
    entity = C300XFirewallPatchSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_turn_on())
    asyncio.run(entity.async_turn_off())

    assert entry.runtime_data.api.firewall_actions == ["apply", "restore"]
    assert entity.is_on is False
    assert entity.extra_state_attributes["state"] == "original"


def test_firewall_patch_switch_exists_before_endpoint_is_enabled() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entry.runtime_data.api.firewall_supported = False
    entry.runtime_data.api.firewall_config_enabled = False
    entities: list[Any] = []

    asyncio.run(async_setup_entry(None, entry, entities.extend))  # type: ignore[arg-type]

    entity = next(item for item in entities if isinstance(item, C300XFirewallPatchSwitch))
    assert entity.is_on is False
    assert entity.extra_state_attributes["state"] == "disabled"

    asyncio.run(entity.async_turn_on())

    assert entry.runtime_data.api.firewall_enable_sets == [True]
    assert entry.runtime_data.api.firewall_actions == ["apply"]
    assert entity.is_on is True


def test_firewall_patch_switch_recovers_when_maintenance_is_disabled() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entry.runtime_data.api.maintenance_config_enabled = False
    entities: list[Any] = []

    asyncio.run(async_setup_entry(None, entry, entities.extend))  # type: ignore[arg-type]

    entity = next(item for item in entities if isinstance(item, C300XFirewallPatchSwitch))
    assert entity.available is True
    assert entity.is_on is False
    assert entity.extra_state_attributes["state"] == "disabled"

    asyncio.run(entity.async_turn_on())

    assert entry.runtime_data.api.firewall_enable_sets == [True]
    assert entry.runtime_data.api.firewall_actions == ["apply"]
    assert entity.is_on is True


def test_firewall_patch_switch_marks_unavailable_when_endpoint_is_unsupported() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "firewall_status": True,
                    "firewall_apply": True,
                    "firewall_restore": True,
                }
            },
        )
    )
    entry.runtime_data.api.firewall_supported = False
    entity = C300XFirewallPatchSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False


def test_firewall_patch_switch_marks_unavailable_when_status_fails() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "firewall_status": True,
                    "firewall_apply": True,
                    "firewall_restore": True,
                }
            },
        )
    )
    entry.runtime_data.api.maintenance_config_enabled = False
    entity = C300XFirewallPatchSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False


def test_firewall_disabled_check_is_false_when_auth_status_fails() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entry.runtime_data.api.auth_config_error = True
    entity = C300XFirewallPatchSwitch(entry)  # type: ignore[arg-type]

    assert asyncio.run(entity._async_configured_endpoint_disabled()) is False


def test_ipv6_firewall_patch_switch_uses_read_only_status() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "ipv6_firewall_status": True,
                    "ipv6_firewall_apply": True,
                    "ipv6_firewall_restore": True,
                }
            },
        )
    )
    entity = C300XIpv6FirewallPatchSwitch(entry)  # type: ignore[arg-type]

    assert entity._attr_entity_registry_enabled_default is False
    asyncio.run(entity.async_update())

    assert entry.runtime_data.api.ipv6_firewall_status_reads == 1
    assert entry.runtime_data.api.ipv6_firewall_actions == []
    assert entity.is_on is False
    assert entity.extra_state_attributes["family"] == "ipv6"


def test_ipv6_firewall_patch_switch_applies_and_restores_patch() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "ipv6_firewall_status": True,
                    "ipv6_firewall_apply": True,
                    "ipv6_firewall_restore": True,
                }
            },
        )
    )
    entity = C300XIpv6FirewallPatchSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_turn_on())
    asyncio.run(entity.async_turn_off())

    assert entry.runtime_data.api.ipv6_firewall_actions == ["apply", "restore"]
    assert entity.is_on is False
    assert entity.extra_state_attributes["state"] == "original"


def test_ipv6_firewall_patch_switch_exists_before_endpoint_is_enabled() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entry.runtime_data.api.ipv6_firewall_supported = False
    entry.runtime_data.api.ipv6_firewall_config_enabled = False
    entities: list[Any] = []

    asyncio.run(async_setup_entry(None, entry, entities.extend))  # type: ignore[arg-type]

    entity = next(
        item for item in entities if isinstance(item, C300XIpv6FirewallPatchSwitch)
    )
    assert entity.is_on is False
    assert entity.extra_state_attributes["state"] == "disabled"

    asyncio.run(entity.async_turn_on())

    assert entry.runtime_data.api.ipv6_firewall_enable_sets == [True]
    assert entry.runtime_data.api.ipv6_firewall_actions == ["apply"]
    assert entity.is_on is True


def test_ipv6_firewall_patch_switch_recovers_when_maintenance_is_disabled() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entry.runtime_data.api.maintenance_config_enabled = False
    entities: list[Any] = []

    asyncio.run(async_setup_entry(None, entry, entities.extend))  # type: ignore[arg-type]

    entity = next(
        item for item in entities if isinstance(item, C300XIpv6FirewallPatchSwitch)
    )
    assert entity.available is True
    assert entity.is_on is False
    assert entity.extra_state_attributes["state"] == "disabled"

    asyncio.run(entity.async_turn_on())

    assert entry.runtime_data.api.ipv6_firewall_enable_sets == [True]
    assert entry.runtime_data.api.ipv6_firewall_actions == ["apply"]
    assert entity.is_on is True


def test_ipv6_firewall_patch_switch_marks_unavailable_when_endpoint_is_unsupported() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "ipv6_firewall_status": True,
                    "ipv6_firewall_apply": True,
                    "ipv6_firewall_restore": True,
                }
            },
        )
    )
    entry.runtime_data.api.ipv6_firewall_supported = False
    entity = C300XIpv6FirewallPatchSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False


def test_ipv6_firewall_patch_switch_marks_unavailable_when_status_fails() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "ipv6_firewall_status": True,
                    "ipv6_firewall_apply": True,
                    "ipv6_firewall_restore": True,
                }
            },
        )
    )
    entry.runtime_data.api.maintenance_config_enabled = False
    entity = C300XIpv6FirewallPatchSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False


def test_ipv6_firewall_disabled_check_is_false_when_auth_status_fails() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entry.runtime_data.api.auth_config_error = True
    entity = C300XIpv6FirewallPatchSwitch(entry)  # type: ignore[arg-type]

    assert asyncio.run(entity._async_configured_endpoint_disabled()) is False


def test_native_mqtt_bridge_switch_uses_read_only_status_and_toggles() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "mqtt_status": True,
                    "mqtt_config": True,
                }
            },
        )
    )
    entity = C300XNativeMqttBridgeSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())
    asyncio.run(entity.async_turn_on())
    asyncio.run(entity.async_turn_off())

    assert entry.runtime_data.api.mqtt_status_reads == 3
    assert entry.runtime_data.api.mqtt_enabled_sets == [True, False]
    assert entity.is_on is False
    assert entity.extra_state_attributes["configured"] is True
    assert entity.extra_state_attributes["connected"] is False
    assert entity.extra_state_attributes["event_topic"] == "Bticino/tx"


def test_native_mqtt_bridge_switch_clears_stale_on_state_when_offline() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "mqtt_status": True,
                    "mqtt_config": True,
                }
            },
        )
    )
    entry.runtime_data.api.mqtt_enabled = True
    entity = C300XNativeMqttBridgeSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())
    assert entity.available is True
    assert entity.is_on is True

    entry.runtime_data.api.mqtt_status_error = True
    asyncio.run(entity.async_update())

    assert entity.available is False
    assert entity.is_on is False
    assert entity.extra_state_attributes["connected"] is None


def test_legacy_mqtt_bridge_switch_disables_and_enables_autostart() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "legacy_mqtt_status": True,
                    "legacy_mqtt_config": True,
                }
            },
        )
    )
    entity = C300XLegacyMqttBridgeSwitch(entry)  # type: ignore[arg-type]

    assert entity._attr_entity_registry_enabled_default is False
    asyncio.run(entity.async_update())
    asyncio.run(entity.async_turn_off())
    asyncio.run(entity.async_turn_on())

    assert entry.runtime_data.api.legacy_mqtt_status_reads == 3
    assert entry.runtime_data.api.legacy_mqtt_enabled_sets == [False, True]
    assert entity.is_on is True
    assert entity.extra_state_attributes["backup_available"] is True
    assert entity.extra_state_attributes["script_path"] == (
        "/etc/tcpdump2mqtt/TcpDump2Mqtt.sh"
    )
    assert entity.extra_state_attributes["flexisip_reference_state"] == (
        "legacy_mqtt_patch"
    )


def test_legacy_mqtt_bridge_switch_is_off_when_native_bridge_is_exclusive() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "legacy_mqtt_status": True,
                    "legacy_mqtt_config": True,
                }
            },
        )
    )
    entry.runtime_data.api.mqtt_enabled = True
    entry.runtime_data.api.legacy_mqtt_enabled = True
    entity = C300XLegacyMqttBridgeSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.is_on is False
    assert entity.extra_state_attributes["native_enabled"] is True
    assert entity.extra_state_attributes["running"] is True


def test_legacy_mqtt_bridge_switch_clears_stale_on_state_when_offline() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "legacy_mqtt_status": True,
                    "legacy_mqtt_config": True,
                }
            },
        )
    )
    entry.runtime_data.api.legacy_mqtt_enabled = True
    entity = C300XLegacyMqttBridgeSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())
    assert entity.available is True
    assert entity.is_on is True

    entry.runtime_data.api.legacy_mqtt_status_error = True
    asyncio.run(entity.async_update())

    assert entity.available is False
    assert entity.is_on is False
    assert entity.extra_state_attributes["running"] is None


def test_maintenance_switches_are_created_without_capabilities_but_do_not_refresh() -> None:
    entry = _FakeEntry()
    entities: list[Any] = []

    asyncio.run(async_setup_entry(None, entry, entities.extend))  # type: ignore[arg-type]

    maintenance_entities = {
        type(item): item
        for item in entities
        if isinstance(
            item,
            (
                C300XFirewallPatchSwitch,
                C300XGuiFunctionPatchSwitch,
                C300XIpv6FirewallPatchSwitch,
                C300XLegacyMqttBridgeSwitch,
                C300XMaintenanceNoAuthSwitch,
                C300XMaintenanceSshSwitch,
                C300XMdnsDiscoverySwitch,
                C300XNativeMqttBridgeSwitch,
                C300XNoAuthSwitch,
            ),
        )
    }
    assert set(maintenance_entities) == {
        C300XFirewallPatchSwitch,
        C300XGuiFunctionPatchSwitch,
        C300XIpv6FirewallPatchSwitch,
        C300XLegacyMqttBridgeSwitch,
        C300XMaintenanceNoAuthSwitch,
        C300XMaintenanceSshSwitch,
        C300XMdnsDiscoverySwitch,
        C300XNativeMqttBridgeSwitch,
        C300XNoAuthSwitch,
    }
    assert all(not entity.available for entity in maintenance_entities.values())
    assert entry.runtime_data.api.auth_config_reads == 0
    assert entry.runtime_data.api.ssh_reads == 0
    assert entry.runtime_data.api.qml_patch_status_reads == 0
    assert entry.runtime_data.api.firewall_status_reads == 0
    assert entry.runtime_data.api.ipv6_firewall_status_reads == 0
    assert entry.runtime_data.api.mqtt_status_reads == 0
    assert entry.runtime_data.api.legacy_mqtt_status_reads == 0


def test_no_auth_switch_refreshes_bootstrap_state() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entity = C300XNoAuthSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entry.runtime_data.api.auth_config_reads == 1
    assert entity.is_on is True
    assert entity.extra_state_attributes == {
        "api_token_configured": False,
        "maintenance_token_configured": True,
        "maintenance_no_auth_allowed": False,
    }


def test_no_auth_switch_disables_bootstrap_mode() -> None:
    entry = _FakeEntry(
        data={
            "agent_token": "configured-agent-token",
            "maintenance_token": "configured-maintenance-token",
        }
    )
    entity = C300XNoAuthSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_turn_off())

    assert entry.runtime_data.api.no_auth_sets == [
        (False, "configured-agent-token", "configured-maintenance-token", False)
    ]
    assert entity.is_on is False
    assert entity.extra_state_attributes["maintenance_no_auth_allowed"] is False


def test_no_auth_switch_enables_bootstrap_mode_without_tokens() -> None:
    entry = _FakeEntry(
        data={
            "agent_token": "configured-agent-token",
            "maintenance_token": "configured-maintenance-token",
        }
    )
    entity = C300XNoAuthSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_turn_on())

    assert entry.runtime_data.api.no_auth_sets == [(True, None, None, None)]
    assert entity.is_on is True


def test_no_auth_switch_marks_unavailable_when_refresh_fails() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entry.runtime_data.api.auth_config_error = True
    entity = C300XNoAuthSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False


def test_mdns_discovery_switch_updates_bootstrap_config() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entity = C300XMdnsDiscoverySwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())
    asyncio.run(entity.async_turn_off())

    assert entity.is_on is False
    assert entity._attr_entity_registry_enabled_default is False
    assert entry.runtime_data.api.auth_config_reads == 1
    assert entry.runtime_data.api.mdns_sets == [False]


def test_mdns_discovery_switch_enables_bootstrap_discovery() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entity = C300XMdnsDiscoverySwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_turn_on())

    assert entity.is_on is True
    assert entry.runtime_data.api.mdns_sets == [True]


def test_mdns_discovery_switch_marks_unavailable_when_refresh_fails() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entry.runtime_data.api.auth_config_error = True
    entity = C300XMdnsDiscoverySwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False


def test_maintenance_no_auth_switch_updates_bootstrap_config() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entity = C300XMaintenanceNoAuthSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())
    asyncio.run(entity.async_turn_on())

    assert entity.is_on is True
    assert entity.extra_state_attributes == {"no_auth": True}
    assert entry.runtime_data.api.auth_config_reads == 1
    assert entry.runtime_data.api.maintenance_no_auth_sets == [True]


def test_maintenance_no_auth_switch_disables_bootstrap_access() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entity = C300XMaintenanceNoAuthSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_turn_off())

    assert entity.is_on is False
    assert entry.runtime_data.api.maintenance_no_auth_sets == [False]


def test_maintenance_no_auth_switch_marks_unavailable_when_refresh_fails() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entry.runtime_data.api.auth_config_error = True
    entity = C300XMaintenanceNoAuthSwitch(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False


def test_auth_config_switches_share_initial_refresh() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    no_auth = C300XNoAuthSwitch(entry)  # type: ignore[arg-type]
    maintenance_no_auth = C300XMaintenanceNoAuthSwitch(entry)  # type: ignore[arg-type]
    mdns = C300XMdnsDiscoverySwitch(entry)  # type: ignore[arg-type]

    asyncio.run(
        _async_refresh_initial_states(
            [no_auth, maintenance_no_auth, mdns]  # type: ignore[list-item]
        )
    )

    assert entry.runtime_data.api.auth_config_reads == 1
    assert no_auth.is_on is True
    assert maintenance_no_auth.is_on is False
    assert mdns.is_on is True


def test_auth_config_initial_refresh_marks_all_unavailable_on_error() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entry.runtime_data.api.auth_config_error = True
    no_auth = C300XNoAuthSwitch(entry)  # type: ignore[arg-type]
    maintenance_no_auth = C300XMaintenanceNoAuthSwitch(entry)  # type: ignore[arg-type]
    mdns = C300XMdnsDiscoverySwitch(entry)  # type: ignore[arg-type]

    asyncio.run(
        _async_refresh_initial_states(
            [no_auth, maintenance_no_auth, mdns]  # type: ignore[list-item]
        )
    )

    assert no_auth.available is False
    assert maintenance_no_auth.available is False
    assert mdns.available is False


def test_auth_config_push_updates_matching_switch_only() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"auth": {"supported": True, "configurable": True}},
        )
    )
    entity = C300XMdnsDiscoverySwitch(entry)  # type: ignore[arg-type]

    entity._handle_auth_config_status(
        "other",
        {"mdns_enabled": False},
    )
    assert entity.is_on is None

    entity._handle_auth_config_status(
        "entry-1",
        {"mdns_enabled": False},
    )

    assert entity.is_on is False
    assert getattr(entity, "wrote_state", False) is True


def test_mqtt_push_updates_matching_native_and_legacy_switches() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={
                "maintenance": {
                    "supported": True,
                    "mqtt_status": True,
                    "mqtt_config": True,
                    "legacy_mqtt_status": True,
                    "legacy_mqtt_config": True,
                }
            },
        )
    )
    native = C300XNativeMqttBridgeSwitch(entry)  # type: ignore[arg-type]
    legacy = C300XLegacyMqttBridgeSwitch(entry)  # type: ignore[arg-type]

    native._handle_mqtt_status("other", {"native_enabled": True})
    legacy._handle_mqtt_status("other", {"legacy_enabled": True})
    assert native.is_on is None
    assert legacy.is_on is None

    native._handle_mqtt_status("entry-1", {"native_enabled": True})
    legacy._handle_mqtt_status(
        "entry-1",
        {
            "legacy_enabled": True,
            "legacy_installed": True,
            "native_enabled": False,
            "exclusive": True,
        },
    )

    assert native.is_on is True
    assert legacy.is_on is True
