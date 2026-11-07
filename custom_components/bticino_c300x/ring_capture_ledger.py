"""Bounded, durable one-use reservations for physical ring actions."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.file import write_utf8_file_atomic

MAX_RING_ANALYSIS_AGE_SECONDS = 60
MAX_USED_CAPTURES = 256
_MAX_LEDGER_BYTES = 131072
_RESERVATION_LOCK = Lock()


def read_used_captures(path: Path, now: datetime) -> dict[str, str]:
    """Load live reservations, including the previous single-capture format."""
    try:
        with path.open(encoding="utf-8") as source:
            text = source.read(_MAX_LEDGER_BYTES + 1)
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError) as err:
        raise HomeAssistantError("C300X ring capture ledger is unavailable") from err
    try:
        if len(text) > _MAX_LEDGER_BYTES:
            raise ValueError("ledger too large")
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("invalid ledger")
        if payload.get("version") == 1:
            captures = payload["captures"]
        elif "version" not in payload:
            captures = {payload["capture_id"]: payload["used_at"]}
        else:
            raise ValueError("unknown ledger version")
        if not isinstance(captures, dict) or len(captures) > MAX_USED_CAPTURES:
            raise ValueError("invalid reservations")
        live = {}
        for capture_id, used_at in captures.items():
            if not isinstance(capture_id, str) or not 1 <= len(capture_id) <= 128:
                raise ValueError("invalid capture id")
            used = datetime.fromisoformat(used_at)
            if used.tzinfo is None or used > now:
                raise ValueError("invalid reservation time")
            if now - used <= timedelta(seconds=MAX_RING_ANALYSIS_AGE_SECONDS):
                live[capture_id] = used_at
        return live
    except (KeyError, TypeError, ValueError) as err:
        raise HomeAssistantError("C300X ring capture ledger is invalid") from err


def reserve_capture(path: Path, capture_id: str) -> bool:
    """Persist at most one reservation even if an executor caller is cancelled."""
    if not 1 <= len(capture_id) <= 128:
        raise HomeAssistantError("C300X ring capture id is invalid")
    # The read/check/atomic replacement runs in the executor as one operation.
    # An asyncio cancellation cannot release this lock before its write finishes.
    with _RESERVATION_LOCK:
        now = datetime.now(UTC)
        captures = read_used_captures(path, now)
        if capture_id in captures:
            return False
        if len(captures) >= MAX_USED_CAPTURES:
            raise HomeAssistantError("C300X ring capture ledger is full")
        captures[capture_id] = now.isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        write_utf8_file_atomic(
            str(path), json.dumps({"version": 1, "captures": captures}), private=True
        )
        return True
