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
# The agent says within moments whether the device let it have the speaker.
_START_POLL_SECONDS = 0.1
_START_SECONDS = 10
_POLL_SECONDS = 0.5
# Longer than the agent lets a sound run: its length and 30 seconds.
_END_MARGIN_SECONDS = 50
# The agent switches the speaker off after a sound before it takes the next;
# a sound it still holds, for example from before a reload, is waited for too.
_BUSY_WAIT_SECONDS = 180
# Conversions running at the same time.
_CONVERSIONS = 2
_PLAYING = "playing"
# Playing, but the device has not let the agent have its speaker yet.
_STARTING = "starting"
_NOT_OVER = (_PLAYING, _STARTING, None)
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
        base = get_url(hass, allow_external=False, allow_cloud=False, allow_ip=True)
    except NoURLAvailableError:
        api = hass.config.api
        if api is None:
            raise HomeAssistantError("The address of Home Assistant is unknown") from None
        base = f"{'https' if api.use_ssl else 'http'}://127.0.0.1:{api.port}"
    return f"{base}{url}"


def _log_error(started: asyncio.Future[str | None]) -> None:
    if started.result() is not None:
        _LOGGER.warning("%s", started.result())


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
        self._converting = asyncio.Semaphore(_CONVERSIONS)
        self._sound: asyncio.Task[None] | None = None
        # Done once the last request has handed its sound over or given up: one
        # sound at a time, as the agent holds a single file, and in the order
        # they were asked for, whichever is converted first.
        self._last_request: asyncio.Future[None] | None = None
        self._removed = False

    async def async_added_to_hass(self) -> None:
        # Home Assistant adds the same entity again after its id was renamed.
        self._removed = False
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
        if self._sound is not None:
            self._sound.cancel()
        await super().async_will_remove_from_hass()

    async def async_set_volume_level(self, volume: float) -> None:
        """Keep the volume for the next sound; a playing one keeps its own."""

        self._attr_volume_level = max(0.01, min(1.0, volume))
        self.async_write_ha_state()

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any,
    ) -> None:
        """Play speech or another sound once the one before it is over.

        The sound is played and followed by a task of its own, so a caller that
        gives up does not leave a sound playing that the speaker no longer knows.
        """

        before, handed = self._last_request, self.hass.loop.create_future()
        self._last_request = handed
        try:
            if media_source.is_media_source_id(media_id):
                media_id = (
                    await media_source.async_resolve_media(self.hass, media_id, self.entity_id)
                ).url
            async with self._converting:
                sound = await async_sound_for_device(media_url_for_ffmpeg(self.hass, media_id))
            if before is not None:
                await asyncio.wait({before})
            if self._sound is not None:
                await asyncio.wait({self._sound})
            if self._removed:
                raise HomeAssistantError("The C300X speaker was removed; nothing was played")
            started: asyncio.Future[str | None] = self.hass.loop.create_future()
            self._sound = self.hass.async_create_background_task(
                self._async_sound(sound, started), f"{self.entity_id} announcement",
            )
        finally:
            # One that gives up early still keeps its place until the one before has its turn.
            if before is None or before.done():
                handed.set_result(None)
            else:
                before.add_done_callback(lambda _before: handed.set_result(None))
        try:
            error = await asyncio.shield(started)
        except asyncio.CancelledError:
            # Nobody waits for the answer any more: the log still gets it.
            started.add_done_callback(_log_error)
            raise
        if error is not None:
            raise HomeAssistantError(error)

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
        """'starting', 'playing', how the sound ended, or None when the agent gave no answer."""

        try:
            status = await self._entry.runtime_data.api.async_announcement_status()
        except C300XAgentApiError:
            return None
        if not isinstance(status, dict):
            return None
        if status.get("playing") is True:
            return _PLAYING if status.get("started") is True else _STARTING
        # The sound is over once the agent tells how, also while it still
        # switches the speaker off, which after a door call takes a while.
        result = status.get("result")
        if isinstance(result, str) and result:
            return result
        # Not playing and no result: the agent was restarted, the sound is gone.
        return "unknown"

    async def _async_until_free(self) -> None:
        """Wait until the agent has switched the speaker off after the last sound."""

        deadline = time.monotonic() + _BUSY_WAIT_SECONDS
        while time.monotonic() < deadline:
            try:
                status = await self._entry.runtime_data.api.async_announcement_status()
            except C300XAgentApiError:
                status = None
            if isinstance(status, dict) and status.get("busy") is False:
                return
            await asyncio.sleep(_POLL_SECONDS)

    def _finish(self, result: str) -> None:
        self._last_result = result
        self._attr_state = MediaPlayerState.IDLE
        if not self._removed:
            self.async_write_ha_state()

    async def _async_upload(self, sound: bytes) -> None:
        """Hand the sound to the agent; one it still holds is waited for once."""

        api = self._entry.runtime_data.api
        volume = announcement_volume(self._attr_volume_level or ANNOUNCEMENT_DEFAULT_VOLUME)
        try:
            await api.async_play_announcement(sound, volume)
            return
        except C300XAgentApiError as err:
            if "announcement_busy" not in str(err):
                raise
        await self._async_until_free()
        await api.async_play_announcement(sound, volume)

    async def _async_until_over(self, sound: bytes, started: asyncio.Future[str | None]) -> str | None:
        """Follow a sound the agent took until it is over, or until its deadline."""

        deadline = time.monotonic() + announcement_seconds(sound) + _END_MARGIN_SECONDS
        start_deadline = time.monotonic() + _START_SECONDS
        result: str | None = _STARTING
        # The device lets the agent have its speaker, or the sound ends at once.
        while result in (_STARTING, None) and time.monotonic() < start_deadline:
            await asyncio.sleep(_START_POLL_SECONDS)
            result = await self._async_check()
        if result in _NOT_OVER:
            # Started, or the agent did not answer for long: it plays as far as is known.
            self._attr_state = MediaPlayerState.PLAYING
            self.async_write_ha_state()
            started.set_result(None)
        while result in _NOT_OVER and time.monotonic() < deadline:
            await asyncio.sleep(_POLL_SECONDS)
            result = await self._async_check()
        return result

    async def _async_sound(self, sound: bytes, started: asyncio.Future[str | None]) -> None:
        """Play one sound and follow it until the device says it is over.

        `started` gets None once the sound plays, or why it was not played. A
        status read that fails is tried again; the agent ends every sound by
        the deadline, so after it the sound is over whatever the answer.
        """

        result: str | None = None
        try:
            try:
                await self._async_upload(sound)
            except C300XAgentApiError as err:
                # During a door call the agent starts no sound at all.
                if "announcement_device_busy" not in str(err):
                    self._finish("not_played")
                    started.set_result(f"C300X announcement was not played: {err}")
                    return
                result = "device_busy"
            else:
                result = await self._async_until_over(sound, started)
        except asyncio.CancelledError:
            if not started.done():
                started.set_result("The C300X speaker was removed while the sound started")
            self._finish("unknown")
            raise
        except Exception:
            _LOGGER.exception("Playing the C300X announcement failed")
            result = "failed"
        if result is None or result in _NOT_OVER:
            result = "unknown"
        self._finish(result)
        error = _RESULT_ERRORS.get(result)
        if not started.done():
            started.set_result(error)
        elif error is not None:
            _LOGGER.warning("%s", error)
