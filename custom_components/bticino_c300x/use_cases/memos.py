"""Memo service use cases."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from ..const import SIGNAL_MEMOS_CHANGED
from ..memos import (
    latest_memo_id,
    latest_voice_memo_audio_id,
    voice_memo_media_source_id,
)
from ..message_refresh import async_memos
from .common import (
    async_ensure_gui_function_patch,
    async_play_media,
    async_refresh_after_message_mutation,
    ensure_text_memo_write_supported,
    latest_item_id_for_entry,
    raise_agent_command_failed,
)

MEDIA_TYPE_MUSIC = "music"


class MemosUseCase:
    """Play, write, or delete C300X local memos."""

    def __init__(self, hass: HomeAssistant, entry: Any) -> None:
        self._hass = hass
        self._entry = entry

    async def play_latest_voice_memo(self, media_player_entity_id: str) -> None:
        """Play the latest voice memo on a media player."""

        memo_id = await self._latest_voice_memo_audio_id()
        await async_play_media(
            self._hass,
            media_player_entity_id,
            media_content_id=voice_memo_media_source_id(self._entry.entry_id, memo_id),
            media_content_type=MEDIA_TYPE_MUSIC,
        )

    async def write_text_memo(self, text: str, *, read: bool = False) -> None:
        """Create a local text memo on the C300X."""

        ensure_text_memo_write_supported(self._entry)
        await raise_agent_command_failed(
            self._entry.runtime_data.api.async_create_text_memo(text, read=read)
        )
        await async_refresh_after_message_mutation(
            self._hass,
            self._entry,
            refresh=lambda: async_memos(self._entry, force_refresh=True),
            signal=SIGNAL_MEMOS_CHANGED,
        )

    async def delete_latest_text_memo(self) -> None:
        """Delete the newest text memo."""

        await self._async_delete_latest_memo("text")

    async def delete_latest_voice_memo(self) -> None:
        """Delete the newest voice memo."""

        await self._async_delete_latest_memo("voice")

    async def _async_delete_latest_memo(self, kind: str) -> None:
        await async_ensure_gui_function_patch(self._entry)
        memo_id = await self._latest_memo_id(kind)
        await raise_agent_command_failed(
            self._entry.runtime_data.api.async_delete_memo(memo_id)
        )
        await async_refresh_after_message_mutation(
            self._hass,
            self._entry,
            refresh=lambda: async_memos(self._entry, force_refresh=True),
            signal=SIGNAL_MEMOS_CHANGED,
        )

    async def _latest_memo_id(self, kind: str) -> str:
        return await latest_item_id_for_entry(
            self._entry,
            cache_attr="memos",
            refresh=lambda: async_memos(self._entry, force_refresh=True),
            latest=lambda memos: latest_memo_id(memos, kind),
            unavailable_error=f"{kind}_memo_not_available",
        )

    async def _latest_voice_memo_audio_id(self) -> str:
        return await latest_item_id_for_entry(
            self._entry,
            cache_attr="memos",
            refresh=lambda: async_memos(self._entry, force_refresh=True),
            latest=latest_voice_memo_audio_id,
            unavailable_error="voice_memo_not_available",
        )
