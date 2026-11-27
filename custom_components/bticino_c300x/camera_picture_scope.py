"""Learn the on-demand picture control scope once per on-demand session.

The agent reports ``picture_controls_scope: "ring_and_on_demand"`` in its video
status on every supported station. The camera does not poll and agent events do
not carry the scope, so without a status read here the card's tune button came
late, never, or from an earlier session.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .camera_media.state_machine import MediaState

# The station applies the outdoor unit's stored picture values when the video
# starts; the tune button appears once that has happened.
PICTURE_SCOPE_REFRESH_DELAY_SECONDS = 2.0
_SHARED_SCOPE = "ring_and_on_demand"
_TASK_KEY = "picture_scope"
# A ring may also have verified direct control; any other state has no media
# the scope could describe.
_SCOPE_STATES = frozenset({
    MediaState.ON_DEMAND_ACTIVE,
    MediaState.RING_PENDING,
    MediaState.RING_PREVIEW_ACTIVE,
    MediaState.RING_ANSWERING,
    MediaState.RING_ACTIVE,
})


def track_picture_scope(camera: Any) -> None:
    """Call after every derived media-state change of the doorbell camera."""

    state = camera._last_media_state
    previous = getattr(camera, "_picture_scope_state", None)
    camera._picture_scope_state = state
    # Only the end of the media drops the scope; a status the agent sent is kept.
    if (previous in _SCOPE_STATES and state not in _SCOPE_STATES
            and camera._bridge_status.get("picture_controls_scope") == _SHARED_SCOPE):
        camera._bridge_status = {**camera._bridge_status, "picture_controls_scope": "ring"}
    if (state is MediaState.ON_DEMAND_ACTIVE) == (previous is MediaState.ON_DEMAND_ACTIVE):
        return
    # Each session gets its own refresh the full delay after its own start; an
    # ended session's refresh must neither read early in the next one nor take
    # the next one's place.
    camera._picture_scope_session = getattr(camera, "_picture_scope_session", 0) + 1
    camera._background_tasks.cancel(_TASK_KEY)
    if state is MediaState.ON_DEMAND_ACTIVE and getattr(camera, "hass", None) is not None:
        camera._background_tasks.create(
            camera.hass, _async_refresh_scope(camera, camera._picture_scope_session), key=_TASK_KEY)


async def _async_refresh_scope(camera: Any, session: int) -> None:
    await asyncio.sleep(PICTURE_SCOPE_REFRESH_DELAY_SECONDS)
    if (camera._picture_scope_session != session
            or camera._last_media_state is not MediaState.ON_DEMAND_ACTIVE):
        return
    if await camera._async_refresh_video_status_or_none() is not None:
        camera._async_write_ha_state_if_ready()
