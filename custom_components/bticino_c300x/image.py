"""Last visitor image of every outdoor unit."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .agent_contracts import OutdoorUnit
from .entity import entry_video_enabled, supports_capability
from .entry_types import BticinoC300XConfigEntry
from .unit_entity import async_track_outdoor_units
from .unit_platforms import C300XUnitLastVisitorImage

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """One image per outdoor unit, when visitor images can be taken."""

    if not (entry_video_enabled(entry) and supports_capability(entry, "doorbell_video")):
        return

    def build(unit: OutdoorUnit) -> list[ImageEntity]:
        return [C300XUnitLastVisitorImage(hass, entry, unit)]

    async_track_outdoor_units(hass, entry, async_add_entities, build)
