"""Binary sensors for BTicino C300X push events."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import EVENT_AGENT_EVENT_RECEIVED, SIGNAL_EVENT_STATE_CHANGED
from .entity import C300XEntity, supports_capability
from .event_payload import agent_event_key
from .video import active_until_is_active, call_later, event_active_seconds

PARALLEL_UPDATES = 0
VIDEO_WINDOW_EVENTS = {"doorbell_pressed", "doorbell_view_requested"}
VIDEO_WINDOW_CLOSED_EVENTS = {"doorbell_media_closed"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up C300X binary sensors."""

    entities = []
    if supports_capability(entry, "doorbell_video"):
        entities.append(C300XDoorbellVideoAvailableBinarySensor(entry))
    async_add_entities(entities)


class C300XDoorbellVideoAvailableBinarySensor(C300XEntity, BinarySensorEntity):
    """Doorbell video availability from push-event metadata."""

    _attr_should_poll = False
    _attr_translation_key = "doorbell_video_available"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "doorbell_video_available")
        self._available = False
        self._active_until: str | None = None
        self._stream_path: str | None = None
        self._reset = None

    @property
    def is_on(self) -> bool:
        """Return true while a recent doorbell video window is active."""

        event_state = self._entry.runtime_data.event_state
        return _video_window_is_active(
            self._available,
            self._active_until,
        ) or _video_window_is_active(
            bool(event_state.video_available),
            event_state.video_active_until,
        )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return video window metadata."""

        event_state = self._entry.runtime_data.event_state
        attributes = {}
        active_until = (
            self._active_until
            if _video_window_is_active(self._available, self._active_until)
            else event_state.video_active_until
        )
        stream_path = self._stream_path or event_state.video_stream_path
        if active_until and active_until_is_active(active_until):
            attributes["active_until"] = active_until
        if stream_path:
            attributes["stream_path"] = stream_path
        return attributes

    async def async_added_to_hass(self) -> None:
        """Subscribe to runtime event-state updates."""

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
                SIGNAL_EVENT_STATE_CHANGED,
                self._handle_event_state_changed,
            )
        )

    @callback
    def _handle_event_state_changed(self, entry_id: str) -> None:
        """Refresh HA state when runtime video state is cleared centrally."""

        if entry_id != self._entry.entry_id:
            return
        event_state = self._entry.runtime_data.event_state
        if not _video_window_is_active(
            bool(event_state.video_available),
            event_state.video_active_until,
        ):
            self._clear()
        self.async_write_ha_state()

    @callback
    def _handle_agent_event(self, event) -> None:
        if event.data.get("entry_id") != self._entry.entry_id:
            return
        event_type = agent_event_key(event.data)
        if event_type not in VIDEO_WINDOW_EVENTS | VIDEO_WINDOW_CLOSED_EVENTS:
            return
        if event_type in VIDEO_WINDOW_CLOSED_EVENTS:
            self._clear()
            self.async_write_ha_state()
            return
        self._available = bool(event.data.get("video_window_available", True))
        self._active_until = event.data.get("video_active_until") or event.data.get(
            "active_until"
        )
        self._stream_path = event.data.get("stream_path")
        if self._reset:
            self._reset()
        active_seconds = event_active_seconds(event.data)

        @callback
        def _reset(now=None) -> None:
            self._reset = None
            self._clear(cancel_timer=False)
            self.async_write_ha_state()

        self._reset = call_later(self.hass, active_seconds, _reset)
        self.async_write_ha_state()

    def _clear(self, *, cancel_timer: bool = True) -> None:
        if cancel_timer and self._reset:
            self._reset()
        self._reset = None
        self._available = False
        self._active_until = None
        self._stream_path = None


def _video_window_is_active(available: bool, active_until: str | None) -> bool:
    """Return true when a video window is currently usable by HA."""

    if not available:
        return False
    return active_until_is_active(active_until) if active_until else True
