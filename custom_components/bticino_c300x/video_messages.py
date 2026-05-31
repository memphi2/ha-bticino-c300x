"""Helpers for C300X answering-machine video messages."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .const import DOMAIN

VIDEO_MESSAGE_PLAYBACK_MIME_TYPE = "video/mp4"


def video_message_items(messages: dict[str, Any]) -> list[dict[str, Any]]:
    """Return stored answering-machine entries that contain video media."""

    return [
        message
        for message in messages.get("messages", [])
        if isinstance(message, dict) and message.get("has_video")
    ]


def latest_video_message(messages: dict[str, Any]) -> dict[str, Any] | None:
    """Return the newest stored answering-machine video message."""

    items = video_message_items(messages)
    if not items:
        return None
    return max(
        items,
        key=lambda message: (
            int(message.get("unix_time") or 0),
            str(message.get("iso_time") or message.get("date") or ""),
            str(message.get("id") or ""),
        ),
    )


def latest_video_message_id(messages: dict[str, Any]) -> str | None:
    """Return the newest video-message id, if one is available."""

    latest = latest_video_message(messages)
    if latest is None:
        return None
    message_id = latest.get("id")
    return str(message_id) if message_id else None


def latest_video_message_attributes(
    messages: dict[str, Any],
    entry_id: str,
) -> dict[str, Any]:
    """Return consistent latest video-message attributes."""

    latest = latest_video_message(messages)
    attributes: dict[str, Any] = {
        "has_message": latest is not None,
        "total": messages.get("total"),
        "unread": messages.get("unread"),
        "read": messages.get("read"),
        "latest_message_id": None,
        "latest_message_at": None,
        "media_mime_type": None,
        "media_size": None,
        "media_content_id": None,
        "media_url": None,
        "playback_mime_type": None,
        "original_media_url": None,
    }
    if latest is None:
        return attributes

    message_id = str(latest["id"])
    attributes.update(
        {
            "latest_message_id": message_id,
            "latest_message_at": latest.get("iso_time") or latest.get("date"),
            "latest_message_read": latest.get("read"),
            "media_mime_type": latest.get("media_mime_type"),
            "media_size": latest.get("media_size"),
            "media_content_id": video_message_media_source_id(entry_id, message_id),
            "media_url": video_message_media_url(entry_id, message_id),
            "playback_mime_type": VIDEO_MESSAGE_PLAYBACK_MIME_TYPE,
            "original_media_url": video_message_original_media_url(
                entry_id,
                message_id,
            ),
        }
    )
    return attributes


def video_message_media_source_id(entry_id: str, message_id: str) -> str:
    """Return the Home Assistant media-source id for a video message."""

    return (
        f"media-source://{DOMAIN}/"
        f"{quote(entry_id, safe='')}/{quote(message_id, safe='')}"
    )


def video_message_media_url(entry_id: str, message_id: str) -> str:
    """Return the authenticated Home Assistant playable media proxy URL."""

    return (
        f"/api/{DOMAIN}/video-messages/"
        f"{quote(entry_id, safe='')}/{quote(message_id, safe='')}/video.mp4"
    )


def video_message_original_media_url(entry_id: str, message_id: str) -> str:
    """Return the authenticated Home Assistant original media proxy URL."""

    return (
        f"/api/{DOMAIN}/video-messages/"
        f"{quote(entry_id, safe='')}/{quote(message_id, safe='')}/video"
    )


def video_message_title(
    message: dict[str, Any],
    *,
    language: str | None = None,
) -> str:
    """Return a stable display title for a stored video message."""

    language_code = str(language or "").lower()
    if language_code.startswith("de"):
        label = "Video-Nachricht"
    elif language_code.startswith("it"):
        label = "Messaggio video"
    else:
        label = "Video message"
    timestamp = message.get("iso_time") or message.get("date")
    if timestamp:
        return f"{label} {timestamp}"
    return f"{label} {message.get('id', '')}".strip()
