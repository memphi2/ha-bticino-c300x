"""Identities of the station, its outdoor units and their entities.

The station is named by the agent's device id (``c300x-<mac>``), not by the
config entry: deleting and re-adding the entry gives the same identifiers.
The config flow stores it with a new entry; an entry from before 3.1.0 gets
it from the identity migration (docs/dev/multi-outdoor-units.md).
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


class StationIdUnknown(LookupError):
    """The entry has no station id: an entry from before 3.1.0 not migrated yet."""


def station_id_known(entry: Any) -> bool:
    """True once the entry carries the station id; until then no entity can be built."""

    return valid_station_id(getattr(entry, "data", {}).get(CONF_STATION_ID)) is not None


def station_id(entry: Any) -> str:
    """The station's identity: the agent's device id the entry stores."""

    value = valid_station_id(getattr(entry, "data", {}).get(CONF_STATION_ID))
    if value is None:
        raise StationIdUnknown(getattr(entry, "entry_id", None))
    return value


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


# The media camera's key: one camera of the station, whichever unit is the default.
MEDIA_CAMERA_KEY = "doorbell_camera"


def media_camera_unique_id(entry: Any) -> str | None:
    """The camera with ring, answer and on-demand video.

    It sits on the default unit's device, but its id is the station's: it
    stays the same entity when the station's default unit changes. None
    while the entry waits for its station id.
    """

    return station_unique_id(entry, MEDIA_CAMERA_KEY) if station_id_known(entry) else None
