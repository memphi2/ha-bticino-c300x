"""Speak a notification over the device speaker with Home Assistant's text-to-speech."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .entity import entry_entity_unique_id, supports_capability
from .entry_config import speech_settings
from .entry_types import BticinoC300XConfigEntry


@dataclass(frozen=True)
class Speech:
    """A message ready to be spoken: the speaker and the speech of the engine."""

    entity_id: str
    media_id: str


def prepare_speech(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, message: str, *,
    engine: str | None = None, language: str | None = None,
) -> Speech:
    """Check everything that can be checked before anything is shown or spoken.

    The engine and language of the call come first, then the ones chosen in
    the settings; without any, Home Assistant takes its default engine.
    """

    if not supports_capability(entry, "announcements"):
        raise ServiceValidationError(
            "The C300X agent does not report that it can speak: update the agent, "
            "or wait until it is reachable, and reload the integration."
        )
    entity_id = er.async_get(hass).async_get_entity_id(
        "media_player", DOMAIN, entry_entity_unique_id(entry, "speaker"),
    )
    state = hass.states.get(entity_id) if entity_id is not None else None
    if entity_id is None or state is None:
        raise ServiceValidationError("The C300X speaker entity is missing or disabled")
    if state.state == STATE_UNAVAILABLE:
        raise ServiceValidationError("The C300X speaker is unavailable; nothing was shown or spoken")
    saved_engine, saved_language = speech_settings(entry)
    try:
        # Loaded only when used: text-to-speech is an optional part of Home Assistant.
        from homeassistant.components import tts  # noqa: PLC0415

        media_id = tts.generate_media_source_id(
            hass, message, engine=engine or saved_engine, language=language or saved_language,
        )
    except (HomeAssistantError, KeyError, ImportError) as err:
        raise ServiceValidationError(
            f"The text-to-speech engine cannot say the C300X notification ({err}); "
            "choose an engine and language under Speech in the C300X settings "
            "or name them in tts_engine and language"
        ) from err
    return Speech(entity_id, media_id)


async def async_speak(hass: HomeAssistant, speech: Speech) -> None:
    """Play the speech on the speaker; it waits for a sound that is still playing."""

    await hass.services.async_call(
        "media_player", "play_media",
        {"entity_id": speech.entity_id, "media_content_id": speech.media_id,
         "media_content_type": "music", "announce": True},
        blocking=True,
    )
