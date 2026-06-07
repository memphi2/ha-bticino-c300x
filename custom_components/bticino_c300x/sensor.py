"""Sensors for BTicino C300X."""

from __future__ import annotations

from asyncio import Task
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import (
    C300XAgentApiError,
    normalize_answering_machine_messages,
    normalize_memos,
)
from .capabilities import (
    answering_machine_messages_supported,
    capability_is_supported,
    diagnostics_supported,
    memos_supported,
)
from .const import (
    EVENT_AGENT_EVENT_RECEIVED,
    SIGNAL_AGENT_DIAGNOSTICS_CHANGED,
    SIGNAL_AGENT_INFO_CHANGED,
    SIGNAL_CONNECTION_STATE_CHANGED,
    SIGNAL_MEMOS_CHANGED,
    SIGNAL_SYSTEM_METRICS_CHANGED,
    SIGNAL_VIDEO_MESSAGES_CHANGED,
)
from .device_user import media_user_attributes
from .doorbell_state import (
    DOORBELL_STATE_IDLE,
    DOORBELL_STATE_RINGING,
    DOORBELL_STATE_VIEW_REQUESTED,
    DOORBELL_STATES,
    raw_doorbell_state_value,
)
from .entity import C300XEntity
from .event_payload import agent_event_key
from .memos import (
    latest_memo,
    latest_memo_attributes,
)
from .message_refresh import (
    async_answering_machine_messages,
    async_memos,
    schedule_answering_machine_messages_refresh,
    schedule_memos_refresh,
)
from .video_messages import (
    latest_video_message_attributes,
)

PARALLEL_UPDATES = 1
_METRICS_CACHE_SECONDS = 10
_DOORBELL_CLOSED_STATES = frozenset({DOORBELL_STATE_IDLE})
_DOORBELL_EVENT_STATES = {
    "doorbell_pressed": DOORBELL_STATE_RINGING,
    "doorbell_view_requested": DOORBELL_STATE_VIEW_REQUESTED,
    "doorbell_media_closed": DOORBELL_STATE_IDLE,
}
_AGENT_RUNTIME_DIAGNOSTIC_KEYS = (
    "last_wake_reason",
    "loop_iterations",
    "poll_wakeups",
    "last_poll_timeout_ms",
    "last_poll_count",
    "accepted_clients",
    "open_fd_count",
    "agent_init_script_present",
    "agent_init_link_ok",
    "subscription_count",
    "recent_event_count",
    "recent_event_capacity",
    "display_bridge_registered",
    "display_bridge_disabled",
    "home_assistant_connected_this_run",
    "home_assistant_last_seen_at",
    "ui_event_revision",
)
_AGENT_VIDEO_DIAGNOSTIC_KEYS = (
    "video_running",
    "video_media_starting",
    "video_call_active",
    "video_clients",
    "video_bridge_open_fds",
    "video_bridge_active_threads",
)
_AGENT_FLEXISIP_DIAGNOSTIC_KEYS = (
    "flexisip_backup_available",
    "flexisip_restart_marker",
    "flexisip_backup_marker",
    "flexisip_reference_state",
)


def _agent_diagnostic_attributes(
    diagnostics: dict[str, Any],
    keys: tuple[str, ...],
) -> dict[str, Any]:
    """Return selected non-sensitive diagnostic attributes."""

    attrs = {key: diagnostics.get(key) for key in keys}
    if "poll_wakeups" in keys:
        attrs["poll_wakeups_per_loop"] = _poll_wakeups_per_loop(diagnostics)
    return attrs


def _agent_info_attributes(agent_info: dict[str, Any]) -> dict[str, Any]:
    """Return non-sensitive device-agent metadata for the status sensor."""

    version = agent_info.get("version")
    return {
        key: value
        for key, value in (
            ("agent_version", version),
            ("implementation", agent_info.get("implementation")),
            ("api_version", agent_info.get("api_version")),
            ("model", agent_info.get("model")),
            ("firmware", agent_info.get("firmware")),
        )
        if value is not None
    }


def _poll_wakeups_per_loop(diagnostics: dict[str, Any]) -> float | None:
    """Return a compact poll wakeup ratio for idle diagnostics."""

    loop_iterations = diagnostics.get("loop_iterations")
    poll_wakeups = diagnostics.get("poll_wakeups")
    if type(loop_iterations) not in (int, float) or loop_iterations <= 0:
        return None
    if type(poll_wakeups) not in (int, float) or poll_wakeups < 0:
        return None
    return round(float(poll_wakeups) / float(loop_iterations), 4)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up C300X sensors."""

    entities: list[SensorEntity] = [
        C300XAgentStatusSensor(entry),
    ]
    metrics = _system_metrics_capability(entry)
    initial_refresh_entities: list[SensorEntity] = []
    if capability_is_supported(entry.runtime_data.capabilities, "doorbell_video"):
        doorbell_state_sensor = C300XDoorbellStateSensor(entry)
        entities.append(doorbell_state_sensor)
    if metrics.get("cpu"):
        cpu_sensor = C300XDeviceCpuSensor(entry)
        entities.append(cpu_sensor)
    if metrics.get("temperature"):
        temperature_sensor = C300XDeviceTemperatureSensor(entry)
        entities.append(temperature_sensor)
    if metrics.get("load"):
        load_sensor = C300XDeviceLoadSensor(entry)
        entities.append(load_sensor)
    if metrics.get("memory"):
        memory_sensor = C300XDeviceMemorySensor(entry)
        entities.append(memory_sensor)
    if diagnostics_supported(entry.runtime_data.capabilities):
        initial_refresh_entities.append(entities[0])
    if answering_machine_messages_supported(entry.runtime_data.capabilities):
        await _async_refresh_initial_answering_machine_messages(entry)
        message_sensor = C300XVoicemailMessagesSensor(entry)
        entities.append(message_sensor)
    if memos_supported(entry.runtime_data.capabilities):
        await _async_refresh_initial_memos(entry)
        text_memos_sensor = C300XTextMemosSensor(entry)
        voice_memos_sensor = C300XVoiceMemosSensor(entry)
        entities.extend(
            [
                text_memos_sensor,
                voice_memos_sensor,
            ]
        )
    if initial_refresh_entities:
        await _async_refresh_initial_states(initial_refresh_entities)
    async_add_entities(entities)


class C300XConnectionDiagnosticSensor(C300XEntity, SensorEntity):
    """Base class for device-agent connection diagnostic sensors."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    @property
    def available(self) -> bool:
        """Keep connection diagnostics readable when the agent is offline."""

        return bool(getattr(self, "_attr_available", True))

    async def async_added_to_hass(self) -> None:
        """Subscribe to connection-state updates."""

        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CONNECTION_STATE_CHANGED,
                self._handle_connection_state_changed,
            )
        )

    @callback
    def _handle_connection_state_changed(self, entry_id: str) -> None:
        if entry_id == self._entry.entry_id:
            self.async_write_ha_state()


class C300XAgentStatusSensor(C300XConnectionDiagnosticSensor):
    """Aggregated device-agent health status."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["ok", "warning", "error"]
    _attr_translation_key = "agent_status"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "agent_status")

    async def async_update(self) -> None:
        """Refresh agent metadata and diagnostics on explicit HA update requests."""

        try:
            self._entry.runtime_data.agent_info = (
                await self._entry.runtime_data.api.async_validate_setup()
            )
        except C300XAgentApiError:
            return
        if diagnostics_supported(self._entry.runtime_data.capabilities):
            await self._async_refresh_diagnostics(write_state=False)

    async def async_added_to_hass(self) -> None:
        """Subscribe to connection and diagnostics updates."""

        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_AGENT_DIAGNOSTICS_CHANGED,
                self._handle_diagnostics_changed,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_AGENT_INFO_CHANGED,
                self._handle_agent_info_changed,
            )
        )

    @property
    def native_value(self) -> str:
        """Return an operator-friendly agent health state."""

        connection_state = self._connection_state_value()
        if connection_state == "disconnected":
            return "error"
        if connection_state == "reconnecting":
            return "warning"
        if self._agent_update_required():
            return "warning"
        return "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return safe status context without secrets or callback URLs."""

        state = self._entry.runtime_data.connection_state
        diagnostics = self._entry.runtime_data.agent_diagnostics
        agent_info = self._entry.runtime_data.agent_info
        update_state = getattr(self._entry.runtime_data, "agent_update_state", None)
        attrs: dict[str, Any] = {
            "reason": self._status_reason(),
            **_agent_info_attributes(agent_info),
            "connection_state": self._connection_state_value(),
            "last_connection_stage": state.last_connection_stage,
            "last_connection_error": state.last_connection_error,
            "last_reconnect_reason": state.last_reconnect_reason,
            "next_reconnect_delay_seconds": state.next_reconnect_delay_seconds,
            "reconnect_count": state.reconnect_count,
            "agent_write_count": diagnostics.get("agent_write_count"),
            "last_write_at": diagnostics.get("last_write_at"),
            "last_write_reason": diagnostics.get("last_write_reason"),
            "last_write_class": diagnostics.get("last_write_class"),
            "qml_patch_last_action": diagnostics.get("qml_patch_last_action"),
            **_agent_diagnostic_attributes(
                diagnostics,
                _AGENT_RUNTIME_DIAGNOSTIC_KEYS,
            ),
            **_agent_diagnostic_attributes(
                diagnostics,
                _AGENT_VIDEO_DIAGNOSTIC_KEYS,
            ),
            **_agent_diagnostic_attributes(
                diagnostics,
                _AGENT_FLEXISIP_DIAGNOSTIC_KEYS,
            ),
        }
        if update_state is not None:
            attrs.update(
                {
                    "agent_update_state": getattr(update_state, "state", None),
                    "agent_update_reason": getattr(update_state, "reason", None),
                    "installed_agent_version": getattr(update_state, "installed_version", None),
                    "available_agent_version": getattr(update_state, "available_version", None),
                }
            )
        return attrs

    def _connection_state_value(self) -> str:
        state = self._entry.runtime_data.connection_state
        if not state.available:
            return "disconnected"
        return state.connection_state

    def _agent_update_required(self) -> bool:
        update_state = getattr(self._entry.runtime_data, "agent_update_state", None)
        return bool(getattr(update_state, "update_required", False))

    def _status_reason(self) -> str:
        connection_state = self._connection_state_value()
        if connection_state == "disconnected":
            return "agent_disconnected"
        if connection_state == "reconnecting":
            return "agent_reconnecting"
        if self._agent_update_required():
            return "agent_update_required"
        return "agent_ok"

    @callback
    def _handle_diagnostics_changed(self, entry_id: str) -> None:
        if entry_id == self._entry.entry_id:
            self.async_write_ha_state()

    @callback
    def _handle_agent_info_changed(self, entry_id: str) -> None:
        if entry_id == self._entry.entry_id:
            self.async_write_ha_state()

    async def _async_refresh_diagnostics(self, *, write_state: bool = True) -> None:
        try:
            diagnostics = await self._entry.runtime_data.api.async_diagnostics()
        except C300XAgentApiError:
            return
        self._entry.runtime_data.agent_diagnostics = diagnostics
        self._entry.runtime_data.agent_diagnostics_updated_at = datetime.now(UTC)
        if write_state:
            self.async_write_ha_state()


class C300XDoorbellStateSensor(C300XEntity, SensorEntity):
    """Doorbell runtime state from the device agent."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(DOORBELL_STATES)
    _attr_should_poll = False
    _attr_translation_key = "doorbell_state"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "doorbell_state")
        self._state: str | None = None
        self._last_event_at: str | None = None

    @property
    def native_value(self) -> str | None:
        """Return the latest known doorbell state."""

        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return doorbell-state metadata."""

        return {
            "last_event_at": self._last_event_at,
            **media_user_attributes(self._entry),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to doorbell push events."""

        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_AGENT_EVENT_RECEIVED,
                self._handle_agent_event,
            )
        )

    @callback
    def _handle_agent_event(self, event) -> None:
        if event.data.get("entry_id") != self._entry.entry_id:
            return
        state = self._doorbell_state_from_event(event.data)
        if state is None:
            return
        if state in _DOORBELL_CLOSED_STATES:
            self._state = DOORBELL_STATE_IDLE
            self._last_event_at = event.data.get("event_at")
            self._attr_available = True
            self.async_write_ha_state()
            return
        self._state = state
        self._last_event_at = event.data.get("event_at")
        self._attr_available = True
        self.async_write_ha_state()

    def _doorbell_state_from_event(self, data: dict[str, Any]) -> str | None:
        state = raw_doorbell_state_value(data.get("doorbell"))
        if state is not None:
            return state
        event_key = agent_event_key(data)
        return _DOORBELL_EVENT_STATES.get(event_key or "")


class C300XSystemMetricSensor(C300XEntity, SensorEntity):
    """Base class for low-frequency device-agent system metric sensors."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _metric_key = ""

    def __init__(self, entry: ConfigEntry, key: str) -> None:
        super().__init__(entry, key)
        self._recovery_refresh_task: Task[None] | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to pushed metric events and one-shot recovery refreshes."""

        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CONNECTION_STATE_CHANGED,
                self._handle_connection_state_changed,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SYSTEM_METRICS_CHANGED,
                self._handle_system_metrics_changed,
            )
        )
        self._schedule_recovery_refresh_if_needed(force=True)

    async def async_update(self) -> None:
        """Refresh cached system metrics from the device agent."""

        try:
            await _async_system_metrics(
                self._entry,
                force_refresh=self._metric_needs_refresh(),
            )
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._attr_available = True

    @property
    def _metrics(self) -> dict[str, Any]:
        return self._entry.runtime_data.system_metrics

    @callback
    def _handle_connection_state_changed(self, entry_id: str) -> None:
        if entry_id != self._entry.entry_id:
            return
        self._schedule_recovery_refresh_if_needed()
        self.async_write_ha_state()

    @callback
    def _handle_system_metrics_changed(self, entry_id: str) -> None:
        if entry_id != self._entry.entry_id:
            return
        self._attr_available = True
        self.async_write_ha_state()

    @callback
    def _schedule_recovery_refresh_if_needed(self, *, force: bool = False) -> None:
        if self.hass is None:
            return
        state = self._entry.runtime_data.connection_state
        if not state.available or state.connection_state != "connected":
            return
        if not force and not self._needs_recovery_refresh():
            return
        if self._recovery_refresh_task and not self._recovery_refresh_task.done():
            return
        self._recovery_refresh_task = self.hass.async_create_task(
            self._async_recovery_refresh()
        )

    async def _async_recovery_refresh(self) -> None:
        try:
            await self.async_update()
        finally:
            self._recovery_refresh_task = None
        self.async_write_ha_state()

    def _needs_recovery_refresh(self) -> bool:
        if not getattr(self, "_attr_available", True):
            return True
        if not bool(self._entry.runtime_data.system_metrics):
            return True
        return self.native_value is None

    def _metric_needs_refresh(self) -> bool:
        key = self._metric_key
        if not key:
            return False
        return self._metrics.get(key) is None

class C300XDeviceTemperatureSensor(C300XSystemMetricSensor):
    """Device-agent host temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1
    _attr_translation_key = "device_temperature"
    _metric_key = "temperature_c"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "device_temperature")

    @property
    def native_value(self) -> float | None:
        """Return the latest device temperature in Celsius."""

        return self._metrics.get("temperature_c")

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return temperature source diagnostics."""

        return {"source": self._metrics.get("temperature_source")}


class C300XDeviceLoadSensor(C300XSystemMetricSensor):
    """Device-agent host CPU-normalized load sensor."""

    _attr_suggested_display_precision = 2
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_translation_key = "device_load"
    _metric_key = "load_1m_percent"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "device_load")

    @property
    def native_value(self) -> float | None:
        """Return the one-minute system load normalized by online CPUs."""

        percent = self._metrics.get("load_1m_percent")
        if percent is not None:
            return percent
        load_1m = self._metrics.get("load_1m")
        cpu_count = self._metrics.get("cpu_count") or 1
        if load_1m is None:
            return None
        return round(float(load_1m) / float(cpu_count) * 100.0, 1)

    @property
    def extra_state_attributes(self) -> dict[str, float | int | None]:
        """Return full load-average diagnostics."""

        return {
            "cpu_count": self._metrics.get("cpu_count"),
            "load_average_1m": self._metrics.get("load_1m"),
            "load_average_5m": self._metrics.get("load_5m"),
            "load_average_15m": self._metrics.get("load_15m"),
            "load_5m_percent": self._metrics.get("load_5m_percent"),
            "load_15m_percent": self._metrics.get("load_15m_percent"),
        }


class C300XDeviceMemorySensor(C300XSystemMetricSensor):
    """Device-agent host memory usage sensor."""

    _attr_suggested_display_precision = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_translation_key = "device_memory"
    _metric_key = "memory_usage_percent"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "device_memory")

    @property
    def native_value(self) -> float | None:
        """Return the latest memory usage percentage."""

        return self._metrics.get("memory_usage_percent")

    @property
    def extra_state_attributes(self) -> dict[str, int | None]:
        """Return memory counters in kB from /proc/meminfo."""

        return {
            "memory_total_kb": self._metrics.get("memory_total_kb"),
            "memory_available_kb": self._metrics.get("memory_available_kb"),
            "memory_used_kb": self._metrics.get("memory_used_kb"),
        }


class C300XDeviceCpuSensor(C300XSystemMetricSensor):
    """Device-agent host CPU usage sensor."""

    _attr_suggested_display_precision = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_translation_key = "device_cpu"
    _metric_key = "cpu_usage_percent"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "device_cpu")

    @property
    def native_value(self) -> float | None:
        """Return the latest host CPU usage percentage."""

        return self._metrics.get("cpu_usage_percent")

    @property
    def extra_state_attributes(self) -> dict[str, int | None]:
        """Return CPU topology diagnostics."""

        return {"cpu_count": self._metrics.get("cpu_count")}


class C300XVoicemailSensor(C300XEntity, SensorEntity):
    """Base class for event-driven video message metadata sensors."""

    _attr_should_poll = False
    _attr_translation_key = "voicemail_messages"

    async def async_added_to_hass(self) -> None:
        """Subscribe to message change events."""

        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_AGENT_EVENT_RECEIVED,
                self._handle_agent_event,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_VIDEO_MESSAGES_CHANGED,
                self._handle_video_messages_refreshed,
            )
        )

    async def async_update(self) -> None:
        """Refresh message metadata on explicit HA update requests."""

        try:
            messages = await async_answering_machine_messages(self._entry)
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._apply_messages(messages)

    @property
    def _messages(self) -> dict[str, Any]:
        return self._entry.runtime_data.answering_machine_messages

    @callback
    def _handle_agent_event(self, event) -> None:
        if event.data.get("entry_id") != self._entry.entry_id:
            return
        if agent_event_key(event.data) != "answering_machine_messages_changed":
            return
        voicemail = event.data.get("voicemail")
        if not isinstance(voicemail, dict):
            return
        messages = normalize_answering_machine_messages(
            {**voicemail, "messages": self._messages.get("messages", [])}
        )
        self._apply_messages(messages)
        if hasattr(self, "hass"):
            schedule_answering_machine_messages_refresh(self.hass, self._entry)

    @callback
    def _handle_video_messages_refreshed(self, entry_id: str) -> None:
        if entry_id != self._entry.entry_id:
            return
        self._attr_available = bool(self._messages.get("available", True))
        self.async_write_ha_state()

    def _apply_messages(self, messages: dict[str, Any], *, write_state: bool = True) -> None:
        self._entry.runtime_data.answering_machine_messages = messages
        self._entry.runtime_data.answering_machine_messages_updated_at = datetime.now(
            UTC
        )
        self._attr_available = bool(messages.get("available", True))
        if write_state:
            self.async_write_ha_state()


class C300XVoicemailMessagesSensor(C300XVoicemailSensor):
    """Total video messages stored on the device."""

    _attr_native_unit_of_measurement = "messages"
    _attr_translation_key = "voicemail_messages"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "voicemail_messages")

    @property
    def native_value(self) -> int | None:
        """Return total video message count."""

        return self._messages.get("total")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return non-sensitive video message summary metadata."""

        return {
            "unread": self._messages.get("unread"),
            "read": self._messages.get("read"),
            "newest_at": self._messages.get("newest_at"),
            **latest_video_message_attributes(self._messages, self._entry.entry_id),
        }


class C300XMemoSensor(C300XEntity, SensorEntity):
    """Base class for event-driven manual memo metadata sensors."""

    _attr_should_poll = False
    _attr_translation_key = "memos"
    _memo_kind = ""

    async def async_added_to_hass(self) -> None:
        """Subscribe to memo change events."""

        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_AGENT_EVENT_RECEIVED,
                self._handle_agent_event,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_MEMOS_CHANGED,
                self._handle_memos_refreshed,
            )
        )

    async def async_update(self) -> None:
        """Refresh memo metadata on explicit HA update requests."""

        try:
            memos = await async_memos(self._entry)
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._apply_memos(memos)

    @property
    def _memos(self) -> dict[str, Any]:
        return self._entry.runtime_data.memos

    @callback
    def _handle_agent_event(self, event) -> None:
        if event.data.get("entry_id") != self._entry.entry_id:
            return
        if agent_event_key(event.data) != "memos_changed":
            return
        memos = event.data.get("memos")
        if isinstance(memos, dict):
            normalized = normalize_memos(
                {**memos, "memos": self._memos.get("memos", [])}
            )
            self._apply_memos(normalized)
        if hasattr(self, "hass"):
            schedule_memos_refresh(self.hass, self._entry)

    @callback
    def _handle_memos_refreshed(self, entry_id: str) -> None:
        if entry_id != self._entry.entry_id:
            return
        self._attr_available = bool(self._memos.get("available", True))
        self.async_write_ha_state()

    def _apply_memos(self, memos: dict[str, Any], *, write_state: bool = True) -> None:
        self._entry.runtime_data.memos = memos
        self._entry.runtime_data.memos_updated_at = datetime.now(UTC)
        self._attr_available = bool(memos.get("available", True))
        if write_state:
            self.async_write_ha_state()

    def _latest_item(self) -> dict[str, Any] | None:
        return latest_memo(self._memos, self._memo_kind)


class C300XTextMemosSensor(C300XMemoSensor):
    """Manual text memos stored on the device."""

    _attr_native_unit_of_measurement = "memos"
    _attr_translation_key = "text_memos"
    _memo_kind = "text"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "text_memos")

    @property
    def native_value(self) -> int | None:
        """Return text memo count."""

        return self._memos.get("text_total")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return text memo counters and latest memo metadata."""

        return {
            "all_memos_total": self._memos.get("total"),
            "newest_at": self._memos.get("newest_at"),
            **latest_memo_attributes(
                self._memos,
                self._memo_kind,
                include_text=True,
            ),
        }


class C300XVoiceMemosSensor(C300XMemoSensor):
    """Manual voice memos stored on the device."""

    _attr_native_unit_of_measurement = "memos"
    _attr_translation_key = "voice_memos"
    _memo_kind = "voice"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "voice_memos")

    @property
    def native_value(self) -> int | None:
        """Return voice memo count."""

        return self._memos.get("voice_total")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return voice memo counters and latest playable metadata."""

        return {
            "all_memos_total": self._memos.get("total"),
            "newest_at": self._memos.get("newest_at"),
            **latest_memo_attributes(
                self._memos,
                self._memo_kind,
                entry_id=self._entry.entry_id,
            ),
        }


async def _async_system_metrics(
    entry: ConfigEntry,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return cached device-agent system metrics."""

    now = datetime.now(UTC)
    updated_at = entry.runtime_data.system_metrics_updated_at
    if (
        not force_refresh
        and entry.runtime_data.system_metrics
        and updated_at is not None
        and (now - updated_at).total_seconds() < _METRICS_CACHE_SECONDS
    ):
        return entry.runtime_data.system_metrics
    metrics = await entry.runtime_data.api.async_system_metrics()
    entry.runtime_data.system_metrics = metrics
    entry.runtime_data.system_metrics_updated_at = now
    return metrics


def _system_metrics_capability(entry: ConfigEntry) -> dict[str, Any]:
    capabilities = getattr(entry.runtime_data, "capabilities", {})
    metrics = capabilities.get("system_metrics") if isinstance(capabilities, dict) else None
    if not isinstance(metrics, dict) or not metrics.get("supported"):
        return {}
    return metrics


async def _async_refresh_initial_answering_machine_messages(
    entry: ConfigEntry,
) -> None:
    """Load a one-shot video-message snapshot for startup state."""

    try:
        await async_answering_machine_messages(entry, force_refresh=True)
    except C300XAgentApiError:
        entry.runtime_data.answering_machine_messages = {
            **entry.runtime_data.answering_machine_messages,
            "available": False,
        }
        entry.runtime_data.answering_machine_messages_updated_at = datetime.now(UTC)


async def _async_refresh_initial_memos(entry: ConfigEntry) -> None:
    """Load a one-shot memo snapshot for startup state."""

    try:
        await async_memos(entry, force_refresh=True)
    except C300XAgentApiError:
        entry.runtime_data.memos = {
            **entry.runtime_data.memos,
            "available": False,
        }
        entry.runtime_data.memos_updated_at = datetime.now(UTC)


async def _async_refresh_initial_states(entities: list[SensorEntity]) -> None:
    """Populate lightweight diagnostic sensors once during setup."""

    for entity in entities:
        if isinstance(entity, C300XAgentStatusSensor):
            await entity._async_refresh_diagnostics(write_state=False)
            continue
        if isinstance(entity, C300XSystemMetricSensor):
            await entity.async_update()
            continue
