"""Shared spec for the two device-stored item families (video messages, memos).

The voicemail/answering-machine and manual-memo features expose the same
entity shapes (a metadata sensor plus a delete-latest button) over different
agent endpoints, dispatcher signals, and payload keys. This spec captures
everything family-specific so sensor.py and button.py can share one
implementation per entity shape instead of maintaining line-for-line twins.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .api import (
    normalize_answering_machine_messages,
    normalize_memos,
)
from .const import SIGNAL_MEMOS_CHANGED, SIGNAL_VIDEO_MESSAGES_CHANGED
from .message_refresh import (
    async_answering_machine_messages,
    async_memos,
    schedule_answering_machine_messages_refresh,
    schedule_memos_refresh,
)


@dataclass(frozen=True)
class StoredItemsSpec:
    """Everything family-specific about one stored-item collection."""

    payload_attr: str
    updated_at_attr: str
    signal: str
    agent_event_key: str
    event_payload_key: str
    items_key: str
    normalize: Callable[[dict[str, Any]], dict[str, Any]]
    fetch: Callable[..., Awaitable[dict[str, Any]]]
    schedule_refresh: Callable[[Any, Any], None]
    # The voicemail sensor historically ignores a malformed event payload
    # entirely, while the memo sensor still schedules a refresh for it.
    schedule_refresh_on_invalid_event_payload: bool
    delete_item: Callable[[Any, str], Awaitable[Any]]
    refresh_error: str
    unsupported_error: str
    delete_error: str


VIDEO_MESSAGE_ITEMS = StoredItemsSpec(
    payload_attr="answering_machine_messages",
    updated_at_attr="answering_machine_messages_updated_at",
    signal=SIGNAL_VIDEO_MESSAGES_CHANGED,
    agent_event_key="answering_machine_messages_changed",
    event_payload_key="voicemail",
    items_key="messages",
    normalize=normalize_answering_machine_messages,
    fetch=async_answering_machine_messages,
    schedule_refresh=schedule_answering_machine_messages_refresh,
    schedule_refresh_on_invalid_event_payload=False,
    delete_item=lambda api, item_id: api.async_delete_answering_machine_message(
        item_id
    ),
    refresh_error="C300X video-message refresh failed",
    unsupported_error=(
        "The installed C300X device agent does not support deleting video messages"
    ),
    delete_error="C300X video-message delete failed",
)

MEMO_ITEMS = StoredItemsSpec(
    payload_attr="memos",
    updated_at_attr="memos_updated_at",
    signal=SIGNAL_MEMOS_CHANGED,
    agent_event_key="memos_changed",
    event_payload_key="memos",
    items_key="memos",
    normalize=normalize_memos,
    fetch=async_memos,
    schedule_refresh=schedule_memos_refresh,
    schedule_refresh_on_invalid_event_payload=True,
    delete_item=lambda api, item_id: api.async_delete_memo(item_id),
    refresh_error="C300X memo refresh failed",
    unsupported_error=(
        "The installed C300X device agent does not support deleting memos"
    ),
    delete_error="C300X memo delete failed",
)
