"""The device speaker as a media player: a target for text-to-speech and sounds."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    async_process_play_media_url,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .announcements import (
    ANNOUNCEMENT_DEFAULT_VOLUME,
    announcement_volume,
    async_sound_for_device,
)
from .api import C300XAgentApiError
from .entity import C300XEntity, supports_capability
from .entry_types import BticinoC300XConfigEntry

_LOGGER = logging.getLogger(__name__)
# The agent knows after a moment whether the device let it have the speaker.
_START_CHECK_SECONDS = 0.4
_POLL_SECONDS = 0.5
_RESULT_ERRORS = {
    "device_busy": "The C300X is using its speaker (call, ring or message); nothing was played",
    "sound_path_failed": "The C300X could not switch its speaker on",
    "play_failed": "The C300X could not play the sound",
    "failed": "The C300X announcement ended unexpectedly",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the speaker where the agent can play sound."""

    if supports_capability(entry, "announcements"):
        async_add_entities([C300XSpeaker(entry)])


class C300XSpeaker(C300XEntity, MediaPlayerEntity, RestoreEntity):
    """Plays one sound at a time; a door call always takes the speaker."""

    _attr_should_poll = False
    _attr_translation_key = "speaker"
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_media_content_type = MediaType.MUSIC
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.VOLUME_SET
    )

    def __init__(self, entry: BticinoC300XConfigEntry) -> None:
        super().__init__(entry, "speaker")
        self._attr_state = MediaPlayerState.IDLE
        self._attr_volume_level = ANNOUNCEMENT_DEFAULT_VOLUME
        self._watch: asyncio.Task[None] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        level = last.attributes.get("volume_level") if last is not None else None
        if isinstance(level, (int, float)) and 0 < level <= 1:
            self._attr_volume_level = float(level)

    async def async_will_remove_from_hass(self) -> None:
        if self._watch is not None:
            self._watch.cancel()
        await super().async_will_remove_from_hass()

    async def async_set_volume_level(self, volume: float) -> None:
        """Keep the volume for the next sound; a playing one keeps its own."""

        self._attr_volume_level = max(0.01, min(1.0, volume))
        self.async_write_ha_state()

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any,
    ) -> None:
        """Play speech or another sound; a second one waits for nothing and is refused."""

        if media_source.is_media_source_id(media_id):
            media_id = (
                await media_source.async_resolve_media(self.hass, media_id, self.entity_id)
            ).url
        sound = await async_sound_for_device(async_process_play_media_url(self.hass, media_id))
        api = self._entry.runtime_data.api
        try:
            await api.async_play_announcement(
                sound, announcement_volume(self._attr_volume_level or ANNOUNCEMENT_DEFAULT_VOLUME),
            )
        except C300XAgentApiError as err:
            raise HomeAssistantError(f"C300X announcement was not played: {err}") from err
        if self._watch is not None:
            self._watch.cancel()
            self._watch = None
        await asyncio.sleep(_START_CHECK_SECONDS)
        result = await self._async_result()
        if result is None:
            self._attr_state = MediaPlayerState.PLAYING
            self.async_write_ha_state()
            self._watch = self.hass.async_create_background_task(
                self._async_watch(), f"{self.entity_id} announcement",
            )
            return
        self._finish(result)
        if result in _RESULT_ERRORS:
            raise HomeAssistantError(_RESULT_ERRORS[result])

    async def async_media_stop(self) -> None:
        try:
            await self._entry.runtime_data.api.async_stop_announcement()
        except C300XAgentApiError as err:
            raise HomeAssistantError(f"C300X announcement was not stopped: {err}") from err

    async def async_browse_media(
        self, media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        return await media_source.async_browse_media(
            self.hass, media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
        )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """How the last sound ended, for automations that care about a cut-off."""

        return {"last_result": self._last_result}

    _last_result = ""

    async def _async_result(self) -> str | None:
        """How the sound ended, or nothing while it plays."""

        try:
            status = await self._entry.runtime_data.api.async_announcement_status()
        except C300XAgentApiError:
            return "failed"
        return None if status.get("playing") else str(status.get("result") or "failed")

    def _finish(self, result: str) -> None:
        self._last_result = result
        self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def _async_watch(self) -> None:
        """Follow the sound until the device says it is over."""

        result = None
        while result is None:
            await asyncio.sleep(_POLL_SECONDS)
            result = await self._async_result()
        self._finish(result)
        if result in _RESULT_ERRORS:
            _LOGGER.warning("%s", _RESULT_ERRORS[result])
