"""Reserve readable notification action names across unloads and restarts."""

from __future__ import annotations

import asyncio
from hashlib import sha256

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .const import DEFAULT_NAME, DOMAIN
from .entry_types import BticinoC300XConfigEntry

_NAMES = f"{DOMAIN}_notify_names"


class NotifyNames:
    """Keep action ownership independent of entry setup order and display names."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self.lock = asyncio.Lock()
        self._store = Store[dict[str, str]](hass, 1, _NAMES, atomic_writes=True)
        self._names: dict[str, str] | None = None
        self._unsaved = False

    async def _async_load(self) -> dict[str, str]:
        """Load validated ownership and finish any interrupted write."""
        if self._names is None:
            names = await self._store.async_load()
            if names is None:
                names = {}
            if not isinstance(names, dict) or any(
                not isinstance(key, str) or not isinstance(name, str)
                or not (name == DOMAIN or name.startswith(f"{DOMAIN}_"))
                or slugify(name) != name
                for key, name in names.items()
            ) or len(set(names.values())) != len(names):
                raise ServiceValidationError("Invalid C300X notification action reservations")
            self._names = names
        if self._unsaved:
            await self._store.async_save(self._names)
            self._unsaved = False
        return self._names

    async def _async_save(self, names: dict[str, str]) -> None:
        self._names = names
        self._unsaved = True
        await self._store.async_save(names)
        self._unsaved = False

    async def async_name(self, entry: BticinoC300XConfigEntry) -> str:
        """Reserve before registration; caller holds the setup lock."""
        names = await self._async_load()
        if name := names.get(entry.entry_id):
            return name
        title = slugify(entry.title.strip())
        name = DOMAIN if not title or title == slugify(DEFAULT_NAME) else f"{DOMAIN}_{title}"
        if name in names.values():
            suffix = sha256(entry.entry_id.encode()).hexdigest()[:8]
            name = f"{name}_{suffix}"
        if name in names.values():
            raise ServiceValidationError(f"Notification action name collision: notify.{name}")
        if self._hass.services.has_service("notify", name):
            raise ServiceValidationError(f"Notification service notify.{name} already exists")
        await self._async_save({**names, entry.entry_id: name})
        return name

    async def async_remove(self, entry_id: str) -> None:
        """Release a deleted entry's reservation; caller holds the setup lock."""
        names = await self._async_load()
        if entry_id in names:
            await self._async_save({key: name for key, name in names.items() if key != entry_id})


def notify_names(hass: HomeAssistant) -> NotifyNames:
    """Return the shared reservation owner, including while entries are unloaded."""
    if _NAMES not in hass.data:
        hass.data[_NAMES] = NotifyNames(hass)
    names: NotifyNames = hass.data[_NAMES]
    return names


async def async_remove_name(hass: HomeAssistant, entry_id: str) -> None:
    """Free a name after permanent entry removal, never on ordinary unload."""
    names = notify_names(hass)
    async with names.lock:
        await names.async_remove(entry_id)
