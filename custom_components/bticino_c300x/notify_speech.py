"""Speak a notification over the device speaker with Home Assistant's text-to-speech."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .entity import entry_entity_unique_id, supports_capability
from .entry_types import BticinoC300XConfigEntry


def speaker_entity_id(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> str:
    """Return the speaker of this device, or say why nothing can be spoken."""

    if not supports_capability(entry, "announcements"):
        raise ServiceValidationError(
            "Spoken C300X notifications need an update of the device agent. "
            "Update it and reload the integration before sending."
        )
    entity_id = er.async_get(hass).async_get_entity_id(
        "media_player", DOMAIN, entry_entity_unique_id(entry, "speaker"),
    )
    if entity_id is None or hass.states.get(entity_id) is None:
        raise ServiceValidationError("The C300X speaker entity is missing or disabled")
    return entity_id


async def async_speak(
    hass: HomeAssistant, entity_id: str, message: str, *,
    engine: str | None = None, language: str | None = None,
) -> None:
    """Have a text-to-speech engine say the message and play it on the speaker.

    Without an engine Home Assistant takes its default one.
    """

    # Loaded only when used: text-to-speech is an optional part of Home Assistant.
    from homeassistant.components import tts  # noqa: PLC0415

    try:
        media_id = tts.generate_media_source_id(hass, message, engine=engine, language=language)
    except (HomeAssistantError, KeyError) as err:
        raise ServiceValidationError(
            "No text-to-speech engine for the C300X notification; set one up in "
            "Home Assistant or name it in tts_engine"
        ) from err
    await hass.services.async_call(
        "media_player", "play_media",
        {"entity_id": entity_id, "media_content_id": media_id,
         "media_content_type": "music", "announce": True},
        blocking=True,
    )
