"""The device speaker as a media player: a target for text-to-speech and sounds."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Self

from homeassistant.components import media_source
from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.browse_media import (
    BrowseMedia,
    async_process_play_media_url,
)
from homeassistant.components.media_player.const import (
    MediaPlayerDeviceClass,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from .announcements import (
    ANNOUNCEMENT_DEFAULT_VOLUME,
    announcement_seconds,
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
# Longer than the agent itself lets a sound run (its length and 30 seconds).
_END_MARGIN_SECONDS = 35
_PLAYING = "playing"
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


def media_url_for_ffmpeg(hass: HomeAssistant, media_id: str) -> str:
    """Address ffmpeg on the Home Assistant host fetches the media from.

    Media of Home Assistant itself is fetched over its internal address,
    or over the loopback where there is none, never through the external one.
    """

    url = async_process_play_media_url(hass, media_id, allow_relative_url=True)
    if not url.startswith("/"):
        return url
    try:
        base = get_url(hass, allow_external=False, allow_cloud=False)
    except NoURLAvailableError:
        api = hass.config.api
        if api is None:
            raise HomeAssistantError("The address of Home Assistant is unknown") from None
        base = f"{'https' if api.use_ssl else 'http'}://127.0.0.1:{api.port}"
    return f"{base}{url}"


@dataclass
class _SpeakerData(ExtraStoredData):
    """The volume, kept even while the entity was unavailable."""

    volume: float

    def as_dict(self) -> dict[str, Any]:
        return {"volume": self.volume}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self | None:
        volume = data.get("volume")
        if isinstance(volume, (int, float)) and not isinstance(volume, bool) and 0 < volume <= 1:
            return cls(float(volume))
        return None


class C300XSpeaker(C300XEntity, MediaPlayerEntity, RestoreEntity):
    """Plays one sound after the other; a door call always takes the speaker."""

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
    _last_result = ""

    def __init__(self, entry: BticinoC300XConfigEntry) -> None:
        super().__init__(entry, "speaker")
        self._attr_state = MediaPlayerState.IDLE
        self._attr_volume_level = ANNOUNCEMENT_DEFAULT_VOLUME
        # One upload and one sound at a time: the agent holds a single file.
        self._turn = asyncio.Lock()
        self._follow: asyncio.Task[None] | None = None
        self._removed = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        data = await self.async_get_last_extra_data()
        saved = _SpeakerData.from_dict(data.as_dict()) if data is not None else None
        if saved is not None:
            self._attr_volume_level = saved.volume

    @property
    def extra_restore_state_data(self) -> _SpeakerData:
        return _SpeakerData(float(self._attr_volume_level or ANNOUNCEMENT_DEFAULT_VOLUME))

    async def async_will_remove_from_hass(self) -> None:
        self._removed = True
        if self._follow is not None:
            self._follow.cancel()
        await super().async_will_remove_from_hass()

    async def async_set_volume_level(self, volume: float) -> None:
        """Keep the volume for the next sound; a playing one keeps its own."""

        self._attr_volume_level = max(0.01, min(1.0, volume))
        self.async_write_ha_state()

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any,
    ) -> None:
        """Play speech or another sound once the one before it is over."""

        if media_source.is_media_source_id(media_id):
            media_id = (
                await media_source.async_resolve_media(self.hass, media_id, self.entity_id)
            ).url
        sound = await async_sound_for_device(media_url_for_ffmpeg(self.hass, media_id))
        async with self._turn:
            if self._follow is not None:
                await asyncio.wait({self._follow})
            if self._removed:
                raise HomeAssistantError("The C300X speaker was removed; nothing was played")
            api = self._entry.runtime_data.api
            try:
                await api.async_play_announcement(
                    sound, announcement_volume(self._attr_volume_level or ANNOUNCEMENT_DEFAULT_VOLUME),
                )
            except C300XAgentApiError as err:
                raise HomeAssistantError(f"C300X announcement was not played: {err}") from err
            deadline = time.monotonic() + announcement_seconds(sound) + _END_MARGIN_SECONDS
            await asyncio.sleep(_START_CHECK_SECONDS)
            result = await self._async_check()
            if result in (_PLAYING, None):
                # Not known yet, or the agent did not answer this once.
                self._attr_state = MediaPlayerState.PLAYING
                self.async_write_ha_state()
                self._follow = self.hass.async_create_background_task(
                    self._async_follow(deadline), f"{self.entity_id} announcement",
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

    async def _async_check(self) -> str | None:
        """'playing', how the sound ended, or None when the agent gave no answer."""

        try:
            status = await self._entry.runtime_data.api.async_announcement_status()
        except C300XAgentApiError:
            return None
        if not isinstance(status, dict):
            return None
        if status.get("playing") is True:
            return _PLAYING
        result = status.get("result")
        return result if isinstance(result, str) and result else None

    def _finish(self, result: str) -> None:
        self._last_result = result
        self._attr_state = MediaPlayerState.IDLE
        if not self._removed:
            self.async_write_ha_state()

    async def _async_follow(self, deadline: float) -> None:
        """Follow the sound until the device says it is over.

        A status read that fails is tried again; the agent ends every sound
        by the deadline, so after it the sound is over whatever the answer.
        """

        result: str | None = None
        try:
            while result in (_PLAYING, None) and time.monotonic() < deadline:
                await asyncio.sleep(_POLL_SECONDS)
                result = await self._async_check()
        except Exception:
            _LOGGER.exception("Following the C300X announcement failed")
            result = None
        if result in (_PLAYING, None):
            result = "unknown"
        self._finish(result)
        if result in _RESULT_ERRORS:
            _LOGGER.warning("%s", _RESULT_ERRORS[result])
