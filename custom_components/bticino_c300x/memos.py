"""Helpers for C300X manual memo metadata."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .const import DOMAIN
from .message_metadata import latest_metadata_item, localized_choice

MAX_MEMO_STATE_LENGTH = 255
DEFAULT_VOICE_MEMO_MIME_TYPE = "audio/wav"


def memo_kind_items(memos: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Return memo items of one normalized kind."""

    return [
        memo
        for memo in memos.get("memos", [])
        if isinstance(memo, dict) and memo.get("kind") == kind
    ]


def memo_kind_counts(memos: dict[str, Any], kind: str) -> tuple[int, int]:
    """Return unread/read counters for one memo kind."""

    items = memo_kind_items(memos, kind)
    return (
        sum(1 for memo in items if memo.get("read") is False),
        sum(1 for memo in items if memo.get("read") is True),
    )


def latest_memo(memos: dict[str, Any], kind: str) -> dict[str, Any] | None:
    """Return newest memo item of one kind."""

    return latest_metadata_item(memo_kind_items(memos, kind))


def latest_memo_id(memos: dict[str, Any], kind: str) -> str | None:
    """Return the newest memo id of one kind."""

    latest = latest_memo(memos, kind)
    if latest is None:
        return None
    memo_id = latest.get("id")
    return memo_id if isinstance(memo_id, str) and memo_id else None


def voice_memo_items(memos: dict[str, Any]) -> list[dict[str, Any]]:
    """Return playable manual voice memo items."""

    return [
        memo
        for memo in memo_kind_items(memos, "voice")
        if memo.get("has_audio") and memo.get("id")
    ]


def latest_voice_memo(memos: dict[str, Any]) -> dict[str, Any] | None:
    """Return the newest playable manual voice memo."""

    return latest_metadata_item(voice_memo_items(memos))


def latest_voice_memo_audio_id(memos: dict[str, Any]) -> str | None:
    """Return the newest playable voice memo id."""

    latest = latest_voice_memo(memos)
    memo_id = latest.get("id") if latest else None
    return memo_id if isinstance(memo_id, str) and memo_id else None


def memo_kind_label(kind: str, language: str | None = None) -> str:
    """Return a translated memo kind label."""

    if kind == "voice":
        return localized_choice(
            language,
            de="Sprach-Memo",
            it="Memo vocale",
            fr="Memo vocal",
            en="Voice memo",
        )
    return localized_choice(
        language,
        de="Text-Memo",
        it="Memo testuale",
        fr="Memo texte",
        en="Text memo",
    )




def latest_memo_attributes(
    memos: dict[str, Any],
    kind: str,
    *,
    include_text: bool = False,
    entry_id: str | None = None,
) -> dict[str, Any]:
    """Return consistent latest-memo attributes for sensors/buttons."""

    latest = latest_memo(memos, kind)
    unread, read = memo_kind_counts(memos, kind)
    attributes: dict[str, Any] = {
        "kind": kind,
        "has_memo": latest is not None,
        "total": memos.get(f"{kind}_total"),
        "unread": unread,
        "read": read,
        "latest_memo_id": latest.get("id") if latest else None,
        "latest_memo_at": latest.get("iso_time") or latest.get("date") if latest else None,
        "latest_memo_read": latest.get("read") if latest else None,
        "has_audio": bool(latest.get("has_audio")) if latest else False,
    }
    if kind == "voice":
        memo_id = (
            str(latest.get("id"))
            if latest and latest.get("has_audio") and latest.get("id")
            else None
        )
        attributes.update(
            {
                "audio_mime_type": latest.get("audio_mime_type")
                if latest
                else None,
                "audio_size": latest.get("audio_size") if latest else None,
                "media_content_id": voice_memo_media_source_id(entry_id, memo_id)
                if entry_id and memo_id
                else None,
                "media_url": voice_memo_media_url(entry_id, memo_id)
                if entry_id and memo_id
                else None,
            }
        )
    if include_text:
        text = latest.get("text") if latest else None
        attributes["latest_text"] = text if isinstance(text, str) else None
        attributes["text_truncated"] = bool(
            latest.get("text_truncated") if latest else False
        ) or memo_text_was_state_truncated(text)
    return attributes


def voice_memo_media_source_id(entry_id: str, memo_id: str) -> str:
    """Return the Home Assistant media-source id for a voice memo."""

    entry_name = _voice_memo_entry_name(memo_id)
    return (
        f"media-source://{DOMAIN}/voice/"
        f"{quote(entry_id, safe='')}/{quote(entry_name, safe='')}"
    )


def voice_memo_media_url(entry_id: str, memo_id: str) -> str:
    """Return the authenticated Home Assistant media proxy URL for a voice memo."""

    entry_name = _voice_memo_entry_name(memo_id)
    return (
        f"/api/{DOMAIN}/voice-memos/"
        f"{quote(entry_id, safe='')}/{quote(entry_name, safe='')}/audio"
    )


def voice_memo_title(
    memo: dict[str, Any],
    *,
    language: str | None = None,
) -> str:
    """Return a stable display title for a voice memo."""

    label = memo_kind_label("voice", language)
    timestamp = memo.get("iso_time") or memo.get("date")
    if timestamp:
        return f"{label} {timestamp}"
    return f"{label} {memo.get('id', '')}".strip()


def _voice_memo_entry_name(memo_id: str) -> str:
    if not isinstance(memo_id, str) or not memo_id.startswith("voice/"):
        raise ValueError("voice memo id must start with voice/")
    return memo_id.split("/", 1)[1]


def memo_state_text(value: Any) -> str | None:
    """Return memo text constrained to Home Assistant's state limit."""

    if not isinstance(value, str) or value == "":
        return None
    if len(value) <= MAX_MEMO_STATE_LENGTH:
        return value
    return f"{value[: MAX_MEMO_STATE_LENGTH - 3]}..."


def memo_text_was_state_truncated(value: Any) -> bool:
    """Return true when the memo text had to be shortened for entity state."""

    return isinstance(value, str) and len(value) > MAX_MEMO_STATE_LENGTH
