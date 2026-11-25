"""Keep the call registry in step with the agent's answers and events."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api_errors import C300XAgentApiError
from .call_registry import (
    SIGNAL_CALLS_CHANGED,
    SIGNAL_OUTDOOR_UNITS_CHANGED,
    C300XCallRegistry,
    units_from_stored,
    units_to_stored,
)
from .capabilities import capability_is_supported
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


def calls_supported(capabilities: Any) -> bool:
    """The agent owns calls and outdoor units (API 2)."""

    return isinstance(capabilities, dict) and capability_is_supported(capabilities, "calls")


def entry_call_registry(entry: BticinoC300XConfigEntry) -> C300XCallRegistry | None:
    registry = getattr(getattr(entry, "runtime_data", None), "calls", None)
    return registry if isinstance(registry, C300XCallRegistry) else None


def load_stored_units(entry: BticinoC300XConfigEntry, registry: C300XCallRegistry) -> None:
    """Start from the units the entry kept, so a station that is offline keeps its units."""

    payload = units_from_stored(entry.data.get(CONF_OUTDOOR_UNITS))
    if payload is not None:
        registry.set_units(payload)


async def async_refresh_units(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> bool:
    """Read the station's units; keep them in the entry and tell the platforms."""

    runtime = getattr(entry, "runtime_data", None)
    registry = entry_call_registry(entry)
    if runtime is None or registry is None or not calls_supported(runtime.capabilities):
        return False
    try:
        payload = await runtime.api.async_outdoor_units()
    except C300XAgentApiError as err:
        _LOGGER.debug("C300X outdoor units could not be read: %s", compact_error_text(err))
        return False
    if getattr(entry, "runtime_data", None) is not runtime:
        return False
    if not registry.set_units(payload):
        return True
    stored = units_to_stored(payload)
    if entry.data.get(CONF_OUTDOOR_UNITS) != stored:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_OUTDOOR_UNITS: stored},
        )
    async_dispatcher_send(hass, SIGNAL_OUTDOOR_UNITS_CHANGED, entry.entry_id)
    return True


async def async_refresh_calls(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    """Read the agent's calls, after a restart of the agent or of Home Assistant."""

    runtime = getattr(entry, "runtime_data", None)
    registry = entry_call_registry(entry)
    if runtime is None or registry is None or not calls_supported(runtime.capabilities):
        return
    try:
        payload = await runtime.api.async_calls()
    except C300XAgentApiError as err:
        _LOGGER.debug("C300X calls could not be read: %s", compact_error_text(err))
        return
    if getattr(entry, "runtime_data", None) is runtime:
        registry.set_calls(payload)
        async_dispatcher_send(hass, SIGNAL_CALLS_CHANGED, entry.entry_id)


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
        _schedule(hass, entry, async_refresh_units(hass, entry), "units")
        return {}
    if event_type == "outdoor_units_changed":
        _schedule(hass, entry, async_refresh_units(hass, entry), "units")
        return {}
    call = registry.apply_event(event_type, data) if event_type in CALL_EVENT_TYPES else None
    if call is not None:
        async_dispatcher_send(hass, SIGNAL_CALLS_CHANGED, entry.entry_id)
    call_id = call.call_id if call is not None else data.get("call_id")
    if not isinstance(call_id, str):
        return {}
    known = registry.call(call_id)
    unit = known.unit if known is not None else data.get("unit")
    fields: dict[str, Any] = {"call_id": call_id, "unit_id": unit if isinstance(unit, str) else None}
    if fields["unit_id"] is not None:
        fields["unit_name"] = registry.unit_name(fields["unit_id"])
    return fields


def _schedule(hass: HomeAssistant, entry: BticinoC300XConfigEntry, work: Any, name: str) -> None:
    hass.async_create_background_task(work, f"{DOMAIN}_{name}_{entry.entry_id}")
