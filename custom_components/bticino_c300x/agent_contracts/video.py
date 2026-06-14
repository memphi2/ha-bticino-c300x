"""Typed video-related device-agent contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import AgentContract


@dataclass(frozen=True, slots=True, eq=False)
class DoorbellVideoStatus(AgentContract):
    """Normalized doorbell video and RTSP bridge status."""

    available: bool
    window_available: bool
    stream_path: str | None
    audio_stream_path: str | None
    recorder_stream_path: str | None
    media_owner: str
    external_media_active: bool
    external_owner: str | None
    last_block_reason: str | None
    bridge: dict[str, Any]
