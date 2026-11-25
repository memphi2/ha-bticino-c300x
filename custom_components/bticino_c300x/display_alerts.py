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
    display_notification_service_error,
    notification_id,
    notification_payload,
    show_notification,
)
from .entry_types import BticinoC300XConfigEntry
from .model_names import C100X, C300X, entry_model
from .schema_compat import vol

_LOGGER = logging.getLogger(__name__)


def _integer(value: Any) -> int:
    if type(value) is not int:
        raise vol.Invalid("expected an integer")
    return value


def _boolean(value: Any) -> bool:
    if type(value) is not bool:
        raise vol.Invalid("expected true or false")
    return value


CHANNELS = ("display", "tts", "led")
_NOTICE_FIELDS = ("severity", "expires_in", "notification_id")


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
        **{vol.Optional(channel): _boolean for channel in CHANNELS},
        vol.Optional("tts_engine"): vol.All(str, vol.Length(min=1, max=255)),
        vol.Optional("language"): vol.All(str, vol.Length(min=1, max=35)),
    }
)


def _invalid(reason: str, model: str) -> ServiceValidationError:
    return ServiceValidationError(f"Invalid {model} display notification: {reason}")


def _switch_channels(data: dict[str, Any], options: dict[str, Any], model: str) -> set[str]:
    """The switched-on channels; fields of a channel that is off are refused."""

    channels = {channel for channel in CHANNELS if options.get(channel)}
    if not channels:
        raise _invalid("switch on at least one of display, tts and led", model)
    if "display" not in channels and (
        data.get("wake_duration") or data.get("sound_duration")
    ):
        raise _invalid(
            "wake_duration and sound_duration need display: true; "
            "leave them out or set them to 0",
            model,
        )
    if "tts" not in channels and ("tts_engine" in data or "language" in data):
        raise _invalid("tts_engine and language need tts: true", model)
    if channels == {"tts"} and any(field in data for field in _NOTICE_FIELDS):
        raise _invalid(
            "severity, expires_in and notification_id need display or led; "
            "a message that is only spoken stores no notice",
            model,
        )
    return channels


def alert_options(data: dict[str, Any] | None, model: str = C300X) -> dict[str, Any]:
    """Check the data of a notification before anything is shown or spoken.

    The result names the channels: display, tts and led (the stored notice
    counts for the LED), plus led_required when the LED itself was asked for.
    """

    data = {} if data is None else data
    if "mode" in data:
        raise _invalid("mode was removed; use the switches display, tts and led", model)
    try:
        options = dict(ALERT_DATA_SCHEMA(data))
    except vol.Invalid as err:
        raise _invalid(str(err), model) from err
    if any(channel in data for channel in CHANNELS):
        channels = _switch_channels(data, options, model)
        led = "led" in channels
    else:
        # Without switches: the display, and the notice lights the LED where
        # the agent supports it, without requiring that support.
        channels = _switch_channels({**data, "display": True}, {**options, "display": True}, model)
        led = True
    options.update(
        display="display" in channels, tts="tts" in channels, led=led,
        led_required="led" in channels,
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
    model = entry_model(entry)
    try:
        options = alert_options(data, model)
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
        raise _invalid(str(err), model) from err

    if not entry_device_ui_enabled_or_patch_active(entry):
        raise ServiceValidationError(f"{model} display integration is disabled")
    runtime = entry.runtime_data
    if options["display"] and runtime.capabilities.get("display_alerts") is not True:
        if model == C100X:
            # A C100X has no Display patch: its pages come with the activation.
            raise ServiceValidationError(
                "C100X display alerts need the Home Assistant pages on the display. "
                "Activate them with Activate display pages on the device page and "
                "reload the integration before sending."
            )
        raise ServiceValidationError(
            f"{model} display alerts require an update of the device agent and "
            "Display patch. Update both and reload the integration before sending."
        )
    if options["led_required"] and runtime.capabilities.get("memo_led") is not True:
        raise ServiceValidationError(
            f"{model} led requires a device agent that reports memo LED support. "
            "Update the agent and reload the integration, or leave led off "
            "if the device has no memo LED."
        )
    # The C100X display has no alert tone it could stop for a call.
    c100x = runtime.capabilities.get("c100x_display")
    silent = isinstance(c100x, dict) and c100x.get("alert_sound") is False
    if silent and options.get("sound_duration"):
        raise ServiceValidationError(
            "Invalid C100X display notification: the C100X display plays no alert "
            "tone; leave out sound_duration"
        )
    try:
        show_notification(hass, entry, notice, led=options["led"])
    except ValueError as err:
        raise display_notification_service_error(err, entry) from err
    if not options["display"]:
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
        # Spoken text takes the place of the tone: both need the one speaker.
        # The C100X display has no alert tone at all.
        "sound_duration": 0 if options["tts"] or silent else options.get("sound_duration", 30),
        "expires_in": notice["expires_in"],
    }
    try:
        result = await runtime.api.async_send_display_alert(payload)
    except C300XAgentApiError as err:
        # Keep the HA notice: a lost response cannot prove GUI non-delivery.
        raise HomeAssistantError(
            f"{model} display alert delivery was not confirmed: {err}. "
            "The HA notice remains stored; wake and sound are not confirmed."
        ) from err
    if isinstance(result, dict) and result.get("suppressed") is True:
        _LOGGER.info(
            "C300X notification stored in HA without popup, wake or sound: "
            "the device GUI reports a protected screen or call. No effects are queued"
        )
