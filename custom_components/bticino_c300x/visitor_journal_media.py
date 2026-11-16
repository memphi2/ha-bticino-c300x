"""Read existing capture files by entry-owned identity, never search by time."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

from .media_cache import MAX_MEDIA_BYTES
from .ring_capture import _capture_media_dirs

_CLIP = re.compile(r"doorbell_[0-9]{8}_[0-9]{6}_[0-9a-f]{32}\.mp4\Z", re.ASCII)


def valid_clip(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not _CLIP.fullmatch(raw["name"]):
        return None
    signature = raw.get("signature")
    if not isinstance(signature, list) or len(signature) != 4 or any(type(part) is not int or not 0 <= part < 2**64 for part in signature):
        return None
    if not 0 < signature[2] <= MAX_MEDIA_BYTES:
        return None
    result = {"name": raw["name"], "signature": signature}
    if "changed_ns" in raw:
        changed = raw["changed_ns"]
        if type(changed) is not int or not 0 <= changed < 2**64:
            return None
        result["changed_ns"] = changed
    return result


def _path(hass: Any, name: str) -> Path:
    if not _CLIP.fullmatch(name):
        raise ValueError("Invalid capture name")
    root = _capture_media_dirs(hass)[0]
    if root.is_symlink() or root.resolve().is_relative_to(Path(hass.config.path("www")).resolve()):
        raise ValueError("Capture directory is not private")
    path = root / name
    if path.is_symlink():
        raise ValueError("Capture is a symlink")
    return path


def _signature(info: os.stat_result) -> list[int]:
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def describe_clip(hass: Any, metadata: Any) -> dict[str, Any] | None:
    target = Path(metadata["output_path"])
    path = _path(hass, target.name)
    if path.resolve() != target.resolve():
        return None
    info = path.stat(follow_symlinks=False)
    return valid_clip({"name": path.name, "signature": _signature(info),
                       "changed_ns": info.st_ctime_ns}) if stat.S_ISREG(info.st_mode) else None


def read_clip(hass: Any, clip: Any) -> bytes | None:
    clip = valid_clip(clip)
    if clip is None:
        return None
    path = _path(hass, clip["name"])
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or _signature(info) != clip["signature"]
                or ("changed_ns" in clip and info.st_ctime_ns != clip["changed_ns"])):
            return None
        content = source.read(MAX_MEDIA_BYTES + 1)
        after = os.fstat(source.fileno())
        current = _path(hass, clip["name"]).stat(follow_symlinks=False)
        if (not stat.S_ISREG(current.st_mode)
                or _signature(after) != clip["signature"]
                or _signature(current) != clip["signature"]
                or after.st_ctime_ns != info.st_ctime_ns
                or current.st_ctime_ns != info.st_ctime_ns):
            return None
    return content if len(content) == clip["signature"][2] else None
