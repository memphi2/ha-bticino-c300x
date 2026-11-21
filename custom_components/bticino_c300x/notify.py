"""Legacy notify services retain the data needed for native display alerts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from homeassistant.components.notify.legacy import BaseNotificationService
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.service import async_set_service_schema
from homeassistant.setup import async_setup_component

from .capabilities import entry_device_ui_enabled_or_patch_active
from .const import DOMAIN
from .display_alerts import alert_options, async_send_display_alert
from .entry_types import BticinoC300XConfigEntry
from .notify_names import notify_names
from .notify_speech import async_speak, prepare_speech
from .service_authorization import authorized_service

_SERVICES = f"{DOMAIN}_notify_services"


@callback
def _async_set_notify_description(
    hass: HomeAssistant, name: str, service: C300XNotificationService,
) -> None:
    """Describe the fixed display target without changing runtime validation."""
    title = service.entry.title.strip() or "BTicino C300X"
    fields = deepcopy(service.services_dict["notify"]["fields"])
    fields.pop("target", None)
    fields["data"].update({
        "description": (
            "Optional display settings: severity is info (default), warning or error. "
            "wake_duration and sound_duration are integer seconds from 0 to 300 "
            "(both default to 30; 0 disables the respective effect). "
            "expires_in is 1 to 604800 seconds (default 3600). "
            "notification_id replaces an existing notification with the same ID "
            "(1-64 lowercase letters, digits, underscores or hyphens). "
            "mode is display (default), speech (the message is only spoken over the "
            "device speaker) or both (shown and spoken; no tone unless sound_duration "
            "is given). tts_engine names the text-to-speech entity, for example "
            "tts.piper; without it Home Assistant uses its default. language is optional."
        ),
        "example": {"severity": "info", "wake_duration": 30, "sound_duration": 30},
    })
    async_set_service_schema(hass, "notify", name, {
        "name": f"Send a display notification to {title}",
        "description": (
            "Shows a notification on this BTicino C300X display. By default, wakes "
            "the screen and plays sound for 30 seconds. Requires an updated device "
            "agent and Display patch."
        ),
        "fields": fields,
    })


class C300XNotificationService(BaseNotificationService):
    """One fixed device target, with no URLs, audio files or commands in its data."""

    def __init__(self, entry: BticinoC300XConfigEntry, name: str) -> None:
        self.entry = entry
        self.name = name
        self.closed = False
        self._unsubscribe: Callable[[], None] = lambda: None
        self._pending: set[asyncio.Task[Any]] = set()

    async def _async_notify_message_service(self, service: ServiceCall) -> None:
        # The legacy base silently omits an explicitly empty title.
        if "title" in service.data and not service.data["title"]:
            raise ServiceValidationError("C300X notification title must not be empty")
        # Authorize before the legacy base drops the caller's ServiceCall context.
        await authorized_service(
            self.hass, "show_display_notification",
            super()._async_notify_message_service, lambda _call: self.entry,
        )(service)

    async def async_send_message(self, message: str, **kwargs: Any) -> None:
        if self.closed:
            raise ServiceValidationError("C300X display notification service is unloaded")
        if "target" in kwargs:
            raise ServiceValidationError("C300X notify targets are fixed per config entry")
        # Everything is checked before anything is shown or spoken.
        options = alert_options(kwargs.get("data"))
        mode = options["mode"]
        speech = None if mode == "display" else prepare_speech(
            self.hass, self.entry, message,
            engine=options.get("tts_engine"), language=options.get("language"),
        )
        task = asyncio.current_task()
        assert task is not None
        self._pending.add(task)
        unconfirmed: HomeAssistantError | None = None
        try:
            if mode != "speech":
                try:
                    await async_send_display_alert(
                        self.hass, self.entry, message,
                        title=kwargs.get("title", "Home Assistant"), data=kwargs.get("data"),
                    )
                except ServiceValidationError:
                    raise
                except HomeAssistantError as err:
                    # The display may still have it; the spoken part is not lost with it.
                    if speech is None:
                        raise
                    unconfirmed = err
            if speech is not None:
                await async_speak(self.hass, speech)
            if unconfirmed is not None:
                raise unconfirmed
        finally:
            self._pending.discard(task)

    @callback
    def close(self) -> None:
        """Stop waiting for in-flight delivery when this entry is unloaded."""
        if self.closed:
            return
        self.closed = True
        self._unsubscribe()
        for task in self._pending:
            task.cancel()

    def owns_service(self) -> bool:
        """Check handler ownership before changing the public registry."""
        registered = self.hass.services.async_services().get("notify", {}).get(self.name)
        return registered is not None and registered.job.target == self._async_notify_message_service

    async def async_update_description(
        self, _hass: HomeAssistant, _entry: BticinoC300XConfigEntry,
    ) -> None:
        """Refresh the label after a title edit without renaming the action."""
        if not self.closed and self.owns_service():
            _async_set_notify_description(self.hass, self.name, self)

    @callback
    def remove(self) -> None:
        """Remove only the handler this instance registered."""
        self.close()
        if self.owns_service():
            self.hass.services.async_remove("notify", self.name)


async def async_setup_notify(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry
) -> None:
    """Register before native support is installed, but only for enabled UI."""
    if not entry_device_ui_enabled_or_patch_active(entry):
        return
    if not await async_setup_component(hass, "notify", {}):
        raise ServiceValidationError("Could not set up Home Assistant notify")
    names = notify_names(hass)
    async with names.lock:
        if entry.entry_id in hass.data.get(_SERVICES, {}):
            return
        name = await names.async_name(entry)
        await _async_register_notify(hass, entry, name)


async def _async_register_notify(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, name: str,
) -> None:
    """Register a reserved name without replacing any existing handler."""
    if hass.services.has_service("notify", name):
        raise ServiceValidationError(f"Notification service notify.{name} already exists")
    service = C300XNotificationService(entry, name)
    try:
        await service.async_setup(hass, name, name)
        if hass.services.has_service("notify", name):
            raise ServiceValidationError(f"Notification service notify.{name} already exists")
        await service.async_register_services()
        _async_set_notify_description(hass, name, service)
        service._unsubscribe = entry.add_update_listener(service.async_update_description)
        hass.data.setdefault(_SERVICES, {})[entry.entry_id] = service
        entry.async_on_unload(lambda: async_unload_notify(hass, entry))
    except (Exception, asyncio.CancelledError):
        service.remove()
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
        service.remove()
    if not services:
        hass.data.pop(_SERVICES, None)
