from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

from custom_components.bticino_c300x.ring_ai import _ring_wav_path


class _FakeConfig:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, *parts: str) -> str:
        return str(self.root.joinpath(*parts))


def test_ring_ai_default_uses_latest_raw_wav_recursively(tmp_path: Path) -> None:
    older = tmp_path / "c300x" / "doorbell_older.raw.wav"
    newer = tmp_path / "c300x" / "ring" / "latest.raw.wav"
    older.parent.mkdir(parents=True)
    newer.parent.mkdir(parents=True)
    older.write_bytes(b"old")
    newer.write_bytes(b"new")
    old_time = time.time() - 60
    os.utime(older, (old_time, old_time))

    hass = SimpleNamespace(config=_FakeConfig(tmp_path))

    assert _ring_wav_path(hass, None) == newer
