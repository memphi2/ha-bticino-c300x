"""Bind journal images to checked local bytes; all file work runs off-loop."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import time
from typing import Any

from .snapshot_store import _FILE_NAME, MAX_SNAPSHOT_BYTES, SnapshotStore

_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


def valid_snapshot(raw: Any) -> dict[str, Any] | None:
    """Reject legacy filename-only links, never rebind them to today's file."""
    if not isinstance(raw, dict):
        return None
    name, signature, digest = raw.get("name"), raw.get("signature"), raw.get("sha256")
    if not isinstance(name, str) or not _FILE_NAME.fullmatch(name):
        return None
    if (not isinstance(signature, list) or len(signature) != 4
            or any(type(part) is not int or not 0 <= part < 2**64 for part in signature)
            or not 0 < signature[2] <= MAX_SNAPSHOT_BYTES):
        return None
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        return None
    return {"name": name, "signature": list(signature), "sha256": digest}


def _signature(info: os.stat_result) -> list[int]:
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def _read(
    store: SnapshotStore, name: str, retention_days: int,
    expected: list[int] | None = None,
    changed_ns: int | None = None,
) -> tuple[bytes, list[int]] | None:
    match = _FILE_NAME.fullmatch(name)
    if (match is None or int(match[1]) / 1000 <= time.time() - retention_days * 86400
            or not store._check_root()):
        return None
    path = store.root / name
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        signature = _signature(info)
        if (not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_SNAPSHOT_BYTES
                or (expected is not None and signature != expected)):
            return None
        if changed_ns is not None and info.st_ctime_ns != changed_ns:
            return None
        content = source.read(MAX_SNAPSHOT_BYTES + 1)
        after = os.fstat(source.fileno())
        if (len(content) != info.st_size or _signature(after) != signature
                or after.st_ctime_ns != info.st_ctime_ns):
            return None
        # Also reject rename/unlink races while the original descriptor is open.
        current = path.stat(follow_symlinks=False)
        if (not stat.S_ISREG(current.st_mode) or _signature(current) != signature
                or current.st_ctime_ns != info.st_ctime_ns
                or not store._check_root()):
            return None
    return content, signature


def describe_snapshot(
    hass: Any, entry_id: str, name: str, acquired: bytes, retention_days: int,
) -> dict[str, Any] | None:
    """Associate only a file still containing the frame this capture acquired."""
    if not isinstance(acquired, bytes) or not 0 < len(acquired) <= MAX_SNAPSHOT_BYTES:
        return None
    result = _read(SnapshotStore(hass, entry_id), name, retention_days)
    if result is None or result[0] != acquired:
        return None
    content, signature = result
    return valid_snapshot({
        "name": name, "signature": signature, "sha256": hashlib.sha256(content).hexdigest(),
    })


def read_snapshot(hass: Any, entry_id: str, raw: Any, retention_days: int) -> bytes | None:
    """Read and verify the same bounded bytes that will be sent to the client."""
    identity = valid_snapshot(raw)
    if identity is None:
        return None
    result = _read(SnapshotStore(hass, entry_id), identity["name"], retention_days, identity["signature"])
    if result is None or hashlib.sha256(result[0]).hexdigest() != identity["sha256"]:
        return None
    return result[0]
