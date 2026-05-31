"""Event entities for BTicino C300X device-agent callbacks."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import (
    DoorbellEventType,
    EventDeviceClass,
    EventEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capabilities import event_label, ha_event_types_for_capabilities
from .const import (
    EVENT_ACTION_RECEIVED,
    EVENT_AGENT_EVENT_RECEIVED,
    SIGNAL_EVENT_STATE_CHANGED,
)
from .entity import C300XEntity, supports_capability
from .event_payload import (
    action_event_display_data,
    agent_event_display_data,
    agent_event_key,
    agent_event_name,
)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the C300X device-agent event entity."""

    entities: list[EventEntity] = []
    if supports_capability(entry, "doorbell_events"):
        entities.append(C300XDoorbellEventEntity(entry))
    event_types = ha_event_types_for_capabilities(entry.runtime_data.capabilities)
    if event_types:
        entities.append(C300XDeviceAgentEventEntity(entry, event_types))
    if entities:
        async_add_entities(entities)


class C300XDoorbellEventEntity(C300XEntity, EventEntity):
    """Expose doorbell presses through Home Assistant's standard ring event."""

    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = [DoorbellEventType.RING]
    _attr_should_poll = False
    _attr_translation_key = "doorbell_event"

    def __init__(self, entry: ConfigEntry) -> None:
        C300XEntity.__init__(self, entry, "doorbell_event")
        self._last_ring_at: str | None = None
        self._last_ring_data: dict[str, Any] = {}

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return safe metadata for the latest standard doorbell event."""

        return {
            "last_ring_at": self._last_ring_at,
            "event_key": self._last_ring_data.get("event_key"),
            "event": self._last_ring_data.get("event"),
            "camera_entity_id": self._last_ring_data.get("camera_entity_id"),
            "video_available": self._last_ring_data.get("video_available"),
            "video_active_until": self._last_ring_data.get("video_active_until"),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to device-agent doorbell push events."""

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
        if agent_event_key(event.data) != "doorbell_pressed":
            return
        event_at = event.data.get("event_at")
        if event_at and event_at == self._last_ring_at:
            return
        self._last_ring_at = event_at
        self._last_ring_data = agent_event_display_data(
            dict(event.data),
            _language(getattr(self, "hass", None)),
        )
        self._trigger_event(DoorbellEventType.RING, self._last_ring_data.copy())
        self.async_write_ha_state()


class C300XDeviceAgentEventEntity(C300XEntity, EventEntity):
    """Expose device-agent push callbacks as Home Assistant events."""

    _attr_should_poll = False
    _attr_translation_key = "agent_event"

    def __init__(self, entry: ConfigEntry, event_types: list[str]) -> None:
        C300XEntity.__init__(self, entry, "agent_event")
        self._event_keys = event_types
        self._attr_event_types = event_types
        self._last_event_at: str | None = None
        self._last_event_data: dict[str, Any] = {}

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the last device-agent event for diagnostics."""

        event_state = self._entry.runtime_data.event_state
        data = self._last_event_data
        event_key = agent_event_key(data) or event_state.last_event
        language = _language(getattr(self, "hass", None))
        label = (
            agent_event_name(data, language)
            or agent_event_name(event_state.last_event_data, language)
            or event_label(event_key, language)
        )
        return {
            "event": label,
            "event_value": label,
            "event_key": event_key,
            "last_event": label,
            "last_event_key": event_key,
            "last_event_label": data.get("event_label")
            or event_state.last_event_data.get("event_label"),
            "last_event_label_en": data.get("event_label_en")
            or event_state.last_event_data.get("event_label_en"),
            "last_event_label_de": data.get("event_label_de")
            or event_state.last_event_data.get("event_label_de"),
            "last_event_label_it": data.get("event_label_it")
            or event_state.last_event_data.get("event_label_it"),
            "last_event_at": data.get("event_at") or event_state.last_event_time,
            "camera_entity_id": data.get("camera_entity_id")
            or event_state.last_event_data.get("camera_entity_id"),
            "video_available": _first_value(
                data.get("video_available"),
                event_state.last_event_data.get("video_available"),
            ),
            "video_active_until": data.get("video_active_until")
            or event_state.video_active_until,
            "smartphone_forwarding_mode": _first_value(
                data.get("mode"),
                event_state.smartphone_forwarding_mode,
            ),
            "ringer_muted": _first_value(
                data.get("muted"),
                event_state.ringer_muted,
            ),
            "voicemail_total": _first_value(
                data.get("voicemail_total"),
                _nested_dict_value(data, "voicemail", "total"),
                event_state.voicemail_total,
            ),
            "voicemail_unread": _first_value(
                data.get("voicemail_unread"),
                _nested_dict_value(data, "voicemail", "unread"),
                event_state.voicemail_unread,
            ),
            "memos_total": _first_value(
                data.get("memos_total"),
                _nested_dict_value(data, "memos", "total"),
                event_state.memos_total,
            ),
            "memos_text_total": _first_value(
                data.get("memos_text_total"),
                _nested_dict_value(data, "memos", "text_total"),
                event_state.memos_text_total,
            ),
            "memos_voice_total": _first_value(
                data.get("memos_voice_total"),
                _nested_dict_value(data, "memos", "voice_total"),
                event_state.memos_voice_total,
            ),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to device-agent event state updates."""

        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_AGENT_EVENT_RECEIVED,
                self._handle_agent_event,
            )
        )
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_ACTION_RECEIVED,
                self._handle_action_event,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_EVENT_STATE_CHANGED,
                self._handle_event_state_changed,
            )
        )

    @callback
    def _handle_agent_event(self, event) -> None:
        if event.data.get("entry_id") != self._entry.entry_id:
            return
        self._write_event_data(dict(event.data))

    @callback
    def _handle_action_event(self, event) -> None:
        if event.data.get("entry_id") != self._entry.entry_id:
            return
        event_data = action_event_display_data(
            event.data,
            _language(getattr(self, "hass", None)),
        )
        if event_data:
            self._write_event_data(event_data)

    @callback
    def _handle_event_state_changed(self, entry_id: str) -> None:
        if entry_id != self._entry.entry_id:
            return
        event_data = self._entry.runtime_data.event_state.last_event_data
        if event_data:
            self._write_event_data(dict(event_data))

    @callback
    def _write_event_data(self, event_data: dict[str, Any]) -> None:
        event_at = event_data.get("event_at")
        if event_at == self._last_event_at:
            return
        event_key = agent_event_key(event_data)
        if event_key not in self._event_keys:
            return
        self._last_event_at = event_at
        if event_key:
            language = _language(getattr(self, "hass", None))
            self._last_event_data = agent_event_display_data(
                event_data,
                language,
            )
            self._trigger_event(event_key, self._last_event_data.copy())
        self.async_write_ha_state()


def _language(hass: HomeAssistant | None) -> str | None:
    """Return the HA language if the entity is attached to Home Assistant."""

    return getattr(getattr(hass, "config", None), "language", None)


def _display_event_types(
    event_keys: list[str],
    language: str | None = None,
) -> list[str]:
    """Return stable event entity values.

    Home Assistant translates these values through strings.json. The actual
    event_type values must remain stable so automations and event validation do
    not depend on the active UI language.
    """

    return event_keys


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _nested_dict_value(
    data: dict[str, Any],
    parent_key: str,
    child_key: str,
) -> Any:
    parent = data.get(parent_key)
    if not isinstance(parent, dict):
        return None
    return parent.get(child_key)
