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
    # Older agents did not gate UDP on a played RTSP connection.
    talkback_ready: bool = True


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


@dataclass(frozen=True, slots=True)
class OutdoorUnit:
    """One outdoor unit of the station; ``id`` is its where with '_' for '#'."""

    id: str
    where: str
    action_where: str
    lock_where: str
    name: str
    source: str
    default: bool


@dataclass(frozen=True, slots=True, eq=False)
class OutdoorUnitsPayload(AgentContract):
    """``GET /api/v1/outdoor-units``."""

    units: tuple[OutdoorUnit, ...]
    default_unit: str | None
    archive: str


@dataclass(frozen=True, slots=True)
class Call:
    """One call as the agent owns it."""

    call_id: str
    kind: str
    state: str
    unit: str | None
    attribution: str
    answered_by: str | None
    end_reason: str | None


@dataclass(frozen=True, slots=True, eq=False)
class CallsPayload(AgentContract):
    """``GET /api/v1/calls``."""

    boot_id: str
    current_call_id: str | None
    calls: tuple[Call, ...]
