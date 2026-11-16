"""Bounded entry-owned completion metadata, persisted with the visitor journal."""

from __future__ import annotations

import time
from typing import Any

from .visitor_journal_media import valid_clip

MAX_CAPTURES = 1000


class CaptureHistory:
    """Never discover ownership from the shared capture directory."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def add(self, clip: Any, at: Any) -> None:
        clip = valid_clip(clip)
        if (clip is None or type(at) not in (int, float)
                or not 0 < at <= time.time()):
            return
        # A completed generated filename is single-use: never rebind its identity.
        self.records.setdefault(clip["name"], {"at": at, "clip": clip})

    def load(self, raw: Any) -> None:
        if isinstance(raw, list):
            for item in raw[-MAX_CAPTURES:]:
                if isinstance(item, dict):
                    self.add(item.get("clip"), item.get("at"))

    def prune(self, retention_days: int) -> bool:
        now = time.time()
        kept = sorted(
            (item for item in self.records.values()
             if now - retention_days * 86400 < item["at"] <= now),
            key=lambda item: (item["at"], item["clip"]["name"]),
        )[-MAX_CAPTURES:]
        records = {item["clip"]["name"]: item for item in kept}
        changed = records != self.records
        self.records = records
        return changed
