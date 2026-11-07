"""Isolate capture artifacts without retaining unlimited analysis workspaces."""

from __future__ import annotations

import os
import re
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from uuid import uuid4

from homeassistant.exceptions import HomeAssistantError

MAX_CAPTURE_WORKSPACES = 64
CAPTURE_WORKSPACE_TTL = 3600
_DIRECTORY_LOCK = Lock()
_ACTIVE_OUTPUTS: set[Path] = set()
_CAPTURE_ID = re.compile(r"[0-9a-f]{32}")


@contextmanager
def reserve_capture_output(target: Path) -> Iterator[None]:
    """Reject overlapping writers to a user-specified MP4 on HA's event loop."""
    if target in _ACTIVE_OUTPUTS:
        raise HomeAssistantError("C300X capture output is already in use")
    _ACTIVE_OUTPUTS.add(target)
    try:
        yield
    finally:
        _ACTIVE_OUTPUTS.discard(target)


def prepare_capture_directory(root: Path, capture_id: str) -> Path:
    """Allocate a private run directory; expire only our old workspaces."""
    if not _CAPTURE_ID.fullmatch(capture_id):
        raise ValueError("Invalid capture id")
    parent = root / "captures"
    with _DIRECTORY_LOCK:
        if parent.is_symlink():
            raise HomeAssistantError("C300X capture workspace must not be a symlink")
        parent.mkdir(parents=True, exist_ok=True)
        count = 0
        for path in parent.iterdir():
            if not _CAPTURE_ID.fullmatch(path.name) or path.is_symlink() or not path.is_dir():
                continue
            if time.time() - path.stat().st_mtime > CAPTURE_WORKSPACE_TTL:
                shutil.rmtree(path)
            else:
                count += 1
        if count >= MAX_CAPTURE_WORKSPACES:
            raise HomeAssistantError("C300X capture workspace limit reached; retry after expiry")
        target = parent / capture_id
        target.mkdir(mode=0o700)
        return target


def publish_capture_aliases(root: Path, work_dir: Path) -> None:
    """Keep legacy latest paths as pointers; publish metadata last."""
    names = (
        "latest.raw.wav", "latest.processed.wav",
        "frame_01.jpg", "frame_02.jpg", "frame_03.jpg", "latest.capture.json",
    )
    for name in names:
        source = work_dir / name
        if not source.is_file():
            continue
        publish_alias(source, root / name)


def publish_alias(source: Path, alias: Path) -> None:
    """Replace a convenience pointer without rewriting immutable run files."""
    alias.parent.mkdir(parents=True, exist_ok=True)
    temporary = alias.with_name(f".{alias.name}.{uuid4().hex}")
    try:
        temporary.symlink_to(os.path.relpath(source, alias.parent))
        os.replace(temporary, alias)
    finally:
        temporary.unlink(missing_ok=True)
