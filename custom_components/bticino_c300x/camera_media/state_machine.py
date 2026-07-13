"""Explicit media state derivation for C300X camera sessions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from ..value_parsing import (
    optional_int as _optional_int,
)
from ..value_parsing import (
    optional_string as _optional_string,
)

# Only an explicit idle/empty owner counts as positively idle. "unknown" means
# the owner is not known -- an ambiguous state, never a destructive idle signal.
IDLE_MEDIA_OWNERS = frozenset({"", "idle"})


def status_reports_agent_idle(
    status: Mapping[str, object] | None,
    *,
    cached_video_owner: str | None = None,
    cached_video_window_available: bool = False,
    cached_external_media_active: bool = False,
) -> bool:
    """Whether the agent positively reports no live media (clients == 0, idle
    owner, no active/starting/stopping flags). An empty or unknown status is
    never treated as idle, so real media is never false-idled and a ready HA
    WebRTC session is only discounted when the device really is idle."""

    if not status:
        return False
    bridge = status.get("bridge")
    bridge = bridge if isinstance(bridge, Mapping) else {}
    clients = _optional_int(bridge.get("clients"))
    if clients is None or clients > 0:
        return False
    window = status.get("window_available")
    if bool(cached_video_window_available if window is None else window):
        return False
    if bool(bridge.get("media_active")) or bool(bridge.get("media_starting")):
        return False
    if bool(bridge.get("stop_in_progress")):
        return False
    external = status.get("external_media_active")
    if bool(
        cached_external_media_active if external is None else external
    ) or bool(bridge.get("external_media_active")):
        return False
    owner = (
        str(
            _optional_string(status.get("media_owner"))
            or _optional_string(bridge.get("media_owner"))
            or cached_video_owner
            or "idle"
        )
        .strip()
        .lower()
    )
    return owner in IDLE_MEDIA_OWNERS


class MediaState(StrEnum):
    """Derived C300X media state."""

    IDLE = "idle"
    ON_DEMAND_STARTING = "on_demand_starting"
    ON_DEMAND_ACTIVE = "on_demand_active"
    RING_PENDING = "ring_pending"
    RING_PREVIEW_ACTIVE = "ring_preview_active"
    RING_ANSWERING = "ring_answering"
    RING_ACTIVE = "ring_active"
    RING_HANGING_UP = "ring_hanging_up"
    HOME_CALL_STARTING = "home_call_starting"
    HOME_CALL_RINGING = "home_call_ringing"
    HOME_CALL_ACTIVE = "home_call_active"
    HOME_CALL_STOPPING = "home_call_stopping"
    EXTERNAL_MEDIA_ACTIVE = "external_media_active"
    RTSP_BUSY = "rtsp_busy"
    ERROR = "error"
    COOLDOWN = "cooldown"
    UNKNOWN = "unknown"


class MediaPrimaryAction(StrEnum):
    """Primary action currently allowed by the derived state."""

    NONE = "none"
    START_STREAM = "start_stream"
    ANSWER_RING = "answer_ring"
    HANGUP = "hangup"
    STOP_STREAM = "stop_stream"
    WAIT = "wait"
    REFRESH = "refresh"


@dataclass(frozen=True)
class MediaStateInput:
    """Facts used to derive media state."""

    video_owner: str | None = None
    video_window_available: bool = False
    external_media_active: bool = False
    external_owner: str | None = None
    ring_call_active: bool = False
    ring_media_active: bool = False
    ring_audio_active: bool = False
    ring_answered: bool = False
    ring_answer_requested: bool = False
    ring_hangup_requested: bool = False
    unanswered_ring_call: bool = False
    home_call_running: bool = False
    home_call_active: bool = False
    home_call_answered: bool = False
    home_call_stopping: bool = False
    rtsp_clients: int | None = None
    local_sessions: int = 0
    last_error: str | None = None
    cooldown_active: bool = False
    entry_video_enabled: bool = True
    capability_doorbell_video: bool = True
    capability_doorbell_call: bool = True
    capability_home_call: bool = True


@dataclass(frozen=True)
class MediaStateOutput:
    """Derived state and safe follow-up decisions."""

    state: MediaState
    primary_action: MediaPrimaryAction
    rtsp_start_allowed: bool
    capture_blocked: bool
    webrtc_keepalive_allowed: bool
    refresh_status_required: bool
    external_owner_blocks: bool
    local_owner_reusable: bool


def media_state_input_from_video_status(
    status: Mapping[str, object] | None,
    *,
    cached_video_owner: str | None = None,
    cached_video_window_available: bool = False,
    cached_external_media_active: bool = False,
    cached_external_owner: str | None = None,
    local_sessions: int = 0,
    last_error: str | None = None,
    cooldown_active: bool = False,
    entry_video_enabled: bool = True,
    capability_doorbell_video: bool = True,
    capability_doorbell_call: bool = True,
    capability_home_call: bool = True,
) -> MediaStateInput:
    """Build media-state facts from normalized native-agent video status."""

    bridge = _status_bridge(status)
    video_owner = (
        _optional_string(_status_value(status, "media_owner"))
        or _optional_string(_status_value(status, "video_owner"))
        or _optional_string(bridge.get("media_owner"))
        or _optional_string(bridge.get("video_owner"))
        or cached_video_owner
    )
    external_media_active = (
        _status_bool(status, "external_media_active", cached_external_media_active)
        or bool(bridge.get("external_media_active"))
    )
    external_owner = (
        _optional_string(_status_value(status, "external_owner"))
        or _optional_string(bridge.get("external_owner"))
        or cached_external_owner
    )
    return MediaStateInput(
        video_owner=video_owner,
        video_window_available=_status_bool(
            status,
            "window_available",
            cached_video_window_available,
        ),
        external_media_active=external_media_active,
        external_owner=external_owner,
        ring_call_active=bool(bridge.get("ring_call_active")),
        ring_media_active=bool(bridge.get("ring_media_active")),
        ring_audio_active=bool(bridge.get("ring_audio_active")),
        ring_answered=bool(bridge.get("ring_answered")),
        ring_answer_requested=bool(bridge.get("ring_answer_requested")),
        ring_hangup_requested=bool(bridge.get("ring_hangup_requested")),
        unanswered_ring_call=bool(bridge.get("unanswered_ring_call")),
        home_call_running=bool(bridge.get("home_call_running")),
        home_call_active=bool(bridge.get("home_call_active")),
        home_call_answered=bool(bridge.get("home_call_answered")),
        home_call_stopping=bool(bridge.get("home_call_stopping")),
        rtsp_clients=_optional_int(bridge.get("clients")),
        local_sessions=local_sessions,
        last_error=last_error,
        cooldown_active=cooldown_active,
        entry_video_enabled=entry_video_enabled,
        capability_doorbell_video=capability_doorbell_video,
        capability_doorbell_call=capability_doorbell_call,
        capability_home_call=capability_home_call,
    )


def derive_media_state(facts: MediaStateInput) -> MediaStateOutput:
    """Derive a media state from factual agent/session inputs."""

    if facts.cooldown_active:
        return _output(
            MediaState.COOLDOWN,
            MediaPrimaryAction.WAIT,
            capture_blocked=True,
            webrtc_keepalive_allowed=False,
        )
    if facts.last_error:
        return _output(
            MediaState.ERROR,
            MediaPrimaryAction.REFRESH,
            capture_blocked=True,
            webrtc_keepalive_allowed=False,
        )
    if not facts.entry_video_enabled or not facts.capability_doorbell_video:
        return _output(
            MediaState.UNKNOWN,
            MediaPrimaryAction.NONE,
            capture_blocked=True,
            webrtc_keepalive_allowed=False,
        )

    if facts.external_media_active or _owner(facts) == "external_media":
        return _output(
            MediaState.EXTERNAL_MEDIA_ACTIVE,
            MediaPrimaryAction.NONE,
            capture_blocked=True,
            webrtc_keepalive_allowed=False,
            external_owner_blocks=True,
        )

    if (
        _owner(facts) == "home_call"
        or facts.home_call_running
        or facts.home_call_active
        or facts.home_call_answered
    ):
        if facts.home_call_stopping:
            return _output(
                MediaState.HOME_CALL_STOPPING,
                MediaPrimaryAction.WAIT,
                capture_blocked=True,
            )
        if facts.home_call_answered:
            return _output(
                MediaState.HOME_CALL_ACTIVE,
                MediaPrimaryAction.HANGUP,
                capture_blocked=True,
            )
        if facts.home_call_running or facts.home_call_active:
            return _output(
                MediaState.HOME_CALL_RINGING,
                MediaPrimaryAction.HANGUP,
                capture_blocked=True,
            )
        return _output(
            MediaState.HOME_CALL_STARTING,
            MediaPrimaryAction.WAIT,
            capture_blocked=True,
        )

    if facts.ring_hangup_requested:
        return _output(
            MediaState.RING_HANGING_UP,
            MediaPrimaryAction.WAIT,
            capture_blocked=True,
        )
    if (
        _owner(facts) == "ring"
        or facts.ring_call_active
        or facts.ring_media_active
        or facts.ring_audio_active
        or facts.ring_answered
        or facts.unanswered_ring_call
    ):
        answered_ring_call = facts.ring_answered or facts.ring_audio_active
        unanswered_ring_call = not (facts.ring_answer_requested or answered_ring_call)
        if facts.ring_answer_requested:
            return _output(
                MediaState.RING_ANSWERING,
                MediaPrimaryAction.WAIT,
                local_owner_reusable=True,
            )
        if unanswered_ring_call and facts.ring_media_active:
            return _output(
                MediaState.RING_PREVIEW_ACTIVE,
                MediaPrimaryAction.ANSWER_RING,
                local_owner_reusable=True,
            )
        if unanswered_ring_call:
            return _output(MediaState.RING_PENDING, MediaPrimaryAction.ANSWER_RING)
        if facts.ring_media_active or answered_ring_call:
            return _output(
                MediaState.RING_ACTIVE,
                MediaPrimaryAction.HANGUP,
                local_owner_reusable=True,
            )
        return _output(MediaState.RING_PENDING, MediaPrimaryAction.ANSWER_RING)

    if _owner(facts) == "agent":
        if not facts.video_window_available:
            return _output(
                MediaState.ON_DEMAND_STARTING,
                MediaPrimaryAction.WAIT,
                capture_blocked=True,
            )
        if facts.rtsp_clients != 0 or facts.local_sessions != 0:
            return _output(
                MediaState.ON_DEMAND_ACTIVE,
                MediaPrimaryAction.STOP_STREAM,
                capture_blocked=True,
            )
        # video_window_available can lag one status poll behind a stop that
        # already dropped every real client; fall through to be
        # re-evaluated below instead of reporting a stoppable stream that
        # nothing is actually using.

    active_clients = (facts.rtsp_clients or 0) + facts.local_sessions
    if active_clients > 0:
        return _output(MediaState.RTSP_BUSY, MediaPrimaryAction.WAIT, capture_blocked=True)

    if _owner(facts) in {"idle", ""}:
        return _output(
            MediaState.IDLE,
            MediaPrimaryAction.START_STREAM,
            rtsp_start_allowed=True,
        )

    return _output(
        MediaState.UNKNOWN,
        MediaPrimaryAction.REFRESH,
        capture_blocked=True,
        webrtc_keepalive_allowed=False,
        refresh_status_required=True,
    )


def _owner(facts: MediaStateInput) -> str:
    return str(facts.video_owner or "").strip().lower()


def _status_bridge(status: Mapping[str, object] | None) -> Mapping[str, object]:
    if status is None:
        return {}
    bridge = status.get("bridge")
    return bridge if isinstance(bridge, Mapping) else {}


def _status_value(status: Mapping[str, object] | None, key: str) -> object | None:
    return status.get(key) if status is not None else None


def _status_bool(
    status: Mapping[str, object] | None,
    key: str,
    fallback: bool,
) -> bool:
    if status is not None and key in status:
        return bool(status.get(key))
    return fallback


def _output(
    state: MediaState,
    primary_action: MediaPrimaryAction,
    *,
    rtsp_start_allowed: bool = False,
    capture_blocked: bool = False,
    webrtc_keepalive_allowed: bool = True,
    refresh_status_required: bool = False,
    external_owner_blocks: bool = False,
    local_owner_reusable: bool = False,
) -> MediaStateOutput:
    return MediaStateOutput(
        state=state,
        primary_action=primary_action,
        rtsp_start_allowed=rtsp_start_allowed,
        capture_blocked=capture_blocked,
        webrtc_keepalive_allowed=webrtc_keepalive_allowed,
        refresh_status_required=refresh_status_required,
        external_owner_blocks=external_owner_blocks,
        local_owner_reusable=local_owner_reusable,
    )
