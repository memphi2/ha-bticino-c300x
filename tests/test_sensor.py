# ruff: noqa: E402

from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field
from typing import Any

dispatcher_signals: list[tuple[str, str]] = []

if "homeassistant.components.sensor" not in sys.modules:
    homeassistant = sys.modules.setdefault(
        "homeassistant",
        types.ModuleType("homeassistant"),
    )
    components = sys.modules.setdefault(
        "homeassistant.components",
        types.ModuleType("homeassistant.components"),
    )
    sensor = types.ModuleType("homeassistant.components.sensor")
    config_entries = sys.modules.setdefault(
        "homeassistant.config_entries",
        types.ModuleType("homeassistant.config_entries"),
    )
    const = sys.modules.setdefault(
        "homeassistant.const",
        types.ModuleType("homeassistant.const"),
    )
    core = sys.modules.setdefault(
        "homeassistant.core",
        types.ModuleType("homeassistant.core"),
    )
    helpers = sys.modules.setdefault(
        "homeassistant.helpers",
        types.ModuleType("homeassistant.helpers"),
    )
    config_validation = types.ModuleType("homeassistant.helpers.config_validation")
    dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
    event_helper = types.ModuleType("homeassistant.helpers.event")
    issue_registry = types.ModuleType("homeassistant.helpers.issue_registry")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    entity = sys.modules.setdefault(
        "homeassistant.helpers.entity",
        types.ModuleType("homeassistant.helpers.entity"),
    )
    entity_platform = sys.modules.setdefault(
        "homeassistant.helpers.entity_platform",
        types.ModuleType("homeassistant.helpers.entity_platform"),
    )

    class SensorEntity:  # pragma: no cover - import-time stub only
        def async_write_ha_state(self) -> None:
            self.wrote_state = True

        def async_on_remove(self, callback: Any) -> None:
            self._remove_callback = callback

    class SensorDeviceClass:  # pragma: no cover - import-time stub only
        ENUM = "enum"
        TIMESTAMP = "timestamp"
        TEMPERATURE = "temperature"
        DURATION = "duration"

    class SensorStateClass:  # pragma: no cover - import-time stub only
        MEASUREMENT = "measurement"
        TOTAL_INCREASING = "total_increasing"

    class ConfigEntry:  # pragma: no cover - import-time stub only
        pass

    class HomeAssistant:  # pragma: no cover - import-time stub only
        pass

    class Entity:  # pragma: no cover - import-time stub only
        pass

    class DeviceInfo(dict):  # pragma: no cover - import-time stub only
        pass

    class EntityCategory:  # pragma: no cover - import-time stub only
        DIAGNOSTIC = "diagnostic"

    class UnitOfTemperature:  # pragma: no cover - import-time stub only
        CELSIUS = "°C"

    class UnitOfTime:  # pragma: no cover - import-time stub only
        SECONDS = "s"

    const.PERCENTAGE = "%"
    config_validation.config_entry_only_config_schema = lambda _domain: dict
    issue_registry.IssueSeverity = types.SimpleNamespace(ERROR="error", WARNING="warning")
    issue_registry.async_create_issue = lambda **kwargs: None
    issue_registry.async_delete_issue = lambda **kwargs: None
    entity_registry.async_get = lambda hass: types.SimpleNamespace(
        async_get=lambda entity_id: None
    )
    sensor.SensorEntity = SensorEntity
    sensor.SensorDeviceClass = SensorDeviceClass
    sensor.SensorStateClass = SensorStateClass
    config_entries.ConfigEntry = ConfigEntry
    const.EntityCategory = EntityCategory
    const.UnitOfTemperature = UnitOfTemperature
    const.UnitOfTime = UnitOfTime
    core.HomeAssistant = HomeAssistant
    core.callback = lambda func: func
    dispatcher.async_dispatcher_connect = lambda *args, **kwargs: lambda: None
    dispatcher.async_dispatcher_send = (
        lambda hass, signal, entry_id: dispatcher_signals.append((signal, entry_id))
    )
    event_helper.async_call_later = lambda *args, **kwargs: (lambda: None)
    entity.Entity = Entity
    entity.DeviceInfo = DeviceInfo
    entity_platform.AddEntitiesCallback = object
    helpers.dispatcher = dispatcher
    helpers.config_validation = config_validation
    helpers.event = event_helper
    helpers.issue_registry = issue_registry
    helpers.entity_registry = entity_registry
    helpers.entity = entity
    helpers.entity_platform = entity_platform
    components.sensor = sensor
    homeassistant.components = components
    sys.modules["homeassistant.components.sensor"] = sensor
    sys.modules["homeassistant.helpers.config_validation"] = config_validation
    sys.modules["homeassistant.helpers.dispatcher"] = dispatcher
    sys.modules["homeassistant.helpers.event"] = event_helper
    sys.modules["homeassistant.helpers.issue_registry"] = issue_registry
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry

from custom_components.bticino_c300x import agent_diagnostics
from custom_components.bticino_c300x.const import (
    SIGNAL_AGENT_DIAGNOSTICS_CHANGED,
)
from custom_components.bticino_c300x.doorbell_state import normalize_doorbell_state
from custom_components.bticino_c300x.sensor import (
    C300XAgentDiagnosticsSensor,
    C300XAgentStatusSensor,
    C300XDeviceCpuSensor,
    C300XDeviceLoadSensor,
    C300XDeviceMemorySensor,
    C300XDeviceTemperatureSensor,
    C300XDoorbellStateSensor,
    C300XTextMemosSensor,
    C300XVoicemailMessagesSensor,
    C300XVoiceMemosSensor,
    _agent_diagnostics_status,
)
from custom_components.bticino_c300x.sensor import (
    async_setup_entry as async_setup_sensor_entry,
)


class _FakeApi:
    def __init__(self) -> None:
        self.metrics_calls = 0
        self.answering_machine_messages_calls = 0
        self.memos_calls = 0
        self.diagnostics_calls = 0
        self.doorbell_video_status_calls = 0
        self.doorbell_video_status: dict[str, Any] = {
            "available": True,
            "media_owner": "idle",
            "window_available": False,
            "external_media_active": False,
            "bridge": {"clients": 0},
        }

    async def async_system_metrics(self) -> dict[str, Any]:
        self.metrics_calls += 1
        return {
            "cpu_count": 2,
            "cpu_usage_percent": 3.5,
            "load_1m": 0.11,
            "load_5m": 0.22,
            "load_15m": 0.33,
            "load_1m_percent": 5.5,
            "load_5m_percent": 11.0,
            "load_15m_percent": 16.5,
            "memory_total_kb": 262144,
            "memory_available_kb": 196608,
            "memory_used_kb": 65536,
            "memory_usage_percent": 25.0,
            "temperature_c": 40.0,
            "temperature_source": "sysfs",
            "raw": {},
        }

    async def async_memos(self) -> dict[str, Any]:
        self.memos_calls += 1
        return {
            "available": True,
            "total": 2,
            "text_total": 1,
            "voice_total": 1,
            "unread": 1,
            "read": 1,
            "newest_at": "2024-03-09T16:02:02Z",
            "memos": [
                {
                    "id": "text/memo_1",
                    "kind": "text",
                    "read": False,
                    "iso_time": "2024-03-09T16:02:01Z",
                    "has_text": True,
                    "has_audio": False,
                    "text": "local memo",
                    "text_truncated": False,
                },
                {
                    "id": "voice/memo_1",
                    "kind": "voice",
                    "read": True,
                    "iso_time": "2024-03-09T16:02:02Z",
                    "has_text": False,
                    "has_audio": True,
                    "text": None,
                    "text_truncated": False,
                },
            ],
            "raw": {},
        }

    async def async_answering_machine_messages(self) -> dict[str, Any]:
        self.answering_machine_messages_calls += 1
        return {
            "available": True,
            "total": 1,
            "unread": 1,
            "read": 0,
            "newest_at": "2024-03-09T16:02:02Z",
            "messages": [
                {
                    "id": "message_1",
                    "read": False,
                    "unix_time": 1710000122,
                    "iso_time": "2024-03-09T16:02:02Z",
                    "has_video": True,
                    "media_mime_type": "video/x-msvideo",
                    "media_size": 12,
                },
            ],
            "raw": {},
        }

    async def async_validate_setup(self) -> dict[str, Any]:
        return {
            "version": "0.2.0",
            "implementation": "native-c",
            "api_version": "1",
            "model": "C300X",
            "firmware": "1.7.19",
            "capabilities": {},
        }

    async def async_diagnostics(self) -> dict[str, Any]:
        self.diagnostics_calls += 1
        return {
            "agent_write_count": 2,
            "last_write_at": 1770000000,
            "last_write_reason": "updated",
            "last_write_class": "config",
            "qml_patch_last_action": "apply",
            "loop_iterations": 10,
            "poll_wakeups": 4,
            "accepted_clients": 3,
            "last_wake_reason": "api",
            "last_poll_timeout_ms": 5000,
            "last_poll_count": 6,
            "open_fd_count": 9,
            "agent_init_script_present": True,
            "agent_init_link_ok": True,
            "subscription_count": 1,
            "recent_event_count": 4,
            "recent_event_capacity": 16,
            "display_bridge_registered": True,
            "display_bridge_disabled": False,
            "home_assistant_connected_this_run": True,
            "home_assistant_last_seen_at": 1770000010,
            "ui_event_revision": 7,
            "video_running": False,
            "video_rtsp_server_running": True,
            "video_media_starting": False,
            "video_call_active": False,
            "video_clients": 0,
            "video_bridge_running": True,
            "video_bridge_media_active": False,
            "video_bridge_stop_in_progress": False,
            "video_bridge_open_fds": 1,
            "video_bridge_active_threads": 1,
            "ring_receiver_running": False,
            "ring_registered": False,
            "ring_call_active": False,
            "ring_media_active": False,
            "home_call_running": False,
            "home_call_active": False,
            "raw": {},
        }

    async def async_state(self) -> dict[str, Any]:
        return {"doorbell": "view_requested"}

    async def async_doorbell_video_status(self) -> dict[str, Any]:
        self.doorbell_video_status_calls += 1
        return self.doorbell_video_status


class _FakeHass:
    data: dict[str, Any] = {}

    def __init__(self) -> None:
        self.bus = types.SimpleNamespace(async_listen=lambda *_args: (lambda: None))

    def async_create_task(self, coro: Any) -> asyncio.Task[Any]:
        return asyncio.create_task(coro)

    def verify_event_loop_thread(self, _what: str) -> None:
        return


@dataclass
class _FakeConnectionState:
    available: bool = True
    connection_state: str = "connected"
    reconnect_count: int = 0
    last_connection_stage: str | None = None
    last_reconnect_reason: str | None = None
    last_connection_error: str | None = None
    next_reconnect_delay_seconds: int | None = None


@dataclass
class _FakeRuntimeData:
    api: _FakeApi = field(default_factory=_FakeApi)
    event_state: Any = field(default_factory=types.SimpleNamespace)
    capabilities: dict[str, Any] = field(default_factory=dict)
    agent_info: dict[str, Any] = field(
        default_factory=lambda: {
            "version": "0.2.0",
            "implementation": "native-c",
            "api_version": "1",
            "model": "C300X",
        }
    )
    connection_state: _FakeConnectionState = field(default_factory=_FakeConnectionState)
    system_metrics: dict[str, Any] = field(default_factory=dict)
    system_metrics_updated_at: Any = None
    answering_machine_messages: dict[str, Any] = field(default_factory=dict)
    answering_machine_messages_updated_at: Any = None
    answering_machine_messages_refresh_task: asyncio.Task[Any] | None = None
    memos: dict[str, Any] = field(default_factory=dict)
    memos_updated_at: Any = None
    memos_refresh_task: asyncio.Task[Any] | None = None
    agent_diagnostics: dict[str, Any] = field(default_factory=dict)
    agent_diagnostics_updated_at: Any = None
    agent_diagnostics_updated_by: str | None = None
    agent_diagnostics_change_reason: str | None = None
    agent_update_state: Any = None


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    runtime_data: _FakeRuntimeData = field(default_factory=_FakeRuntimeData)


async def _drain_tasks() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def test_agent_status_sensor_reports_ok_with_safe_context() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            agent_diagnostics={
                "agent_write_count": 2,
                "last_write_at": 1770000000,
                "last_write_reason": "updated",
                "last_write_class": "config",
                "last_wake_reason": "api",
                "loop_iterations": 10,
                "poll_wakeups": 4,
                "last_poll_timeout_ms": 5000,
                "last_poll_count": 6,
                "open_fd_count": 9,
                "agent_init_script_present": True,
                "agent_init_link_ok": True,
                "subscription_count": 1,
                "recent_event_count": 4,
                "recent_event_capacity": 16,
                "display_bridge_registered": True,
                "display_bridge_disabled": False,
                "home_assistant_connected_this_run": True,
                "home_assistant_last_seen_at": 1770000010,
                "ui_event_revision": 7,
                "flexisip_backup_available": True,
                "flexisip_restart_marker": True,
                "flexisip_backup_marker": False,
                "flexisip_reference_state": "legacy_mqtt_patch",
            },
        )
    )
    entity = C300XAgentStatusSensor(entry)  # type: ignore[arg-type]

    assert entity.available is True
    assert entity.native_value == "ok"
    assert entity.extra_state_attributes == {
        "reason": "agent_ok",
        "agent_version": "0.2.0",
        "api_version": "1",
        "model": "C300X",
        "connection_state": "connected",
        "last_connection_stage": None,
        "last_connection_error": None,
        "last_reconnect_reason": None,
        "next_reconnect_delay_seconds": None,
        "reconnect_count": 0,
        "media_watchdog_trigger_count": 0,
    }


def test_agent_status_sensor_reports_media_watchdog_trigger_count() -> None:
    entry = _FakeEntry()
    entry.runtime_data.agent_cpu_watchdog = types.SimpleNamespace(trigger_count=3)
    entity = C300XAgentStatusSensor(entry)  # type: ignore[arg-type]

    assert entity.extra_state_attributes["media_watchdog_trigger_count"] == 3


def test_agent_diagnostics_sensor_reports_disabled_detailed_context() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            agent_diagnostics={
                "agent_write_count": 2,
                "last_write_at": 1770000000,
                "last_write_reason": "updated",
                "last_write_class": "config",
                "last_wake_reason": "api",
                "loop_iterations": 10,
                "poll_wakeups": 4,
                "last_poll_timeout_ms": 5000,
                "last_poll_count": 6,
                "open_fd_count": 9,
                "agent_init_script_present": True,
                "agent_init_link_ok": True,
                "subscription_count": 1,
                "recent_event_count": 4,
                "recent_event_capacity": 16,
                "display_bridge_registered": True,
                "display_bridge_disabled": False,
                "home_assistant_connected_this_run": True,
                "home_assistant_last_seen_at": 1770000010,
                "ui_event_revision": 7,
                "video_running": False,
                "video_rtsp_server_running": True,
                "video_media_starting": True,
                "video_call_active": True,
                "video_clients": 1,
                "video_bridge_running": True,
                "video_bridge_media_active": True,
                "video_bridge_stop_in_progress": False,
                "video_bridge_open_fds": 2,
                "video_bridge_active_threads": 1,
                "ring_receiver_running": True,
                "ring_registered": True,
                "ring_call_active": False,
                "ring_media_active": False,
                "home_call_running": False,
                "home_call_active": False,
                "flexisip_backup_available": True,
                "flexisip_restart_marker": True,
                "flexisip_backup_marker": False,
                "flexisip_reference_state": "legacy_mqtt_patch",
            },
        )
    )
    entity = C300XAgentDiagnosticsSensor(entry)  # type: ignore[arg-type]

    assert entity._attr_entity_registry_enabled_default is False
    assert entity._attr_device_class == "enum"
    assert entity.native_value == "doorbell_call_active"
    assert entity.extra_state_attributes == {
        "status_reason": "native_doorbell_call_active",
        "recommended_action": "use_doorstation_card_stop_when_finished",
        "change_reason": None,
        "updated_at": None,
        "updated_by": None,
        "agent_write_count": 2,
        "last_write_at": 1770000000,
        "last_write_reason": "updated",
        "last_write_class": "config",
        "qml_patch_last_action": None,
        "media_watchdog_trigger_count": 0,
        "media_watchdog_last_reason": None,
        "media_watchdog_last_percent": None,
        "last_wake_reason": "api",
        "loop_iterations": 10,
        "poll_wakeups": 4,
        "poll_wakeups_per_loop": 0.4,
        "last_poll_timeout_ms": 5000,
        "last_poll_count": 6,
        "accepted_clients": None,
        "open_fd_count": 9,
        "agent_init_script_present": True,
        "agent_init_link_ok": True,
        "subscription_count": 1,
        "recent_event_count": 4,
        "recent_event_capacity": 16,
        "display_bridge_registered": True,
        "display_bridge_disabled": False,
        "home_assistant_connected_this_run": True,
        "home_assistant_last_seen_at": 1770000010,
        "ui_event_revision": 7,
        "ui_event_waiters": None,
        "ui_event_waiter_capacity": None,
        "ui_event_waiter_overflows": None,
        "video_running": False,
        "video_rtsp_server_running": True,
        "video_media_starting": True,
        "video_call_active": True,
        "video_clients": 1,
        "video_bridge_running": True,
        "video_bridge_media_active": True,
        "video_bridge_stop_in_progress": False,
        "video_bridge_open_fds": 2,
        "video_bridge_active_threads": 1,
        "ring_receiver_running": True,
        "ring_registered": True,
        "ring_call_active": False,
        "ring_media_active": False,
        "home_call_running": False,
        "home_call_active": False,
        "flexisip_backup_available": True,
        "flexisip_restart_marker": True,
        "flexisip_backup_marker": False,
        "flexisip_reference_state": "legacy_mqtt_patch",
    }


def test_agent_diagnostics_sensor_reports_idle_despite_historical_writes() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            agent_diagnostics={
                "agent_write_count": 2,
                "last_write_at": 1770000000,
                "last_write_reason": "updated",
                "last_write_class": "config",
                "agent_init_script_present": True,
                "agent_init_link_ok": True,
                "subscription_count": 1,
                "home_assistant_connected_this_run": True,
                "video_clients": 0,
                "video_bridge_open_fds": 0,
                "video_bridge_active_threads": 0,
            },
        )
    )
    entity = C300XAgentDiagnosticsSensor(entry)  # type: ignore[arg-type]

    assert entity.native_value == "idle"
    assert entity.extra_state_attributes["status_reason"] == "native_agent_idle"
    assert entity.extra_state_attributes["recommended_action"] == "no_action_needed"
    assert entity.extra_state_attributes["agent_write_count"] == 2


def test_agent_diagnostics_sensor_reports_installation_and_subscription_issues() -> None:
    repair_entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            agent_diagnostics={
                "agent_init_script_present": False,
                "agent_init_link_ok": True,
                "subscription_count": 1,
                "home_assistant_connected_this_run": True,
            },
        )
    )
    repair_entity = C300XAgentDiagnosticsSensor(repair_entry)  # type: ignore[arg-type]

    assert repair_entity.native_value == "repair_required"
    assert repair_entity.extra_state_attributes["status_reason"] == (
        "agent_installation_needs_repair"
    )
    assert repair_entity.extra_state_attributes["recommended_action"] == (
        "run_device_agent_repair_or_update"
    )

    subscription_entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            agent_diagnostics={
                "agent_init_script_present": True,
                "agent_init_link_ok": True,
                "subscription_count": 0,
                "home_assistant_connected_this_run": True,
            },
        )
    )
    subscription_entity = C300XAgentDiagnosticsSensor(subscription_entry)  # type: ignore[arg-type]

    assert subscription_entity.native_value == "subscription_missing"
    assert subscription_entity.extra_state_attributes["status_reason"] == (
        "ha_event_subscription_missing"
    )
    assert subscription_entity.extra_state_attributes["recommended_action"] == (
        "reload_integration_after_agent_is_online"
    )


def test_agent_diagnostics_sensor_reports_connection_and_watchdog_state() -> None:
    offline_entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            connection_state=_FakeConnectionState(available=False),
            agent_diagnostics={
                "agent_init_script_present": True,
                "agent_init_link_ok": True,
                "subscription_count": 1,
                "home_assistant_connected_this_run": True,
            },
        )
    )
    offline_entity = C300XAgentDiagnosticsSensor(offline_entry)  # type: ignore[arg-type]

    assert offline_entity.native_value == "agent_offline"
    assert offline_entity.extra_state_attributes["status_reason"] == (
        "agent_connection_unavailable"
    )
    assert offline_entity.extra_state_attributes["recommended_action"] == (
        "check_agent_reachability_and_token"
    )

    watchdog_entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            agent_diagnostics={
                "agent_init_script_present": True,
                "agent_init_link_ok": True,
                "subscription_count": 1,
                "home_assistant_connected_this_run": True,
            },
        )
    )
    watchdog_entry.runtime_data.agent_cpu_watchdog = types.SimpleNamespace(
        tripped=True,
        trigger_count=2,
        last_reason="agent_cpu_high_95.0_percent_300s",
        last_percent=95.0,
    )
    watchdog_entity = C300XAgentDiagnosticsSensor(watchdog_entry)  # type: ignore[arg-type]

    assert watchdog_entity.native_value == "media_watchdog_tripped"
    assert watchdog_entity.extra_state_attributes["status_reason"] == (
        "sustained_high_cpu_media_watchdog"
    )
    assert watchdog_entity.extra_state_attributes["recommended_action"] == (
        "stop_live_media_reload_display_gui_and_check_device_load"
    )

    ui_event_entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            agent_diagnostics={
                "agent_init_script_present": True,
                "agent_init_link_ok": True,
                "subscription_count": 1,
                "home_assistant_connected_this_run": True,
                "ui_event_waiters": 4,
                "ui_event_waiter_capacity": 4,
                "ui_event_waiter_overflows": 1,
            },
        )
    )
    ui_event_entity = C300XAgentDiagnosticsSensor(ui_event_entry)  # type: ignore[arg-type]

    assert ui_event_entity.native_value == "display_event_watchdog"
    assert ui_event_entity.extra_state_attributes["status_reason"] == (
        "display_ui_event_watchdog_triggered"
    )
    assert ui_event_entity.extra_state_attributes["recommended_action"] == (
        "reload_c300x_display_gui_then_refresh_diagnostics"
    )
    assert watchdog_entity.extra_state_attributes["media_watchdog_trigger_count"] == 2
    assert watchdog_entity.extra_state_attributes["media_watchdog_last_percent"] == 95.0

    historical_ui_event_entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            agent_diagnostics={
                "agent_init_script_present": True,
                "agent_init_link_ok": True,
                "subscription_count": 1,
                "home_assistant_connected_this_run": True,
                "ui_event_waiters": 0,
                "ui_event_waiter_capacity": 4,
                "ui_event_waiter_overflows": 1,
            },
        )
    )
    historical_ui_event_entity = C300XAgentDiagnosticsSensor(  # type: ignore[arg-type]
        historical_ui_event_entry
    )

    assert historical_ui_event_entity.native_value == "idle"


def test_agent_diagnostics_sensor_options_include_display_event_watchdog() -> None:
    entity = C300XAgentDiagnosticsSensor(_FakeEntry())  # type: ignore[arg-type]
    state = _agent_diagnostics_status(
        {
            "agent_init_script_present": True,
            "agent_init_link_ok": True,
            "subscription_count": 1,
            "home_assistant_connected_this_run": True,
            "ui_event_waiters": 4,
            "ui_event_waiter_capacity": 4,
        }
    )

    assert state == "display_event_watchdog"
    assert state in entity._attr_options


def test_agent_status_sensor_reports_connection_errors() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            connection_state=_FakeConnectionState(
                available=False,
                connection_state="disconnected",
                reconnect_count=3,
                last_connection_stage="agent_api",
                last_reconnect_reason="ClientConnectorError",
                last_connection_error="ClientConnectorError: connection refused",
                next_reconnect_delay_seconds=300,
            )
        )
    )
    entity = C300XAgentStatusSensor(entry)  # type: ignore[arg-type]

    assert entity.available is True
    assert entity.native_value == "error"
    assert entity.extra_state_attributes["reason"] == "agent_disconnected"
    assert entity.extra_state_attributes["last_connection_stage"] == "agent_api"
    assert entity.extra_state_attributes["last_connection_error"] == (
        "ClientConnectorError: connection refused"
    )
    assert entity.extra_state_attributes["next_reconnect_delay_seconds"] == 300


def test_agent_status_sensor_reports_event_subscription_errors() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            connection_state=_FakeConnectionState(
                available=True,
                connection_state="reconnecting",
                last_connection_stage="event_subscription",
                last_reconnect_reason="event_subscription_registration",
                last_connection_error="device agent returned HTTP 404",
                next_reconnect_delay_seconds=30,
            )
        )
    )
    entity = C300XAgentStatusSensor(entry)  # type: ignore[arg-type]

    assert entity.native_value == "warning"
    assert entity.extra_state_attributes["reason"] == "agent_reconnecting"
    assert entity.extra_state_attributes["last_connection_stage"] == (
        "event_subscription"
    )
    assert entity.extra_state_attributes["last_reconnect_reason"] == (
        "event_subscription_registration"
    )


def test_agent_status_sensor_warns_for_pending_update() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            agent_update_state=types.SimpleNamespace(
                update_required=True,
                state="update_available",
                reason="bundle_hash_mismatch",
                installed_version="0.2.0",
                available_version="0.3.1",
            )
        )
    )
    entity = C300XAgentStatusSensor(entry)  # type: ignore[arg-type]

    assert entity.native_value == "warning"
    assert entity.extra_state_attributes["reason"] == "agent_update_required"
    assert entity.extra_state_attributes["agent_update_state"] == "update_available"
    assert entity.extra_state_attributes["agent_update_reason"] == "bundle_hash_mismatch"


def test_agent_status_sensor_updates_on_agent_info_signal() -> None:
    entry = _FakeEntry()
    entity = C300XAgentStatusSensor(entry)  # type: ignore[arg-type]

    entity._handle_agent_info_changed("entry-1")

    assert entity.wrote_state is True


def test_agent_diagnostics_sensor_refreshes_safe_write_diagnostics() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(
                capabilities={"diagnostics": {"supported": True, "writes": True}},
            )
        )
        entity = C300XAgentDiagnosticsSensor(entry)  # type: ignore[arg-type]
        entity.hass = _FakeHass()  # type: ignore[assignment]

        await entity.async_update()

        attrs = entity.extra_state_attributes
        assert entry.runtime_data.api.diagnostics_calls == 1
        assert entity.native_value == "media_resources_open"
        assert attrs["agent_write_count"] == 2
        assert attrs["last_write_reason"] == "updated"
        assert attrs["change_reason"] == "api_refresh"
        assert attrs["updated_at"] == entry.runtime_data.agent_diagnostics_updated_at
        assert attrs["updated_by"] == "api_refresh"
        assert attrs["qml_patch_last_action"] == "apply"
        assert attrs["accepted_clients"] == 3
        assert attrs["video_running"] is False
        assert attrs["video_bridge_active_threads"] == 1

    asyncio.run(_run())


def test_agent_write_diagnostics_refresh_dispatches_one_shot_update() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(
                capabilities={"diagnostics": {"supported": True, "writes": True}},
            )
        )
        dispatcher_signals.clear()

        original_dispatch = agent_diagnostics.async_dispatcher_send
        agent_diagnostics.async_dispatcher_send = (
            lambda hass, signal, entry_id: dispatcher_signals.append((signal, entry_id))
        )
        try:
            result = await agent_diagnostics.async_refresh_agent_diagnostics(  # type: ignore[arg-type]
                _FakeHass(),
                entry,  # type: ignore[arg-type]
            )
        finally:
            agent_diagnostics.async_dispatcher_send = original_dispatch

        assert result is not None
        assert entry.runtime_data.api.diagnostics_calls == 1
        assert entry.runtime_data.agent_diagnostics["agent_write_count"] == 2
        assert dispatcher_signals == [
            (SIGNAL_AGENT_DIAGNOSTICS_CHANGED, "entry-1")
        ]

    asyncio.run(_run())


def test_system_metric_sensors_are_disabled_by_default() -> None:
    assert C300XAgentDiagnosticsSensor._attr_entity_registry_enabled_default is False
    assert C300XDeviceCpuSensor._attr_entity_registry_enabled_default is False
    assert C300XDeviceLoadSensor._attr_entity_registry_enabled_default is False
    assert C300XDeviceMemorySensor._attr_entity_registry_enabled_default is False
    assert C300XDeviceTemperatureSensor._attr_entity_registry_enabled_default is False


def test_non_connection_sensor_goes_unavailable_when_agent_disconnected() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            connection_state=_FakeConnectionState(
                available=False,
                connection_state="disconnected",
            )
        )
    )
    entity = C300XDoorbellStateSensor(entry)  # type: ignore[arg-type]

    assert entity.available is False


def test_doorbell_state_sensor_requires_doorbell_video_events() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(capabilities={"doorbell_events": True})
        )
        entities: list[Any] = []

        await async_setup_sensor_entry(_FakeHass(), entry, entities.extend)  # type: ignore[arg-type]

        assert not any(
            isinstance(entity, C300XDoorbellStateSensor) for entity in entities
        )

    asyncio.run(_run())


def test_doorbell_state_sensor_is_created_for_doorbell_video_events() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(
                capabilities={"doorbell_video": {"supported": True}}
            )
        )
        entities: list[Any] = []

        await async_setup_sensor_entry(_FakeHass(), entry, entities.extend)  # type: ignore[arg-type]

        assert any(isinstance(entity, C300XDoorbellStateSensor) for entity in entities)

    asyncio.run(_run())


def test_system_metric_sensor_recovers_when_metrics_missing() -> None:
    async def _run() -> None:
        entry = _FakeEntry()
        entity = C300XDeviceLoadSensor(entry)  # type: ignore[arg-type]
        entity.hass = _FakeHass()

        entity._schedule_recovery_refresh_if_needed()
        await _drain_tasks()

        assert entry.runtime_data.api.metrics_calls == 1
        assert entity.native_value == 5.5
        assert entity.available is True

    asyncio.run(_run())


def test_system_metric_sensor_skips_refresh_when_metrics_cached() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            system_metrics={
                "cpu_usage_percent": 8.0,
                "load_1m": 0.77,
                "load_5m": 0.66,
                "load_15m": 0.55,
                "load_1m_percent": 77.0,
                "load_5m_percent": 66.0,
                "load_15m_percent": 55.0,
                "memory_total_kb": 262144,
                "memory_available_kb": 196608,
                "memory_used_kb": 65536,
                "memory_usage_percent": 25.0,
                "cpu_count": 1,
                "temperature_c": 41.0,
                "temperature_source": "sysfs",
                "raw": {},
            }
        )
    )
    entity = C300XDeviceLoadSensor(entry)  # type: ignore[arg-type]
    entity.hass = _FakeHass()

    entity._schedule_recovery_refresh_if_needed()

    assert entry.runtime_data.api.metrics_calls == 0
    assert entity.native_value == 77.0


def test_system_metric_sensor_uses_pushed_metrics_without_api_call() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            system_metrics={
                "cpu_usage_percent": 3.0,
                "load_1m": 0.12,
                "load_5m": 0.0,
                "load_15m": 0.0,
                "load_1m_percent": 12.0,
                "load_5m_percent": 0.0,
                "load_15m_percent": 0.0,
                "memory_total_kb": 262144,
                "memory_available_kb": 196608,
                "memory_used_kb": 65536,
                "memory_usage_percent": 25.0,
                "cpu_count": 1,
                "temperature_c": 41.0,
                "temperature_source": "sysfs",
                "raw": {},
            }
        )
    )
    entity = C300XDeviceLoadSensor(entry)  # type: ignore[arg-type]
    entity._attr_available = False

    entity._handle_system_metrics_changed("entry-1")

    assert entry.runtime_data.api.metrics_calls == 0
    assert entity.native_value == 12.0
    assert entity.available is True
    assert entity.wrote_state is True


def test_cpu_metric_sensor_uses_pushed_cpu_percent() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            system_metrics={
                "cpu_count": 2,
                "cpu_usage_percent": 3.5,
                "raw": {},
            }
        )
    )
    entity = C300XDeviceCpuSensor(entry)  # type: ignore[arg-type]

    assert entity.native_value == 3.5
    assert entity.extra_state_attributes == {"cpu_count": 2}


def test_memory_metric_sensor_uses_pushed_memory_percent() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            system_metrics={
                "memory_total_kb": 262144,
                "memory_available_kb": 196608,
                "memory_used_kb": 65536,
                "memory_usage_percent": 25.0,
                "raw": {},
            }
        )
    )
    entity = C300XDeviceMemorySensor(entry)  # type: ignore[arg-type]

    assert entity.native_value == 25.0
    assert entity.extra_state_attributes == {
        "memory_total_kb": 262144,
        "memory_available_kb": 196608,
        "memory_used_kb": 65536,
    }


def test_doorbell_state_sensor_keeps_raw_agent_state_for_translation() -> None:
    entry = _FakeEntry()
    entity = C300XDoorbellStateSensor(entry)  # type: ignore[arg-type]
    entity.hass = _FakeHass()
    event = types.SimpleNamespace(
        data={
            "entry_id": entry.entry_id,
            "event_key": "doorbell_view_requested",
            "doorbell": "view_requested",
            "event_at": "2026-06-01T10:00:00Z",
        }
    )

    entity._handle_agent_event(event)

    assert entity.native_value == "view_requested"
    assert entity._attr_options == ["idle", "ringing", "view_requested"]
    assert entity.extra_state_attributes == {
        "last_event_at": "2026-06-01T10:00:00Z"
    }
    assert entity.wrote_state is True


def test_doorbell_state_sensor_keeps_view_until_agent_close_event() -> None:
    entry = _FakeEntry()
    entity = C300XDoorbellStateSensor(entry)  # type: ignore[arg-type]
    entity.hass = _FakeHass()
    event = types.SimpleNamespace(
        data={
            "entry_id": entry.entry_id,
            "event_key": "doorbell_view_requested",
            "doorbell": "view_requested",
            "event_at": "2026-06-01T10:00:00Z",
        }
    )

    entity._handle_agent_event(event)

    assert entity.native_value == "view_requested"
    assert entity.available is True


def test_doorbell_state_sensor_uses_agent_event_key_when_doorbell_field_is_missing() -> None:
    entry = _FakeEntry()
    entity = C300XDoorbellStateSensor(entry)  # type: ignore[arg-type]
    entity.hass = _FakeHass()
    event = types.SimpleNamespace(
        data={
            "entry_id": entry.entry_id,
            "event_key": "doorbell_pressed",
            "event_at": "2026-06-01T10:00:00Z",
        }
    )

    entity._handle_agent_event(event)

    assert entity.native_value == "ringing"


def test_doorbell_state_sensor_does_not_synthesize_idle_without_close_event() -> None:
    entry = _FakeEntry()
    entity = C300XDoorbellStateSensor(entry)  # type: ignore[arg-type]
    entity.hass = _FakeHass()
    event = types.SimpleNamespace(
        data={
            "entry_id": entry.entry_id,
            "event_key": "doorbell_view_requested",
            "event_at": "2026-06-01T10:00:00Z",
        }
    )

    entity._handle_agent_event(event)

    assert entity.native_value == "view_requested"
    assert entity.available is True
    assert entity.wrote_state is True


def test_doorbell_state_sensor_clears_on_media_closed() -> None:
    entry = _FakeEntry()
    entity = C300XDoorbellStateSensor(entry)  # type: ignore[arg-type]

    entity._state = "view_requested"
    event = types.SimpleNamespace(
        data={
            "entry_id": entry.entry_id,
            "event_key": "doorbell_media_closed",
            "doorbell": "idle",
            "event_at": "2026-06-01T10:00:30Z",
        }
    )

    entity._handle_agent_event(event)

    assert entity.native_value == "idle"
    assert entity.extra_state_attributes == {
        "last_event_at": "2026-06-01T10:00:30Z"
    }
    assert entity.available is True
    assert entity.wrote_state is True


def test_doorbell_state_sensor_does_not_infer_state_from_runtime_video_window() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            event_state=types.SimpleNamespace(
                video_available=True,
            )
        )
    )
    entity = C300XDoorbellStateSensor(entry)  # type: ignore[arg-type]
    entity._state = "idle"

    assert entity.native_value == "idle"


def test_doorbell_state_sensor_initializes_idle_from_agent_media_state() -> None:
    entry = _FakeEntry()
    entity = C300XDoorbellStateSensor(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.native_value == "idle"
    assert entry.runtime_data.api.doorbell_video_status_calls == 1
    assert entity.available is True


def test_doorbell_state_sensor_writes_initial_idle_when_added_to_hass() -> None:
    entry = _FakeEntry()
    entity = C300XDoorbellStateSensor(entry)  # type: ignore[arg-type]
    entity.hass = _FakeHass()

    asyncio.run(entity.async_added_to_hass())

    assert entity.native_value == "idle"
    assert entity.wrote_state is True
    assert entry.runtime_data.api.doorbell_video_status_calls == 1


def test_doorbell_state_sensor_does_not_clear_active_ring_from_status_refresh() -> None:
    api = _FakeApi()
    api.doorbell_video_status = {
        "available": True,
        "media_owner": "ring",
        "window_available": True,
        "bridge": {
            "ring_call_active": True,
            "ring_media_active": True,
            "unanswered_ring_call": True,
        },
    }
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
    entity = C300XDoorbellStateSensor(entry)  # type: ignore[arg-type]
    entity._state = "ringing"

    asyncio.run(entity.async_update())

    assert entity.native_value == "ringing"
    assert entry.runtime_data.api.doorbell_video_status_calls == 1


def test_doorbell_state_accepts_only_agent_canonical_values() -> None:
    assert normalize_doorbell_state({"doorbell": "idle"}) == "idle"
    assert normalize_doorbell_state({"doorbell": "ringing"}) == "ringing"
    assert normalize_doorbell_state({"doorbell": "view_requested"}) == "view_requested"
    assert normalize_doorbell_state({"doorbell": "pressed"}) is None
    assert normalize_doorbell_state({"doorbell": "doorbell_view_requested"}) is None
    assert normalize_doorbell_state({"state": {"doorbell": "pressed"}}) is None


def test_system_metric_sensor_does_not_refresh_while_reconnecting() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            connection_state=_FakeConnectionState(
                available=True,
                connection_state="reconnecting",
            )
        )
    )
    entity = C300XDeviceLoadSensor(entry)  # type: ignore[arg-type]
    entity.hass = _FakeHass()
    entity._attr_available = False
    entity.async_write_ha_state = lambda: None  # type: ignore[method-assign]

    entity._handle_connection_state_changed("entry-1")

    assert entry.runtime_data.api.metrics_calls == 0


def test_system_metric_sensor_recovers_when_cached_metric_is_unknown() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(
                system_metrics={
                    "cpu_usage_percent": None,
                    "load_1m": None,
                    "load_5m": 0.0,
                    "load_15m": 0.0,
                    "temperature_c": None,
                    "temperature_source": None,
                    "raw": {},
                }
            )
        )
        entity = C300XDeviceLoadSensor(entry)  # type: ignore[arg-type]
        entity.hass = _FakeHass()
        entity.async_write_ha_state = lambda: None  # type: ignore[method-assign]

        entity._handle_connection_state_changed("entry-1")
        await _drain_tasks()

        assert entry.runtime_data.api.metrics_calls == 1
        assert entity.native_value == 5.5

    asyncio.run(_run())


def test_text_memos_sensor_exposes_counters_and_latest_text_metadata() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            memos={
                "available": True,
                "total": 2,
                "text_total": 1,
                "voice_total": 1,
                "newest_at": "2024-03-09T16:02:02Z",
                "memos": [
                    {
                        "id": "text/memo_1",
                        "kind": "text",
                        "read": False,
                        "text": "local memo",
                        "has_text": True,
                        "has_audio": False,
                        "text_truncated": False,
                    },
                    {
                        "id": "voice/memo_1",
                        "kind": "voice",
                        "read": True,
                        "text": None,
                        "has_text": False,
                        "has_audio": True,
                        "text_truncated": False,
                    },
                ],
            }
        )
    )
    entity = C300XTextMemosSensor(entry)  # type: ignore[arg-type]

    assert entity.native_value == 1
    assert entity.extra_state_attributes == {
        "all_memos_total": 2,
        "newest_at": "2024-03-09T16:02:02Z",
        "kind": "text",
        "has_memo": True,
        "total": 1,
        "unread": 1,
        "read": 0,
        "latest_memo_id": "text/memo_1",
        "latest_memo_at": None,
        "latest_memo_read": False,
        "has_audio": False,
        "latest_text": "local memo",
        "text_truncated": False,
    }


def test_text_memos_sensor_flags_truncated_latest_text() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            memos={
                "available": True,
                "text_total": 1,
                "memos": [
                    {
                        "id": "text/long",
                        "kind": "text",
                        "text": "x" * 300,
                        "text_truncated": False,
                    },
                ],
            }
        )
    )
    entity = C300XTextMemosSensor(entry)  # type: ignore[arg-type]

    assert entity.extra_state_attributes["latest_text"] == "x" * 300
    assert entity.extra_state_attributes["text_truncated"] is True


def test_text_memos_sensor_uses_empty_latest_metadata() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            memos={
                "available": True,
                "text_total": 0,
                "memos": [],
            }
        )
    )
    entity = C300XTextMemosSensor(entry)  # type: ignore[arg-type]

    assert entity.native_value == 0
    assert entity.extra_state_attributes["has_memo"] is False
    assert entity.extra_state_attributes["latest_memo_id"] is None
    assert entity.extra_state_attributes["latest_text"] is None


def test_voice_memos_sensor_exposes_counters_and_latest_media_metadata() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            memos={
                "available": True,
                "total": 1,
                "text_total": 0,
                "voice_total": 1,
                "memos": [
                    {
                        "id": "voice/memo_1",
                        "kind": "voice",
                        "read": True,
                        "iso_time": "2024-03-09T16:02:02Z",
                        "text": None,
                        "has_text": False,
                        "has_audio": True,
                        "text_truncated": False,
                    },
                ],
            }
        )
    )
    entity = C300XVoiceMemosSensor(entry)  # type: ignore[arg-type]

    assert entity.native_value == 1
    attrs = entity.extra_state_attributes
    assert attrs["all_memos_total"] == 1
    assert attrs["total"] == 1
    assert attrs["unread"] == 0
    assert attrs["read"] == 1
    assert attrs["latest_memo_id"] == "voice/memo_1"
    assert attrs["latest_memo_at"] == "2024-03-09T16:02:02Z"
    assert attrs["has_audio"] is True
    assert attrs["media_content_id"] == (
        "media-source://bticino_c300x/voice/entry-1/memo_1"
    )


def test_video_messages_sensor_exposes_latest_media_metadata() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            answering_machine_messages={
                "available": True,
                "total": 1,
                "unread": 1,
                "read": 0,
                "messages": [
                    {
                        "id": "message_1",
                        "read": False,
                        "unix_time": 1710000122,
                        "iso_time": "2024-03-09T16:02:02Z",
                        "has_video": True,
                        "media_mime_type": "video/x-msvideo",
                        "media_size": 12,
                    },
                ],
            }
        )
    )
    entity = C300XVoicemailMessagesSensor(entry)  # type: ignore[arg-type]

    attrs = entity.extra_state_attributes
    assert entity.native_value == 1
    assert attrs["unread"] == 1
    assert attrs["read"] == 0
    assert attrs["has_message"] is True
    assert attrs["latest_message_id"] == "message_1"
    assert attrs["media_content_id"] == (
        "media-source://bticino_c300x/entry-1/message_1"
    )


def test_message_sensors_load_one_startup_snapshot() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(
                capabilities={
                    "answering_machine": {
                        "supported": True,
                        "messages": {"supported": True},
                    },
                    "memos": {"supported": True},
                },
            )
        )
        entities: list[Any] = []

        await async_setup_sensor_entry(_FakeHass(), entry, entities.extend)  # type: ignore[arg-type]

        assert entry.runtime_data.api.answering_machine_messages_calls == 1
        assert entry.runtime_data.api.memos_calls == 1
        video_sensor = next(
            entity for entity in entities if isinstance(entity, C300XVoicemailMessagesSensor)
        )
        text_sensor = next(
            entity for entity in entities if isinstance(entity, C300XTextMemosSensor)
        )
        voice_sensor = next(
            entity for entity in entities if isinstance(entity, C300XVoiceMemosSensor)
        )
        assert len(entities) == 4
        assert video_sensor.native_value == 1
        assert video_sensor.extra_state_attributes["unread"] == 1
        assert video_sensor.extra_state_attributes["latest_message_id"] == "message_1"
        assert text_sensor.native_value == 1
        assert text_sensor.extra_state_attributes["latest_text"] == "local memo"
        assert voice_sensor.native_value == 1

    asyncio.run(_run())


def test_memo_event_refresh_is_deduplicated_between_memo_sensors() -> None:
    async def _run() -> None:
        entry = _FakeEntry()
        text_sensor = C300XTextMemosSensor(entry)  # type: ignore[arg-type]
        voice_sensor = C300XVoiceMemosSensor(entry)  # type: ignore[arg-type]
        text_sensor.hass = _FakeHass()
        voice_sensor.hass = text_sensor.hass
        text_sensor.async_write_ha_state = lambda: None  # type: ignore[method-assign]
        voice_sensor.async_write_ha_state = lambda: None  # type: ignore[method-assign]
        event = types.SimpleNamespace(
            data={
                "entry_id": entry.entry_id,
                "event_key": "memos_changed",
                "memos": {
                    "available": True,
                    "total": 2,
                    "text_total": 1,
                    "voice_total": 1,
                },
            }
        )

        text_sensor._handle_agent_event(event)
        voice_sensor._handle_agent_event(event)
        await _drain_tasks()

        assert entry.runtime_data.api.memos_calls == 1
        assert entry.runtime_data.memos_refresh_task is None
        assert entry.runtime_data.memos["memos"][0]["text"] == "local memo"

    asyncio.run(_run())
