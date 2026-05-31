"""Expose stored C300X media through Home Assistant media source."""

from __future__ import annotations

from contextlib import suppress
from typing import Any
from urllib.parse import unquote

from homeassistant.components.media_player import BrowseError, MediaClass
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant

from .api import (
    C300XAgentApiError,
    C300XAgentApiResponseError,
    normalize_memo_id,
    normalize_video_message_id,
)
from .const import DOMAIN
from .media import runtime_entry
from .memos import (
    DEFAULT_VOICE_MEMO_MIME_TYPE,
    voice_memo_items,
    voice_memo_media_url,
    voice_memo_title,
)
from .video_messages import (
    VIDEO_MESSAGE_PLAYBACK_MIME_TYPE,
    video_message_items,
    video_message_media_url,
    video_message_title,
)


async def async_get_media_source(hass: HomeAssistant) -> C300XStoredMediaSource:
    """Set up the C300X stored media source."""

    return C300XStoredMediaSource(hass)


class C300XStoredMediaSource(MediaSource):
    """Provide stored answering-machine videos and voice memos as playable HA media."""

    name: str = "BTicino C300X Media"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve a stored C300X media-source id to the HA proxy URL."""

        media_kind, entry_id, media_id = _parse_identifier(item.identifier)
        entry = runtime_entry(self.hass, entry_id)
        if entry is None:
            raise Unresolvable(f"Could not resolve C300X entry: {entry_id}")

        if media_kind == "voice":
            memos = await _async_memos_for_entry(entry)
            memo = next(
                (
                    candidate
                    for candidate in voice_memo_items(memos)
                    if candidate.get("id") == media_id
                ),
                None,
            )
            if memo is None:
                raise Unresolvable(f"Could not resolve C300X voice memo: {media_id}")
            return PlayMedia(
                voice_memo_media_url(entry_id, media_id),
                str(memo.get("audio_mime_type") or DEFAULT_VOICE_MEMO_MIME_TYPE),
            )

        messages = await _async_messages_for_entry(entry)
        message = next(
            (
                candidate
                for candidate in video_message_items(messages)
                if candidate.get("id") == media_id
            ),
            None,
        )
        if message is None:
            raise Unresolvable(f"Could not resolve C300X video message: {media_id}")

        return PlayMedia(
            video_message_media_url(entry_id, media_id),
            VIDEO_MESSAGE_PLAYBACK_MIME_TYPE,
        )

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Return browsable stored video messages."""

        if item.identifier:
            raise BrowseError("Unknown C300X media-source item")

        children: list[BrowseMediaSource] = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if not hasattr(entry, "runtime_data"):
                continue
            messages: dict[str, Any] = {}
            memos: dict[str, Any] = {}
            with suppress(C300XAgentApiError):
                messages = await _async_messages_for_entry(entry)
            with suppress(C300XAgentApiError):
                memos = await _async_memos_for_entry(entry)
            children.extend(_message_children(entry.entry_id, messages))
            children.extend(_voice_memo_children(entry.entry_id, memos))

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=None,
            media_class=MediaClass.APP,
            media_content_type="",
            title=self.name,
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.APP,
            children=children,
        )


async def _async_messages_for_entry(entry: Any) -> dict[str, Any]:
    messages = await entry.runtime_data.api.async_answering_machine_messages()
    entry.runtime_data.answering_machine_messages = messages
    return messages


async def _async_memos_for_entry(entry: Any) -> dict[str, Any]:
    memos = await entry.runtime_data.api.async_memos()
    entry.runtime_data.memos = memos
    return memos


def _message_children(entry_id: str, messages: dict[str, Any]) -> list[BrowseMediaSource]:
    return [
        BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{entry_id}/{message['id']}",
            media_class=MediaClass.VIDEO,
            media_content_type=VIDEO_MESSAGE_PLAYBACK_MIME_TYPE,
            title=video_message_title(message),
            can_play=True,
            can_expand=False,
        )
        for message in video_message_items(messages)
        if message.get("id")
    ]


def _voice_memo_children(entry_id: str, memos: dict[str, Any]) -> list[BrowseMediaSource]:
    return [
        BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"voice/{entry_id}/{str(memo['id']).split('/', 1)[1]}",
            media_class=_voice_media_class(),
            media_content_type=str(
                memo.get("audio_mime_type") or DEFAULT_VOICE_MEMO_MIME_TYPE
            ),
            title=voice_memo_title(memo),
            can_play=True,
            can_expand=False,
        )
        for memo in voice_memo_items(memos)
        if memo.get("id") and "/" in str(memo.get("id"))
    ]


def _parse_identifier(identifier: str | None) -> tuple[str, str, str]:
    value = str(identifier or "").strip()
    if "/" not in value:
        raise Unresolvable("C300X media identifier is incomplete")
    if value.startswith("voice/"):
        parts = value.split("/", 2)
        if len(parts) != 3:
            raise Unresolvable("C300X voice-memo identifier is incomplete")
        entry_id = unquote(parts[1])
        memo_name = unquote(parts[2])
        try:
            return "voice", entry_id, normalize_memo_id(f"voice/{memo_name}")
        except C300XAgentApiResponseError as err:
            raise Unresolvable("C300X voice-memo identifier is invalid") from err
    if value.startswith("video/"):
        parts = value.split("/", 2)
        if len(parts) != 3:
            raise Unresolvable("C300X video-message identifier is incomplete")
        entry_id = unquote(parts[1])
        message_id = unquote(parts[2])
    else:
        entry_id, message_id = value.split("/", 1)
        entry_id = unquote(entry_id)
        message_id = unquote(message_id)
    try:
        return "video", entry_id, normalize_video_message_id(message_id)
    except C300XAgentApiResponseError as err:
        raise Unresolvable("C300X video-message identifier is invalid") from err


def _voice_media_class() -> MediaClass:
    return getattr(MediaClass, "MUSIC", MediaClass.APP)
