"""Answering-machine message service use cases."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from ..const import SIGNAL_VIDEO_MESSAGES_CHANGED
from ..message_refresh import async_answering_machine_messages
from ..video_messages import latest_video_message_id, video_message_media_source_id
from .common import (
    async_ensure_gui_function_patch,
    async_play_media,
    async_refresh_after_message_mutation,
    latest_item_id_for_entry,
    raise_agent_command_failed,
)

MEDIA_TYPE_VIDEO = "video"


class MessagesUseCase:
    """Play or delete C300X answering-machine video messages."""

    def __init__(self, hass: HomeAssistant, entry: Any) -> None:
        self._hass = hass
        self._entry = entry

    async def play_latest_video_message(self, media_player_entity_id: str) -> None:
        """Play the latest video message on a media player."""

        message_id = await self._latest_video_message_id()
        await async_play_media(
            self._hass,
            media_player_entity_id,
            media_content_id=video_message_media_source_id(
                self._entry.entry_id,
                message_id,
            ),
            media_content_type=MEDIA_TYPE_VIDEO,
        )

    async def delete_latest_video_message(self) -> None:
        """Delete the newest stored video message."""

        await async_ensure_gui_function_patch(self._entry)
        message_id = await self._latest_video_message_id()
        await raise_agent_command_failed(
            self._entry.runtime_data.api.async_delete_answering_machine_message(
                message_id
            )
        )
        await async_refresh_after_message_mutation(
            self._hass,
            self._entry,
            refresh=lambda: async_answering_machine_messages(
                self._entry,
                force_refresh=True,
            ),
            signal=SIGNAL_VIDEO_MESSAGES_CHANGED,
        )

    async def _latest_video_message_id(self) -> str:
        return await latest_item_id_for_entry(
            self._entry,
            cache_attr="answering_machine_messages",
            refresh=lambda: async_answering_machine_messages(
                self._entry,
                force_refresh=True,
            ),
            latest=latest_video_message_id,
            unavailable_error="video_message_not_available",
        )
