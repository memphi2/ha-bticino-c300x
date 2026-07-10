"""Answering-machine messages and memos."""

from __future__ import annotations

from base64 import b64encode
from typing import Any
from urllib.parse import quote

from ._api_core import _C300XApiCore
from ._api_normalize import (
    _ok_response,
    normalize_answering_machine,
    normalize_answering_machine_messages,
    normalize_memos,
)
from .api_errors import (
    C300XAgentApiError,
    C300XAgentApiResponseError,
)
from .api_validation import (
    normalize_memo_id,
    normalize_text_memo_text,
    normalize_video_message_id,
)


class _ApiContentMixin(_C300XApiCore):
    """Answering-machine messages and memos."""

    async def async_answering_machine_status(self) -> dict[str, Any]:
        """Return answering-machine status."""

        try:
            data = await self._request_json("GET", "/api/v1/answering-machine")
        except C300XAgentApiError:
            data = await self._request_json("GET", "/api/v1/state")
        return normalize_answering_machine(data)

    async def async_answering_machine_messages(self) -> dict[str, Any]:
        """Return answering-machine video message metadata."""

        data = await self._request_json("GET", "/api/v1/answering-machine/messages")
        return normalize_answering_machine_messages(data)

    async def async_answering_machine_message_video(
        self,
        message_id: str,
    ) -> tuple[bytes, str]:
        """Return a stored answering-machine video message."""

        normalized_message_id = normalize_video_message_id(message_id)
        return await self._request_bytes(
            "GET",
            (
                "/api/v1/answering-machine/messages/"
                f"{quote(normalized_message_id, safe='')}/video"
            ),
        )

    async def async_delete_answering_machine_message(
        self,
        message_id: str,
    ) -> dict[str, Any]:
        """Delete a stored answering-machine video message."""

        normalized_message_id = normalize_video_message_id(message_id)
        data = await self._request_json(
            "POST",
            "/api/v1/answering-machine/messages/actions/delete",
            json_data={"id": normalized_message_id},
        )
        return _ok_response(data)

    async def async_memos(self) -> dict[str, Any]:
        """Return local manual text and voice memo metadata."""

        data = await self._request_json("GET", "/api/v1/memos")
        return normalize_memos(data)

    async def async_create_text_memo(self, text: str, *, read: bool = False) -> dict[str, Any]:
        """Create a local manual text memo on the C300X."""

        normalized_text = normalize_text_memo_text(text)
        data = await self._request_json(
            "POST",
            "/api/v1/memos/text/actions/create",
            json_data={
                "text_b64": b64encode(normalized_text.encode()).decode("ascii"),
                "read": bool(read),
            },
        )
        return _ok_response(data)

    async def async_memo_audio(self, memo_id: str) -> tuple[bytes, str]:
        """Return a stored manual voice memo audio file."""

        normalized_memo_id = normalize_memo_id(memo_id)
        kind, entry_name = normalized_memo_id.split("/", 1)
        if kind != "voice":
            raise C300XAgentApiResponseError("memo id does not reference a voice memo")
        return await self._request_bytes(
            "GET",
            f"/api/v1/memos/voice/{quote(entry_name, safe='')}/audio",
        )

    async def async_delete_memo(self, memo_id: str) -> dict[str, Any]:
        """Delete a local manual memo by normalized agent memo id."""

        normalized_memo_id = normalize_memo_id(memo_id)
        data = await self._request_json(
            "POST",
            "/api/v1/memos/actions/delete",
            json_data={"id": normalized_memo_id},
        )
        return _ok_response(data)

    async def async_set_answering_machine_enabled(self, enabled: bool) -> dict[str, Any]:
        """Enable or disable the device answering machine."""

        data = await self._request_json(
            "POST",
            "/api/v1/answering-machine",
            json_data={"enabled": enabled},
        )
        return normalize_answering_machine(data)
