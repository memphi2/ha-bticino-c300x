"""Binary sensors for BTicino C300X push events."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import EVENT_AGENT_EVENT_RECEIVED
from .device_user import media_user_attributes
from .entity import C300XEntity, supports_capability
from .event_payload import agent_event_key

PARALLEL_UPDATES = 0
HOME_CALL_EVENTS = {"home_call_started", "home_call_answered", "home_call_ended"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up C300X binary sensors."""

    entities = []
    if supports_capability(entry, "home_call"):
        entities.append(C300XHomeCallActiveBinarySensor(entry))
    async_add_entities(entities)


class C300XHomeCallActiveBinarySensor(C300XEntity, BinarySensorEntity):
    """Home-call state from native agent SIP events."""

    _attr_should_poll = False
    _attr_translation_key = "home_call_active"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "home_call_active")
        self._running = False
        self._active = False
        self._answered = False
        self._rtp_proxy = False
        self._target_audio_port: int | None = None
        self._rtp_packets = 0
        self._rtcp_packets = 0
        self._last_error: str | None = None

    @property
    def is_on(self) -> bool:
        """Return true while the native agent reports a home call."""

        return self._running or self._active or self._answered

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return native home-call metadata."""

        attributes: dict[str, Any] = {
            "phase": self._phase,
            "answered": self._answered,
            "rtp_proxy": self._rtp_proxy,
            "rtp_packets": self._rtp_packets,
            "rtcp_packets": self._rtcp_packets,
            **media_user_attributes(self._entry),
        }
        if self._target_audio_port is not None:
            attributes["target_audio_port"] = self._target_audio_port
        if self._last_error:
            attributes["last_error"] = self._last_error
        return attributes

    @property
    def _phase(self) -> str:
        if self._answered:
            return "answered"
        if self._running or self._active:
            return "ringing"
        return "idle"

    async def async_added_to_hass(self) -> None:
        """Subscribe to native agent event updates."""

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
        event_type = agent_event_key(event.data)
        if event_type not in HOME_CALL_EVENTS:
            return
        payload = _home_call_payload(event.data)
        if event_type == "home_call_ended":
            self._apply_status(
                {
                    **payload,
                    "running": False,
                    "active": False,
                    "answered": False,
                    "rtp_proxy": False,
                    "target_audio_port": 0,
                }
            )
        elif event_type == "home_call_answered":
            self._apply_status(
                {
                    **payload,
                    "running": payload.get("running", True),
                    "active": payload.get("active", True),
                    "answered": payload.get("answered", True),
                }
            )
        else:
            self._apply_status(
                {
                    **payload,
                    "running": payload.get("running", True),
                    "active": payload.get("active", True),
                    "answered": payload.get("answered", False),
                }
            )
        self.async_write_ha_state()

    def _apply_status(self, status: dict[str, Any]) -> None:
        self._running = bool(status.get("running"))
        self._active = bool(status.get("active"))
        self._answered = bool(status.get("answered"))
        self._rtp_proxy = bool(status.get("rtp_proxy"))
        self._target_audio_port = _optional_int(status.get("target_audio_port"))
        self._rtp_packets = _optional_int(status.get("rtp_packets"), 0) or 0
        self._rtcp_packets = _optional_int(status.get("rtcp_packets"), 0) or 0
        self._last_error = (
            str(status["last_error"]) if status.get("last_error") else None
        )


def _home_call_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = data.get("home_call")
    if isinstance(payload, dict):
        return payload
    nested = data.get("data")
    if isinstance(nested, dict):
        payload = nested.get("home_call")
        if isinstance(payload, dict):
            return payload
        return nested
    return {}


def _optional_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
