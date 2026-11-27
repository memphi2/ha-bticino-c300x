"""Keep the call registry in step with the agent's answers and events."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from ._api_calls import normalize_station_state, valid_unit_id
from .api_errors import C300XAgentApiError
from .call_registry import (
    SIGNAL_CALLS_CHANGED,
    SIGNAL_DOORS_CHANGED,
    SIGNAL_OUTDOOR_UNITS_CHANGED,
    C300XCallRegistry,
    units_from_stored,
    units_to_stored,
)
from .const import CONF_OUTDOOR_UNITS, DOMAIN
from .entry_types import BticinoC300XConfigEntry
from .error_text import compact_error_text

_LOGGER = logging.getLogger(__name__)

CALL_EVENT_TYPES = frozenset({
    "doorbell_pressed",
    "call_caller_identified",
    "call_answered",
    "call_view_started",
    "call_ended",
})
_UNIT_BINDING_EVENTS = frozenset({"doorbell_pressed", "call_caller_identified", "call_view_started"})
DOOR_EVENT_STATES = {"door_opened": "open", "door_closed": "closed"}


def entry_call_registry(entry: BticinoC300XConfigEntry) -> C300XCallRegistry | None:
    registry = getattr(getattr(entry, "runtime_data", None), "calls", None)
    return registry if isinstance(registry, C300XCallRegistry) else None


def load_stored_units(entry: BticinoC300XConfigEntry, registry: C300XCallRegistry) -> None:
    """Start from the units the entry kept, so a station that is offline keeps its units."""

    payload = units_from_stored(entry.data.get(CONF_OUTDOOR_UNITS))
    if payload is not None:
        registry.set_units(payload)


async def async_refresh_units(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, *, during_setup: bool = False,
) -> bool:
    """Read the station's units; keep them in the entry and tell the platforms.

    Outside setup, units that make the identity migration possible (the read
    at setup failed) reload the entry: the migration runs before the platforms.
    """

    runtime = getattr(entry, "runtime_data", None)
    registry = entry_call_registry(entry)
    if runtime is None or registry is None:
        return False
    try:
        payload = await runtime.api.async_outdoor_units()
    except C300XAgentApiError as err:
        _LOGGER.debug("C300X outdoor units could not be read: %s", compact_error_text(err))
        return False
    if getattr(entry, "runtime_data", None) is not runtime:
        return False
    doors = registry.door_states()
    changed = registry.set_units(payload)
    if registry.door_states() != doors:
        async_dispatcher_send(hass, SIGNAL_DOORS_CHANGED, entry.entry_id)
    if not during_setup and _identity_migration_pending(entry, runtime, registry):
        _LOGGER.info("C300X entry %s reloads to take the station's identity", entry.entry_id)
        hass.config_entries.async_schedule_reload(entry.entry_id)
    if not changed:
        return True
    stored = units_to_stored(payload)
    if entry.data.get(CONF_OUTDOOR_UNITS) != stored:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_OUTDOOR_UNITS: stored},
        )
    async_dispatcher_send(hass, SIGNAL_OUTDOOR_UNITS_CHANGED, entry.entry_id)
    return True


def _identity_migration_pending(entry: BticinoC300XConfigEntry, runtime: Any, registry: C300XCallRegistry) -> bool:
    from .identity_migration import identity_migration_needed

    station = getattr(runtime, "agent_info", {}).get("device_id")
    return registry.default_unit is not None and identity_migration_needed(
        entry, station if isinstance(station, str) else None,
    )


async def async_refresh_calls(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    """Read the agent's calls, after a restart of the agent or of Home Assistant."""

    runtime = getattr(entry, "runtime_data", None)
    registry = entry_call_registry(entry)
    if runtime is None or registry is None:
        return
    try:
        payload = await runtime.api.async_calls()
    except C300XAgentApiError as err:
        _LOGGER.debug("C300X calls could not be read: %s", compact_error_text(err))
        return
    if getattr(entry, "runtime_data", None) is runtime:
        registry.set_calls(payload)
        async_dispatcher_send(hass, SIGNAL_CALLS_CHANGED, entry.entry_id)


async def async_resync(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    """Units and calls again from the agent.

    After every event registration pass (setup, reconnect, renewal) and an
    agent restart: a callback the agent could not deliver is never resent.
    """

    await async_refresh_units(hass, entry)
    await async_refresh_calls(hass, entry)


@callback
def async_apply_call_event(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    event_type: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Mirror one agent event; returns the call fields the HA event carries."""

    registry = entry_call_registry(entry)
    if registry is None:
        return {}
    if event_type == "agent_restarted":
        registry.clear_calls()
        async_dispatcher_send(hass, SIGNAL_CALLS_CHANGED, entry.entry_id)
        if registry.clear_door_states():
            async_dispatcher_send(hass, SIGNAL_DOORS_CHANGED, entry.entry_id)
        _schedule(hass, entry, async_resync(hass, entry), "units_calls")
        return {}
    if event_type == "outdoor_units_changed":
        _schedule(hass, entry, async_refresh_units(hass, entry), "units")
        return {}
    if event_type == "station_call_state":
        # The station's own call state; the agent ends and answers calls with it.
        registry.station_state = normalize_station_state(data)
        async_dispatcher_send(hass, SIGNAL_CALLS_CHANGED, entry.entry_id)
    if event_type in DOOR_EVENT_STATES:
        _apply_door_event(hass, entry, registry, valid_unit_id(data.get("unit")), DOOR_EVENT_STATES[event_type])
    call = registry.apply_event(event_type, data) if event_type in CALL_EVENT_TYPES else None
    ring_unit = None
    if call is not None:
        async_dispatcher_send(hass, SIGNAL_CALLS_CHANGED, entry.entry_id)
        if event_type == "doorbell_pressed" and registry.has_other_live_call(call.call_id):
            # The agent does not resend a lost callback: a call it ended may
            # still look live here and would shadow this ring. Ask the agent.
            _schedule(hass, entry, async_refresh_calls(hass, entry), "calls")
        ring_unit = registry.unit_ring(event_type, call)
        if event_type in _UNIT_BINDING_EVENTS and call.unit is not None and call.unit not in registry.units:
            # A unit the station had not listed; outdoor_units.changed may be lost.
            _schedule(hass, entry, async_refresh_units(hass, entry), "units")
    call_id = call.call_id if call is not None else data.get("call_id")
    known = registry.call(call_id) if isinstance(call_id, str) else None
    # A door frame names its unit also outside a call.
    unit = known.unit if known is not None else data.get("unit")
    fields: dict[str, Any] = {
        "call_id": call_id if isinstance(call_id, str) else None,
        "unit": unit if isinstance(unit, str) else None,
    }
    if ring_unit is not None:
        # The unit whose doorbell event entity fires for this event.
        fields["ring_unit_id"] = ring_unit
    return fields


def _apply_door_event(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, registry: C300XCallRegistry,
    unit_id: str | None, state: str,
) -> None:
    """A unit's door contact opened or closed."""

    if registry.set_door(unit_id, state):
        async_dispatcher_send(hass, SIGNAL_DOORS_CHANGED, entry.entry_id)
        return
    unit = registry.unit(unit_id)
    if unit is None or unit.door is None:
        # The unit's first door frame: the agent lists the contact now, and
        # its outdoor_units.changed may be lost.
        _schedule(hass, entry, async_refresh_units(hass, entry), "units")


def _schedule(hass: HomeAssistant, entry: BticinoC300XConfigEntry, work: Any, name: str) -> None:
    hass.async_create_background_task(work, f"{DOMAIN}_{name}_{entry.entry_id}")
