"""Which station, and which outdoor unit, a service call targets.

Services take a Home Assistant target: a station or outdoor unit device, or
one of their entities. Without a target the only loaded station serves the
call. A unit target names the unit; a station target means the current
call's unit, else the default unit (docs/dev/multi-outdoor-units.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    ATTR_FLOOR_ID,
    ATTR_LABEL_ID,
    ENTITY_MATCH_ALL,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .exceptions import service_validation_error
from .schema_compat import vol

_UNIT_MARK = ":unit:"

# A station or outdoor unit device, or one of their entities. The target
# picker also offers areas, floors and labels; they are accepted by the
# schema only to be refused with a message that says what to pick.
_UNSUPPORTED_TARGETS = (ATTR_AREA_ID, ATTR_FLOOR_ID, ATTR_LABEL_ID)
TARGET_FIELDS = {
    vol.Optional(ATTR_DEVICE_ID): vol.Any(str, [str]),
    vol.Optional(ATTR_ENTITY_ID): vol.Any(str, [str]),
    **{vol.Optional(key): vol.Any(str, [str]) for key in _UNSUPPORTED_TARGETS},
}


@dataclass(frozen=True, slots=True)
class ServiceTarget:
    entry: Any
    unit_id: str | None


def _ids(value: Any) -> list[str]:
    if value is None or value == "none":
        return []
    items = [value] if isinstance(value, str) else value
    ids = [item for item in items if isinstance(item, str) and item]
    if ENTITY_MATCH_ALL in ids:
        raise service_validation_error("target_unsupported")
    return ids


def _device_ids(hass: HomeAssistant, call: ServiceCall) -> list[str]:
    if any(_ids(call.data.get(key)) for key in _UNSUPPORTED_TARGETS):
        raise service_validation_error("target_unsupported")
    devices = _ids(call.data.get(ATTR_DEVICE_ID))
    entity_ids = _ids(call.data.get(ATTR_ENTITY_ID))
    if entity_ids:
        entities = er.async_get(hass)
        for entity_id in entity_ids:
            entity = entities.async_get(entity_id)
            if entity is None or entity.platform != DOMAIN or entity.device_id is None:
                raise service_validation_error("unknown_entry")
            devices.append(entity.device_id)
    return list(dict.fromkeys(devices))


def resolve_service_target(hass: HomeAssistant, call: ServiceCall) -> ServiceTarget:
    """The one station (and unit) the call targets, or a translated error."""

    device_ids = _device_ids(hass, call)
    if not device_ids:
        # Ignored, disabled and failed entries cannot serve a call, so they
        # never make the station ambiguous.
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if not entries:
            raise service_validation_error("entry_not_loaded")
        if len(entries) != 1:
            raise service_validation_error("entry_id_required")
        return ServiceTarget(entries[0], None)
    if len(device_ids) != 1:
        # Two stations, or a station and one of its units: the call names one.
        raise service_validation_error("target_ambiguous")
    device = dr.async_get(hass).async_get(device_ids[0])
    if device is None:
        raise service_validation_error("unknown_entry")
    unit_id = next(
        (value.split(_UNIT_MARK, 1)[1] for domain, value in device.identifiers
         if domain == DOMAIN and _UNIT_MARK in value),
        None,
    )
    # A device belongs to one config entry (DeviceEntry.config_entries is
    # deprecated and goes in HA 2027.10).
    entry = hass.config_entries.async_get_entry(device.config_entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise service_validation_error("unknown_entry")
    if entry.state is not ConfigEntryState.LOADED:
        raise service_validation_error("entry_not_loaded")
    return ServiceTarget(entry, unit_id)
