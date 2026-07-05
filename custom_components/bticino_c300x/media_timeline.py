"""Bounded in-memory media timeline diagnostics."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

MAX_MEDIA_TIMELINE_ENTRIES = 40
_MAX_DETAIL_TEXT_LENGTH = 120
_UNSAFE_DETAIL_KEY_PARTS = (
    "candidate",
    "host",
    "password",
    "path",
    "sdp",
    "secret",
    "session_id",
    "token",
    "url",
)


@dataclass(slots=True)
class C300XMediaTimelineEntry:
    """One safe media/call runtime transition."""

    at: datetime
    kind: str
    event: str
    media_state: str | None = None
    owner: str | None = None
    session_count: int | None = None
    ring_preview_sessions: int | None = None
    ready_sessions: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def diagnostics(self) -> dict[str, Any]:
        """Return the entry as diagnostics-safe JSON data."""

        return {
            "at": self.at.isoformat(),
            "kind": self.kind,
            "event": self.event,
            "media_state": self.media_state,
            "owner": self.owner,
            "session_count": self.session_count,
            "ring_preview_sessions": self.ring_preview_sessions,
            "ready_sessions": self.ready_sessions,
            "details": self.details,
        }


@dataclass(slots=True)
class C300XMediaTimeline:
    """Bounded media timeline backed by already-observed runtime events."""

    entries: deque[C300XMediaTimelineEntry] = field(
        default_factory=lambda: deque(maxlen=MAX_MEDIA_TIMELINE_ENTRIES)
    )

    def record(
        self,
        *,
        kind: str,
        event: str,
        media_state: str | None = None,
        owner: str | None = None,
        session_count: int | None = None,
        ring_preview_sessions: int | None = None,
        ready_sessions: int | None = None,
        details: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> None:
        """Append one sanitized runtime transition."""

        self.entries.append(
            C300XMediaTimelineEntry(
                at=now or datetime.now(UTC),
                kind=str(kind),
                event=str(event),
                media_state=_optional_text(media_state),
                owner=_optional_text(owner),
                session_count=_optional_int(session_count),
                ring_preview_sessions=_optional_int(ring_preview_sessions),
                ready_sessions=_optional_int(ready_sessions),
                details=_safe_details(details or {}),
            )
        )

    def diagnostics(self) -> list[dict[str, Any]]:
        """Return diagnostics-safe entries in chronological order."""

        return [entry.diagnostics() for entry in self.entries]


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_details(details: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for raw_key, value in details.items():
        key = str(raw_key)
        lowered = key.lower()
        if any(part in lowered for part in _UNSAFE_DETAIL_KEY_PARTS):
            continue
        if value is None or isinstance(value, bool | int | float):
            safe[key] = value
        elif isinstance(value, str):
            safe[key] = _truncate_detail_text(value)
    return safe


def _truncate_detail_text(value: str) -> str:
    if len(value) <= _MAX_DETAIL_TEXT_LENGTH:
        return value
    return f"{value[: _MAX_DETAIL_TEXT_LENGTH - 3]}..."
