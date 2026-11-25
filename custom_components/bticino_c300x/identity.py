"""Identities of the station, its outdoor units and their entities.

The station is named by the agent's device id (``c300x-<mac>``), not by the
config entry: deleting and re-adding the entry gives the same identifiers.
Until the first setup with an agent that reports outdoor units the entry id
stands in, which is what 2.x used (docs/dev/multi-outdoor-units.md).
"""

from __future__ import annotations

import re
from typing import Any

from .const import CONF_OUTDOOR_UNITS, CONF_STATION_ID, DOMAIN

_STATION_ID = re.compile(r"[a-z0-9][a-z0-9._:-]{0,63}\Z")
_MAC_STATION_ID = re.compile(r"c300x-([0-9a-f]{12})\Z")


def valid_station_id(value: Any) -> str | None:
    """The agent's device id when it can name a device, else None."""

    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if _STATION_ID.fullmatch(value) else None


def station_id(entry: Any) -> str:
    """The station's identity: the agent's device id once known, else the entry id."""

    return valid_station_id(getattr(entry, "data", {}).get(CONF_STATION_ID)) or str(entry.entry_id)


def station_mac(entry: Any) -> str | None:
    """The MAC address the station id carries, as ``aa:bb:cc:dd:ee:ff``."""

    match = _MAC_STATION_ID.fullmatch(station_id(entry))
    if match is None:
        return None
    digits = match.group(1)
    return ":".join(digits[index:index + 2] for index in range(0, 12, 2))


def station_unique_id(entry: Any, key: str) -> str:
    """Unique id of a station entity; the only place that formats it."""

    return f"{station_id(entry)}_{key}"


def unit_unique_id(entry: Any, unit_id: str, key: str) -> str:
    """Unique id of an outdoor unit entity."""

    return f"{station_id(entry)}_unit_{unit_id}_{key}"


def station_device_identifier(entry: Any) -> tuple[str, str]:
    return (DOMAIN, station_id(entry))


def unit_device_identifier(entry: Any, unit_id: str) -> tuple[str, str]:
    return (DOMAIN, f"{station_id(entry)}:unit:{unit_id}")


def default_unit_id(entry: Any) -> str | None:
    """The default outdoor unit the entry last learned from the station."""

    stored = getattr(entry, "data", {}).get(CONF_OUTDOOR_UNITS)
    value = stored.get("default_unit") if isinstance(stored, dict) else None
    return value if isinstance(value, str) and value else None


def media_camera_unique_id(entry: Any) -> str:
    """The camera with ring, answer and on-demand video: the default unit's."""

    unit = default_unit_id(entry)
    return unit_unique_id(entry, unit, "camera") if unit else station_unique_id(entry, "doorbell_camera")
