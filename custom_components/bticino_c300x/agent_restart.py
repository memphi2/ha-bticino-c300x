"""Camera self-heal after an agent restart.

A restarted agent has lost every call and stream, and it sends no end event
for them. Home Assistant sees the restart only as a new instance id in the
metrics heartbeat, so that heartbeat makes the camera ask for the real status
once, also when it holds no session of its own.
"""

from __future__ import annotations

from typing import Any

from .camera_media.state_machine import MediaState


def _restart_count(camera: Any) -> int:
    diagnostics = getattr(camera._runtime_data, "diagnostics", None)
    return int(getattr(diagnostics, "agent_restart_count", 0) or 0)


def agent_restart_pending(camera: Any) -> bool:
    """Whether a restart was counted that the camera has not reconciled yet."""

    count = _restart_count(camera)
    if not hasattr(camera, "_agent_restart_reconciled"):
        camera._agent_restart_reconciled = count
    return count != camera._agent_restart_reconciled


def reconcile_due(camera: Any, entry_id: str) -> bool:
    """Whether this metrics heartbeat should start a status reconcile."""

    if entry_id != camera._entry.entry_id or camera._reconcile_in_flight:
        return False
    camera._agent_restart_due = _restart_count(camera)
    # Asked first: the first heartbeat sets the baseline, sessions or not.
    pending = agent_restart_pending(camera)
    # RTSP_BUSY comes from client counts alone: no agent event ends it, so a
    # count read mid-start would hold it after the last session is gone.
    # EXTERNAL_MEDIA_ACTIVE ends with the display call's bus end frame; when
    # that frame is lost the agent's guard expires without an event. The
    # status read keeps it while the agent still reports the display call.
    return (
        pending
        or bool(camera._webrtc_sessions.active)
        or camera._last_media_state
        in (MediaState.RTSP_BUSY, MediaState.EXTERNAL_MEDIA_ACTIVE)
    )


def note_status_reconciled(camera: Any, status: Any) -> None:
    """Both status reads settle the restart; a failed read is retried.

    A call the camera still shows after the reads is either live on the new
    agent or its status read failed, so the next heartbeat asks again."""

    if status is not None and not camera._cached_home_call_state_needs_refresh():
        camera._agent_restart_reconciled = getattr(
            camera, "_agent_restart_due", _restart_count(camera)
        )
