"""Bounded, device-isolated JPEG storage under Home Assistant's media root.

All filesystem and image work in this module is synchronous and must run in an
executor. Only our generated filenames are considered for retention cleanup.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .ring_capture import _capture_media_dirs

MAX_SNAPSHOT_BYTES = 512 * 1024
MAX_SNAPSHOT_PIXELS = 1920 * 1080
MAX_DEVICE_BYTES = 128 * 1024 * 1024
MAX_DEVICE_IMAGES = 1000
MAX_TEMP_CLEANUP = 1000
_FILE_NAME = re.compile(r"c300x-([0-9]{13})-([0-9a-f]{32})\.jpg\Z", re.ASCII)
_TEMP_FILE_NAME = re.compile(r"\.c300x-[0-9]{13}-[0-9a-f]{32}\.jpg\.tmp\Z", re.ASCII)


@dataclass(frozen=True)
class StoredSnapshot:
    """Server-generated media identity, never a client-supplied path."""

    name: str
    captured_at: float
    size: int


class SnapshotStore:
    """Operate on one entry's owned images, without querying the device."""

    def __init__(self, hass: Any, entry_id: str) -> None:
        # An opaque directory remains stable even if the user renames the device.
        device = hashlib.sha256(entry_id.encode()).hexdigest()[:32]
        self.root = _capture_media_dirs(hass)[0] / "snapshots" / device
        self.public_root = Path(hass.config.path("www")) if hasattr(hass.config, "path") else None

    def _check_root(self, *, create: bool = False) -> bool:
        if self.public_root and self.root.resolve().is_relative_to(self.public_root.resolve()):
            raise ValueError("Snapshots must not be stored under www")
        # Reject symlinked feature directories, including c300x itself. The HA
        # administrator's configured media root may intentionally be a symlink.
        for path in (self.root.parent.parent, self.root.parent, self.root):
            if path.is_symlink():
                raise ValueError("Snapshot directory must not be a symlink")
        if create:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self.root.is_dir()

    def items(self, retention_days: int, *, now: float | None = None) -> list[StoredSnapshot]:
        """Remove expired owned images and return newest first."""

        if not self._check_root():
            return []
        cutoff = (time.time() if now is None else now) - retention_days * 86400
        items: list[StoredSnapshot] = []
        removed_temps = 0
        for path in self.root.iterdir():
            # Store operations are serialized by the manager. No live write
            # exists while items() runs; these are interrupted-write remnants.
            if (_TEMP_FILE_NAME.fullmatch(path.name) and removed_temps < MAX_TEMP_CLEANUP
                    and not path.is_symlink() and path.is_file()):
                path.unlink(missing_ok=True)
                removed_temps += 1
                continue
            match = _FILE_NAME.fullmatch(path.name)
            if match is None or path.is_symlink() or not path.is_file():
                continue
            captured_at = int(match[1]) / 1000
            if captured_at <= cutoff:
                path.unlink(missing_ok=True)
                continue
            size = path.stat().st_size
            if 0 < size <= MAX_SNAPSHOT_BYTES:
                items.append(StoredSnapshot(path.name, captured_at, size))
            else:
                path.unlink(missing_ok=True)
        items.sort(key=lambda item: item.name, reverse=True)
        total = 0
        kept: list[StoredSnapshot] = []
        for item in items:
            if len(kept) >= MAX_DEVICE_IMAGES or total + item.size > MAX_DEVICE_BYTES:
                (self.root / item.name).unlink(missing_ok=True)
            else:
                kept.append(item)
                total += item.size
        return kept

    def read(self, name: str, retention_days: int) -> bytes | None:
        """Return only a non-expired owned file, including the latest alias."""

        items = self.items(retention_days)
        item = next((item for item in items if name in ("latest", item.name)), None)
        if item is None:
            return None
        # O_NOFOLLOW closes the final-component symlink race during reads.
        fd = os.open(self.root / item.name, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as source:
            content = source.read(MAX_SNAPSHOT_BYTES + 1)
        return content if len(content) <= MAX_SNAPSHOT_BYTES else None

    def save(self, content: bytes, session: str, retention_days: int) -> StoredSnapshot:
        """Store at most one normalized image per session under resource limits."""

        digest = hashlib.sha256(session.encode()).hexdigest()[:32]
        items = self.items(retention_days)
        existing = next((item for item in items if item.name.endswith(f"-{digest}.jpg")), None)
        if existing is not None:
            return existing
        normalized = normalize_snapshot(content)
        self._check_root(create=True)
        captured_at = int(time.time() * 1000) / 1000
        name = f"c300x-{int(captured_at * 1000):013d}-{digest}.jpg"
        temporary = self.root / f".{name}.tmp"
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as target:
                target.write(normalized)
            temporary.replace(self.root / name)
        finally:
            temporary.unlink(missing_ok=True)
        self.items(retention_days)
        return StoredSnapshot(name, captured_at, len(normalized))


def normalize_snapshot(content: bytes) -> bytes:
    """Decode bounded JPEG input and discard EXIF and other client metadata."""

    if not content or len(content) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Invalid snapshot size")
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format != "JPEG" or image.width * image.height > MAX_SNAPSHOT_PIXELS:
                raise ValueError("Expected a bounded JPEG image")
            image.load()
            rgb = image.convert("RGB")
            rgb.info.clear()
            rgb.thumbnail((1280, 720))
            output = BytesIO()
            rgb.save(output, format="JPEG", quality=85)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as err:
        raise ValueError("Invalid JPEG image") from err
    result = output.getvalue()
    if len(result) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Snapshot exceeds the storage limit")
    return result
