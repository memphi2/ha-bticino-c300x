"""Typed call-related device-agent contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .base import AgentContract


@dataclass(frozen=True, slots=True, eq=False)
class RingCallStatus(AgentContract):
    """Normalized doorbell ring-call status."""

    supported: bool
    active: bool
    early_media_active: bool
    audio_active: bool
    answer_requested: bool
    answered: bool
    hangup_requested: bool
    can_answer: bool
    can_hangup: bool
    media_owner: str
    ring_receiver_running: bool
    ring_registered: bool
    capture_supported: bool
    open_fds: int
    active_threads: int
    last_error: str | None


@dataclass(frozen=True, slots=True, eq=False)
class HomeCallStatus(AgentContract):
    """Normalized local Home Call status."""

    available: bool
    running: bool
    active: bool
    answered: bool
    rtp_proxy: bool
    target_audio_port: int | None
    rtp_packets: int
    rtcp_packets: int
    max_duration_seconds: int | None
    last_error: str | None
