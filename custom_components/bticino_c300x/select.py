"""Select entities for BTicino C300X."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import C300XAgentApiError
from .capabilities import entry_maintenance_action_is_advertised
from .const import (
    EVENT_AGENT_EVENT_RECEIVED,
    SIGNAL_CONNECTION_STATE_CHANGED,
    SMARTPHONE_FORWARDING_MODES,
    SMARTPHONE_FORWARDING_STATE_UNPROVISIONED,
)
from .entity import C300XEntity, supports_capability
from .entity import (
    async_refresh_initial_states as _async_refresh_initial_states,
)
from .entry_types import BticinoC300XConfigEntry
from .event_payload import agent_event_key
from .forwarding import coerce_forwarding_mode_state, forwarding_state_from_value

if TYPE_CHECKING:
    from homeassistant.core import Event

PARALLEL_UPDATES = 1

# Labels for every state the agent reports, including "unprovisioned" -- a
# device with no smartphone pairing at all. That one is deliberately not in
# _FORWARDING_OPTION_LABELS below, so Home Assistant drops it from the entity
# state (SelectEntity.state returns None for a current_option outside options)
# and the value is surfaced through extra_state_attributes and media readiness
# instead. Do not "fix" that by adding it to the options: Home Assistant only
# rejects an unselectable option while it is absent from the list, so adding it
# would let a select_option call through to async_select_option, which discards
# an unsupported mode without a word.
_FORWARDING_STATE_LABELS = {
    "enabled": "Smartphone",
    "homeassistant": "Home Assistant",
    "blocked": "Blocked",
    SMARTPHONE_FORWARDING_STATE_UNPROVISIONED: "Unprovisioned",
}
_FORWARDING_OPTION_LABELS = {
    mode: label
    for mode, label in _FORWARDING_STATE_LABELS.items()
    if mode in SMARTPHONE_FORWARDING_MODES
}
_FORWARDING_MODE_BY_LABEL = {
    label: mode for mode, label in _FORWARDING_OPTION_LABELS.items()
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up C300X select entities."""

    entities: list[SelectEntity] = []
    if supports_capability(entry, "smartphone_forwarding"):
        entities.append(C300XSmartphoneForwardingModeSelect(entry))
    if entry_maintenance_action_is_advertised(entry, "audio_codec_apply"):
        entities.append(C300XAudioCodecSelect(entry))
    if entities:
        await _async_refresh_initial_states(entities)
        async_add_entities(entities)


class C300XSmartphoneForwardingModeSelect(C300XEntity, SelectEntity):
    """Select the C300X smartphone forwarding mode."""

    _attr_should_poll = False
    _attr_translation_key = "smartphone_forwarding_mode"
    _attr_options = list(_FORWARDING_OPTION_LABELS.values())

    def __init__(self, entry: BticinoC300XConfigEntry) -> None:
        super().__init__(entry, "smartphone_forwarding_mode")
        self._mode: int | None = None
        self._state = "unknown"
        self._attr_available = True

    @property
    def current_option(self) -> str | None:
        """Return the current forwarding mode."""

        return _FORWARDING_STATE_LABELS.get(self._state)

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        """Return raw forwarding state metadata."""

        return {"mode": self._mode, "state": self._state}

    async def async_select_option(self, option: str) -> None:
        """Set the forwarding mode."""

        mode = _FORWARDING_MODE_BY_LABEL.get(option, option)
        if mode not in SMARTPHONE_FORWARDING_MODES:
            return
        status = await self._entry.runtime_data.api.async_set_smartphone_forwarding_mode(
            mode
        )
        self._apply_status(status)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh forwarding state through the active read-only endpoint."""

        try:
            status = await self._entry.runtime_data.api.async_smartphone_forwarding_status()
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._apply_status(status)

    def _apply_status(self, status: Mapping[str, Any]) -> None:
        mode = status.get("mode")
        state = status.get("state", "unknown")
        self._mode = mode if isinstance(mode, int) else None
        self._state = state if isinstance(state, str) else "unknown"
        # The shared state store holds a real forwarding state or nothing:
        # "unknown" is this class's display sentinel for "no reading", and
        # readiness must not score it as a real non-Home-Assistant mode.
        forwarding_state = forwarding_state_from_value(self._state)
        if forwarding_state is not None:
            # "unknown" means no reading, so it must not clear a known state --
            # the webhook preserves it on an unparseable push, and this callback
            # runs synchronously right afterwards on the very same store.
            self._entry.runtime_data.event_state.smartphone_forwarding_mode = (
                forwarding_state
            )
        self._attr_available = True

    async def async_added_to_hass(self) -> None:
        """Subscribe to push state updates."""

        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_AGENT_EVENT_RECEIVED,
                self._handle_agent_event,
            )
        )

    @callback
    def _handle_agent_event(self, event: Event) -> None:
        if event.data.get("entry_id") != self._entry.entry_id:
            return
        event_type = agent_event_key(event.data) or ""
        if not event_type.startswith("smartphone_forwarding_"):
            return
        forwarding = _normalize_smartphone_forwarding_event(event.data)
        state = forwarding.get("state")
        mode = forwarding.get("mode")
        self._state = state if isinstance(state, str) else "unknown"
        self._mode = mode if isinstance(mode, int) else None
        # The shared state store holds a real forwarding state or nothing:
        # "unknown" is this class's display sentinel for "no reading", and
        # readiness must not score it as a real non-Home-Assistant mode.
        forwarding_state = forwarding_state_from_value(self._state)
        if forwarding_state is not None:
            # "unknown" means no reading, so it must not clear a known state --
            # the webhook preserves it on an unparseable push, and this callback
            # runs synchronously right afterwards on the very same store.
            self._entry.runtime_data.event_state.smartphone_forwarding_mode = (
                forwarding_state
            )
        self._attr_available = True
        self.async_write_ha_state()


class C300XAudioCodecSelect(C300XEntity, SelectEntity):
    """Select the on-demand/intercom audio codec (speex or native PCMU).

    Disabled by default because native PCMU mode is experimental. Once enabled,
    this is the single source of truth in HA for the codec mode: the card reads
    this entity's state (no agent round-trip). Choosing an option patches the
    device config and reboots for the change to take effect.
    """

    _attr_should_poll = False
    _attr_translation_key = "audio_codec"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_options = ["speex", "pcmu"]

    def __init__(self, entry: BticinoC300XConfigEntry) -> None:
        super().__init__(entry, "audio_codec")
        self._state = "unknown"
        self._pending_option: str | None = None
        self._seen_reboot_gap = False
        self._resolving_pending = False
        self._attr_available = True

    @property
    def current_option(self) -> str | None:
        """Return the codec the device is currently running (None while partial)."""

        return self._state if self._state in ("speex", "pcmu") else None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Expose the live state plus any codec change staged for a reboot."""

        return {"state": self._state, "pending_option": self._pending_option}

    async def async_select_option(self, option: str) -> None:
        """Switch the device codec (apply=PCMU, restore=speex); reboots."""

        api = self._entry.runtime_data.api
        if option == "pcmu":
            status = await api.async_apply_audio_codec()
        elif option == "speex":
            status = await api.async_restore_audio_codec()
        else:
            return
        self._apply_action_result(option, status)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh the codec state from the device."""

        try:
            status = await self._entry.runtime_data.api.async_audio_codec_status()
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._apply_status(status)

    def _apply_action_result(self, target: str, status: Mapping[str, Any]) -> None:
        # apply/restore patch the config files, which the status reports as the
        # target codec immediately -- but bt_av_media, linphone and the agent
        # only adopt it on reboot. Until the codec is actually live, keep
        # reporting the running codec (the card keys its gain path off this
        # entity) and surface the change as pending. It resolves when the agent
        # actually restarts: the connection drops and comes back, and we then
        # re-read the now-live codec (see _handle_reboot_reconnect) -- no polling.
        if bool(status.get("reboot_required")):
            self._pending_option = target
            self._seen_reboot_gap = False
        else:
            self._clear_pending()
            self._state = target
            self._record_running_codec()
        self._attr_available = True

    @callback
    def _handle_reboot_reconnect(self, entry_id: str) -> None:
        # Resolve a pending codec change without polling by re-reading the live
        # codec whenever the agent is reachable. A codec change only goes live on
        # a device restart; `_apply_status` keeps it pending until the device
        # actually reports the new *running* codec, so re-reading is safe even
        # before the reboot and never optimistically claims a switch the device
        # did not make. We do NOT require first observing a down->up availability
        # gap: a reboot triggered by the codec apply often re-registers within the
        # reconnect grace window, so `available` never flips and the gap is never
        # seen -- which used to leave the change stuck pending until a manual
        # reload. (The gap flag is still recorded for legacy agents that report
        # only the on-disk codec; see `_apply_status`.)
        if entry_id != self._entry.entry_id or not self._pending_option:
            return
        if not self._entry.runtime_data.connection_state.available:
            self._seen_reboot_gap = True
            return
        if self._resolving_pending:
            return
        self._resolving_pending = True
        self.hass.async_create_task(self._async_resolve_pending())

    async def _async_resolve_pending(self) -> None:
        try:
            await self.async_update()
        finally:
            self._resolving_pending = False
        self.async_write_ha_state()

    def _clear_pending(self) -> None:
        self._pending_option = None
        self._seen_reboot_gap = False

    async def async_added_to_hass(self) -> None:
        """Resolve pending codec changes when the agent reconnects post-reboot."""

        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CONNECTION_STATE_CHANGED,
                self._handle_reboot_reconnect,
            )
        )

    def _apply_status(self, status: Mapping[str, Any]) -> None:
        # New agents report both the running codec and the configured on-disk
        # target. Older agents only reported the on-disk state; if we already
        # know a change is pending, keep the live state until a reboot gap was
        # observed and resolved through _handle_reboot_reconnect.
        has_running_state = isinstance(status.get("running_state"), str)
        if self._pending_option and not self._seen_reboot_gap and not has_running_state:
            self._attr_available = True
            return
        state = status.get("running_state", status.get("state", "unknown"))
        self._state = state if isinstance(state, str) else "unknown"
        configured_state = status.get("configured_state", status.get("state"))
        if (
            bool(status.get("reboot_required"))
            and configured_state in ("speex", "pcmu")
            and configured_state != self._state
        ):
            self._pending_option = str(configured_state)
            self._seen_reboot_gap = False
        else:
            self._clear_pending()
        self._record_running_codec()
        self._attr_available = True

    def _record_running_codec(self) -> None:
        # Mirror the resolved running codec into shared runtime state so
        # consumers (ring-capture talkback) still see it while this entity is
        # unavailable during an agent-connection blip. Only real codecs are
        # published; "unknown" leaves the last-known value untouched.
        if self._state in ("speex", "pcmu"):
            self._entry.runtime_data.event_state.audio_codec = self._state


def _normalize_smartphone_forwarding_event(
    payload: Mapping[str, Any],
) -> dict[str, str | int | None]:
    return coerce_forwarding_mode_state(payload.get("mode"), payload.get("state"))
