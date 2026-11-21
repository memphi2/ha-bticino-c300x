"""Select entities for BTicino C300X."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import C300XAgentApiError
from .capabilities import entry_maintenance_action_is_advertised
from .const import (
    DOMAIN,
    EVENT_AGENT_EVENT_RECEIVED,
    SIGNAL_AGENT_INFO_CHANGED,
    SIGNAL_CONNECTION_STATE_CHANGED,
    SIGNAL_FORWARDING_CHANGED,
    SIGNAL_SETTING_STATE,
    SMARTPHONE_FORWARDING_MODES,
)
from .entity import C300XEntity, supports_capability
from .entity import (
    async_refresh_initial_states as _async_refresh_initial_states,
)
from .entry_types import BticinoC300XConfigEntry
from .event_payload import agent_event_key
from .forwarding import coerce_forwarding_mode_state, forwarding_state_from_value
from .select_camera_resolution import C300XCameraResolutionSelect

if TYPE_CHECKING:
    from homeassistant.core import Event

PARALLEL_UPDATES = 1

# The options are the agent's mode keys; their texts come from the state
# translations. "unprovisioned" -- a device with no smartphone pairing at
# all -- is a state the agent reports but not a mode that can be chosen, so
# it is not an option: the entity state is then unknown and the value is
# surfaced through extra_state_attributes and media readiness instead. Do
# not add it to the options: Home Assistant only rejects an unselectable
# option while it is absent from the list.


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
    if entry_maintenance_action_is_advertised(entry, "camera_resolution"):
        entities.append(C300XCameraResolutionSelect(entry))
    if entities:
        await _async_refresh_initial_states(entities)
        async_add_entities(entities)


class C300XSmartphoneForwardingModeSelect(C300XEntity, SelectEntity):
    """Select the C300X smartphone forwarding mode."""

    _attr_should_poll = False
    _attr_translation_key = "smartphone_forwarding_mode"
    _attr_options = list(SMARTPHONE_FORWARDING_MODES)

    def __init__(self, entry: BticinoC300XConfigEntry) -> None:
        super().__init__(entry, "smartphone_forwarding_mode")
        self._mode: int | None = None
        self._state = "unknown"
        self._attr_available = True
        self._state_generation = 0

    @property
    def current_option(self) -> str | None:
        """Return the current forwarding mode."""

        return self._state if self._state in SMARTPHONE_FORWARDING_MODES else None

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        """Return raw forwarding state metadata."""

        return {"mode": self._mode, "state": self._state}

    async def async_select_option(self, option: str) -> None:
        """Set the forwarding mode."""

        if option not in SMARTPHONE_FORWARDING_MODES:
            return
        generation = self._state_generation
        try:
            status = await self._entry.runtime_data.api.async_set_smartphone_forwarding_mode(
                option
            )
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X smartphone forwarding update failed") from err
        if generation == self._state_generation:
            self._state_generation += 1
            self._apply_status(status)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh forwarding state through the active read-only endpoint."""

        generation = self._state_generation
        try:
            status = await self._entry.runtime_data.api.async_smartphone_forwarding_status()
        except C300XAgentApiError:
            if generation == self._state_generation:
                self._attr_available = False
            return
        if generation == self._state_generation:
            self._apply_status(status)

    def _apply_status(self, status: Mapping[str, Any]) -> None:
        """Take a reading from the agent, whether asked for or pushed."""

        mode = status.get("mode")
        state = status.get("state")
        self._mode = mode if isinstance(mode, int) else None
        self._state = state if isinstance(state, str) else "unknown"
        # The shared state store holds a real forwarding state or nothing:
        # "unknown" is this class's display sentinel for "no reading", and
        # readiness must not score it as a real non-Home-Assistant mode. It
        # must not clear a known state either -- the webhook preserves that
        # on an unparseable push, and the push callback runs synchronously
        # right afterwards on the very same store.
        forwarding_state = forwarding_state_from_value(self._state)
        event_state = self._entry.runtime_data.event_state
        if forwarding_state not in (
            None, getattr(event_state, "smartphone_forwarding_mode", None)
        ):
            event_state.smartphone_forwarding_mode = forwarding_state
            # Media readiness reads the store; a reading that did not come
            # with a device event would otherwise not reach it.
            if self.hass is not None:
                async_dispatcher_send(
                    self.hass, SIGNAL_FORWARDING_CHANGED, self._entry.entry_id
                )
        self._attr_available = forwarding_state is not None and status.get("available") is not False

    async def async_added_to_hass(self) -> None:
        """Subscribe to push state updates."""

        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_SETTING_STATE, self._handle_setting_state,
        ))
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_AGENT_EVENT_RECEIVED,
                self._handle_agent_event,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_AGENT_INFO_CHANGED, self._handle_agent_restarted
            )
        )

    @callback
    def _handle_agent_restarted(self, entry_id: str) -> None:
        """Ask again: a restarted agent reads the mode without reporting it.

        The read also lets the agent switch its Ring Call receiver to match.
        """

        if entry_id != self._entry.entry_id:
            return
        self._cancel_reconnect_refresh()
        self._reconnect_refresh_task = self.hass.async_create_background_task(
            self._async_refresh_after_reconnect(),
            f"{DOMAIN}_refresh_after_restart_{self._attr_unique_id}",
        )

    @callback
    def _handle_agent_event(self, event: Event) -> None:
        event_type = agent_event_key(event.data) or ""
        self._handle_setting_state(event.data.get("entry_id"), event_type, event.data)

    @callback
    def _handle_setting_state(self, entry_id: str | None, event_type: str, data: Any) -> None:
        if entry_id != self._entry.entry_id or not isinstance(data, Mapping):
            return
        if event_type != "smartphone_forwarding_changed":
            return
        status = _normalize_smartphone_forwarding_event(data)
        if data.get("available") is not False and status["state"] == "unknown":
            return
        self._state_generation += 1
        if data.get("available") is False:
            self._attr_available = False
        else:
            self._apply_status(status)
        self.async_write_ha_state()


class C300XAudioCodecSelect(C300XEntity, SelectEntity):
    """Select the on-demand/intercom audio codec (speex or native PCMU).

    Disabled by default; firmware 3.0.x runs PCMU from the factory. Once enabled,
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
        self._pending_refresh_task: asyncio.Task[None] | None = None
        self._removed = False
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
        try:
            if option == "pcmu":
                status = await api.async_apply_audio_codec()
            elif option == "speex":
                status = await api.async_restore_audio_codec()
            else:
                return
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X audio codec change failed") from err
        self._apply_action_result(option, status)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh the codec state from the device."""

        runtime = self._entry.runtime_data
        try:
            status = await runtime.api.async_audio_codec_status()
        except C300XAgentApiError:
            if not self._removed and self._entry.runtime_data is runtime:
                self._attr_available = False
            return
        if self._removed or self._entry.runtime_data is not runtime:
            return
        self._apply_status(status)

    def _apply_action_result(self, target: str, status: Mapping[str, Any]) -> None:
        # apply/restore patch the config files, which the status reports as the
        # target codec immediately -- but the device's media service, linphone
        # and the agent only adopt it on reboot. Until the codec is actually live, keep
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
        if self._removed or entry_id != self._entry.entry_id or not self._pending_option:
            return
        if not self._entry.runtime_data.connection_state.available:
            self._seen_reboot_gap = True
            return
        if self._resolving_pending:
            return
        self._resolving_pending = True
        self._pending_refresh_task = self.hass.async_create_task(self._async_resolve_pending())

    @callback
    def _cancel_pending_refresh(self) -> None:
        self._removed = True
        if self._pending_refresh_task is not None:
            self._pending_refresh_task.cancel()
            self._pending_refresh_task = None

    async def _async_resolve_pending(self) -> None:
        runtime = self._entry.runtime_data
        try:
            await self.async_update()
        finally:
            self._resolving_pending = False
        if not self._removed and self._entry.runtime_data is runtime:
            self.async_write_ha_state()

    def _clear_pending(self) -> None:
        self._pending_option = None
        self._seen_reboot_gap = False

    async def async_added_to_hass(self) -> None:
        """Resolve pending codec changes when the agent reconnects post-reboot."""

        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_pending_refresh)
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
