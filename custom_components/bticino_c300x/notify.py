"""Legacy notify services retain the data needed for native display alerts."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.notify.legacy import BaseNotificationService
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component

from .capabilities import entry_device_ui_enabled_or_patch_active
from .const import DOMAIN
from .display_alerts import async_send_display_alert
from .entry_types import BticinoC300XConfigEntry

_SERVICES = f"{DOMAIN}_notify_services"


class C300XNotificationService(BaseNotificationService):
    """One fixed device target, with no URLs, audio files or commands."""

    def __init__(self, entry: BticinoC300XConfigEntry) -> None:
        self.entry = entry
        self.closed = False
        self._pending: set[asyncio.Task[Any]] = set()

    async def _async_notify_message_service(self, service: ServiceCall) -> None:
        # The legacy base silently omits an explicitly empty title.
        if "title" in service.data and not service.data["title"]:
            raise ServiceValidationError("C300X notification title must not be empty")
        await super()._async_notify_message_service(service)

    async def async_send_message(self, message: str, **kwargs: Any) -> None:
        if self.closed:
            raise ServiceValidationError("C300X display notification service is unloaded")
        if "target" in kwargs:
            raise ServiceValidationError("C300X notify targets are fixed per config entry")
        task = asyncio.current_task()
        assert task is not None
        self._pending.add(task)
        try:
            await async_send_display_alert(
                self.hass, self.entry, message,
                title=kwargs.get("title", "Home Assistant"), data=kwargs.get("data"),
            )
        finally:
            self._pending.discard(task)

    @callback
    def close(self) -> None:
        """Stop waiting for in-flight delivery when this entry is unloaded."""
        self.closed = True
        for task in self._pending:
            task.cancel()


async def async_setup_notify(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry
) -> None:
    """Register before native support is installed, but only for enabled UI."""
    if not entry_device_ui_enabled_or_patch_active(entry):
        return
    if entry.entry_id in hass.data.get(_SERVICES, {}):
        return
    if not await async_setup_component(hass, "notify", {}):
        raise ServiceValidationError("Could not set up Home Assistant notify")
    name = f"{DOMAIN}_{entry.entry_id.lower()}"
    if hass.services.has_service("notify", name):
        raise ServiceValidationError(f"Notification service notify.{name} already exists")
    service = C300XNotificationService(entry)
    try:
        await service.async_setup(hass, name, name)
        await service.async_register_services()
        hass.data.setdefault(_SERVICES, {})[entry.entry_id] = service
        entry.async_on_unload(lambda: async_unload_notify(hass, entry))
    except (Exception, asyncio.CancelledError):
        service.close()
        hass.services.async_remove("notify", name)
        services = hass.data.get(_SERVICES, {})
        services.pop(entry.entry_id, None)
        if not services:
            hass.data.pop(_SERVICES, None)
        raise


@callback
def async_unload_notify(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    """Synchronously remove only this entry's service, also on setup rollback."""
    services = hass.data.get(_SERVICES, {})
    if service := services.pop(entry.entry_id, None):
        service.close()
        hass.services.async_remove("notify", f"{DOMAIN}_{entry.entry_id.lower()}")
    if not services:
        hass.data.pop(_SERVICES, None)
