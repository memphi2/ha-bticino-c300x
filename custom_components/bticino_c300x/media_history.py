"""Local metadata inventory and immutable reads; call disk functions in an executor."""

from __future__ import annotations

import hashlib
import json
import stat
import time
from typing import Any

from .capture_history import CLOCK_TOLERANCE
from .snapshot_identity import _read, _signature
from .snapshot_store import MAX_SNAPSHOT_BYTES, SnapshotStore
from .visitor_journal_media import _path, describe_clip, read_clip

MAX_HISTORY_ITEMS = 1000
PUBLIC_FIELDS = ("id", "kind", "at", "expires_at", "revision")


def video_records(journal: Any) -> list[dict[str, Any]]:
    """Use only entry-owned completions or already owned legacy journal links."""
    if journal is None or journal.closed:
        return []
    visits = journal.items()
    records = dict(journal.captures.records)
    for visit in visits:
        clip = visit["clip"]
        if clip is not None:
            # Old journals have no capture-start timestamp. Their original file
            # completion mtime is the only retained media timestamp, not playback time.
            records.setdefault(clip["name"], {
                "at": clip["signature"][3] / 1_000_000_000, "clip": clip,
            })
    return sorted(records.values(), key=lambda item: item["at"], reverse=True)[:MAX_HISTORY_ITEMS]


def _item(entry_id: str, kind: str, at: float, identity: dict[str, Any], days: int) -> dict[str, Any]:
    revision = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    key = hashlib.sha256(f"{entry_id}:{kind}:{revision}".encode()).hexdigest()
    return {"id": key, "kind": kind, "at": at, "expires_at": at + days * 86400,
            "revision": revision, "identity": identity}


def inventory(hass: Any, entry_id: str, enabled: bool, days: int,
              videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stat bounded owned candidates; never hash or open all media content."""
    result = []
    now = time.time()
    if enabled:
        store = SnapshotStore(hass, entry_id)
        for image in store.items(days):
            try:
                info = (store.root / image.name).stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_SNAPSHOT_BYTES:
                    continue
                identity = {"name": image.name, "signature": _signature(info), "changed_ns": info.st_ctime_ns}
                result.append(_item(entry_id, "image", image.captured_at, identity, days))
            except OSError:
                continue
    for record in videos[:MAX_HISTORY_ITEMS]:
        if not now - days * 86400 < record["at"] <= now + CLOCK_TOLERANCE:
            continue
        try:
            # _path applies the existing private capture-root policy. No scan.
            clip = record["clip"]
            current = describe_clip(hass, {"output_path": _path(hass, clip["name"])})
            if (current is None or current["signature"] != clip["signature"]
                    or ("changed_ns" in clip and current["changed_ns"] != clip["changed_ns"])):
                continue
            item = _item(entry_id, "video", record["at"], current, days)
            item["record"] = record
            result.append(item)
        except (OSError, ValueError):
            continue
    return sorted(
        (item for item in result if now - days * 86400 < item["at"] <= now + CLOCK_TOLERANCE),
        key=lambda item: (item["at"], item["id"]), reverse=True,
    )[:MAX_HISTORY_ITEMS]


def read_item(
    hass: Any, entry_id: str, item: dict[str, Any], days: int,
    window: tuple[int, int] | None = None,
) -> bytes | None:
    """Reject replacement, rewrite (even restored mtime), unlink and symlink races."""
    identity = item["identity"]
    if item["kind"] == "video":
        return read_clip(hass, identity, window)
    result = _read(SnapshotStore(hass, entry_id), identity["name"], days,
                   identity["signature"], identity["changed_ns"])
    return result[0] if result is not None else None
