"""Shared Home Assistant config-entry types for BTicino C300X."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .data import BticinoC300XRuntimeData

    type BticinoC300XConfigEntry = ConfigEntry[BticinoC300XRuntimeData]
else:
    BticinoC300XConfigEntry = Any
