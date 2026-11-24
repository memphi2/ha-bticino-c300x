"""Camera facts after the agent reports the doorbell media window closed."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Transient start/stop flags belong to the window that just closed, like the
# home-call path already clears them. Leaving them behind in the cumulative
# bridge view republishes them as live state.
CLOSED_WINDOW_BRIDGE_FACTS: Mapping[str, Any] = {
    "media_owner": "idle",
    "media_active": False,
    "media_starting": False,
    "stop_in_progress": False,
    "external_media_active": False,
    "ring_call_active": False,
    "ring_media_active": False,
    "ring_audio_active": False,
    "ring_answer_requested": False,
    "ring_answered": False,
    "ring_hangup_requested": False,
    "unanswered_ring_call": False,
    "call_active": False,
    "clients": 0,
}


def closed_window_bridge_status(bridge_status: Mapping[str, Any]) -> dict[str, Any]:
    """Return the cached bridge view with the closed window's facts reset."""

    return {**bridge_status, **CLOSED_WINDOW_BRIDGE_FACTS}


def external_media_outlives_close(data: Mapping[str, Any]) -> bool:
    """Whether the station still shows the call after HA's window closed.

    A display that answers a ring makes the station cancel the agent's ring
    leg. The agent then closes HA's ring window while its payload still
    reports the display's external media, which ends with its own event.
    """

    return data.get("external_media_active") is True
