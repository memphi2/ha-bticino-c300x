"""Validate HA notifications and deliver one bounded native display alert."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .api_errors import C300XAgentApiError
from .capabilities import entry_device_ui_enabled_or_patch_active
from .display_notifications import (
    SHOW_SCHEMA,
    notification_id,
    notification_payload,
    show_notification,
)
from .entry_types import BticinoC300XConfigEntry
from .schema_compat import vol

_LOGGER = logging.getLogger(__name__)


def _integer(value: Any) -> int:
    if type(value) is not int:
        raise vol.Invalid("expected an integer")
    return value


ALERT_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional("severity", default="info"): vol.In({"info", "warning", "error"}),
        vol.Optional("wake_duration", default=30): vol.All(
            _integer, vol.Range(min=0, max=300)
        ),
        vol.Optional("sound_duration"): vol.All(
            _integer, vol.Range(min=0, max=300)
        ),
        vol.Optional("notification_id"): notification_id,
        vol.Optional("expires_in", default=3600): vol.All(
            _integer, vol.Range(min=1, max=604800)
        ),
        vol.Optional("mode", default="display"): vol.In({"display", "speech", "both", "led"}),
        vol.Optional("tts_engine"): vol.All(str, vol.Length(min=1, max=255)),
        vol.Optional("language"): vol.All(str, vol.Length(min=1, max=35)),
    }
)


def alert_options(data: dict[str, Any] | None) -> dict[str, Any]:
    """Check the data of a notification before anything is shown or spoken."""

    try:
        options = dict(ALERT_DATA_SCHEMA({} if data is None else data))
    except vol.Invalid as err:
        raise ServiceValidationError(f"Invalid C300X display notification: {err}") from err
    if options["mode"] == "led" and data is not None and (
        data.get("wake_duration") or data.get("sound_duration")
        or "tts_engine" in data or "language" in data
    ):
        raise ServiceValidationError(
            "Invalid C300X display notification: mode led does not wake, play sound "
            "or speak; omit positive durations and TTS settings"
        )
    if options["mode"] == "both" and options.get("sound_duration"):
        # The tone would hold the speaker the speech needs.
        raise ServiceValidationError(
            "Invalid C300X display notification: mode both speaks instead of the tone; "
            "leave out sound_duration"
        )
    return options


async def async_send_display_alert(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    message: str,
    *,
    title: str = "Home Assistant",
    data: dict[str, Any] | None = None,
) -> None:
    """Store the revision first, then request GUI delivery without retries."""
    try:
        options = alert_options(data)
        severity = options["severity"]
        notice = SHOW_SCHEMA({
            "notification_id": options.get("notification_id", uuid4().hex),
            "title": title,
            "message": message,
            "icon": "info" if severity == "info" else "warning",
            "priority": {"info": "normal", "warning": "important", "error": "urgent"}[severity],
            "expires_in": options["expires_in"],
        })
    except vol.Invalid as err:
        raise ServiceValidationError(f"Invalid C300X display notification: {err}") from err

    if not entry_device_ui_enabled_or_patch_active(entry):
        raise ServiceValidationError("C300X display integration is disabled")
    runtime = entry.runtime_data
    if options["mode"] == "led":
        if runtime.capabilities.get("memo_led") is not True:
            raise ServiceValidationError(
                "C300X mode led requires a device agent that reports memo LED support. "
                "Update the agent and reload the integration, or choose another mode "
                "if the device has no memo LED."
            )
    elif runtime.capabilities.get("display_alerts") is not True:
        raise ServiceValidationError(
            "C300X display alerts require an update of the device agent and "
            "Display patch. Update both and reload the integration before sending."
        )
    try:
        show_notification(hass, entry, notice)
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err
    if options["mode"] == "led":
        return
    stored = next(
        item for item in notification_payload(entry)
        if item["id"] == notice["notification_id"]
    )
    payload = {
        "id": uuid4().hex,
        "notification_id": stored["id"],
        "revision": stored["revision"],
        "severity": severity,
        "title": stored["title"],
        "message": stored["message"],
        "wake_duration": options["wake_duration"],
        # Spoken text takes the place of the tone.
        "sound_duration": 0 if options["mode"] == "both" else options.get("sound_duration", 30),
        "expires_in": notice["expires_in"],
    }
    try:
        result = await runtime.api.async_send_display_alert(payload)
    except C300XAgentApiError as err:
        # Keep the HA notice: a lost response cannot prove GUI non-delivery.
        raise HomeAssistantError(
            f"C300X display alert delivery was not confirmed: {err}. "
            "The HA notice remains stored; wake and sound are not confirmed."
        ) from err
    if isinstance(result, dict) and result.get("suppressed") is True:
        _LOGGER.info(
            "C300X notification stored in HA without popup, wake or sound: "
            "the device GUI reports a protected screen or call. No effects are queued"
        )
