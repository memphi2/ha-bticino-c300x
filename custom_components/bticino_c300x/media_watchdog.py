"""Runtime media watchdog helpers for C300X safety handling."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from math import isfinite
from typing import Any

from .camera_media.state_machine import (
    MediaState,
    derive_media_state,
    media_state_input_from_video_status,
)

AGENT_CPU_WATCHDOG_THRESHOLD_PERCENT = 90.0
AGENT_CPU_WATCHDOG_SECONDS = 300.0
_HOME_CALL_STATES = {
    MediaState.HOME_CALL_STARTING,
    MediaState.HOME_CALL_RINGING,
    MediaState.HOME_CALL_ACTIVE,
    MediaState.HOME_CALL_STOPPING,
}
_RING_STATES = {
    MediaState.RING_PENDING,
    MediaState.RING_PREVIEW_ACTIVE,
    MediaState.RING_ANSWERING,
    MediaState.RING_ACTIVE,
    MediaState.RING_HANGING_UP,
}
_DOORBELL_VIDEO_STATES = {
    MediaState.ON_DEMAND_STARTING,
    MediaState.ON_DEMAND_ACTIVE,
    MediaState.RTSP_BUSY,
}


@dataclass
class AgentCpuWatchdog:
    """Track sustained high CPU samples without polling the device."""

    high_since: float | None = None
    tripped: bool = False
    last_percent: float | None = None
    last_reason: str | None = None
    trigger_count: int = 0

    def evaluate(
        self,
        metrics: dict[str, Any],
        now: float,
        *,
        threshold_percent: float = AGENT_CPU_WATCHDOG_THRESHOLD_PERCENT,
        duration_seconds: float = AGENT_CPU_WATCHDOG_SECONDS,
    ) -> str | None:
        """Return a watchdog reason once sustained high CPU crosses the limit."""

        cpu_percent = _optional_float(metrics.get("cpu_usage_percent"))
        if cpu_percent is None:
            return None
        self.last_percent = cpu_percent
        if cpu_percent < threshold_percent:
            self.high_since = None
            self.tripped = False
            return None

        if self.high_since is None:
            self.high_since = now
            return None
        if self.tripped or now - self.high_since < duration_seconds:
            return None

        self.tripped = True
        self.trigger_count += 1
        self.last_reason = (
            f"agent_cpu_high_{cpu_percent:.1f}_percent_"
            f"{int(duration_seconds)}s"
        )
        return self.last_reason


def _optional_float(value: Any) -> float | None:
    """Return a finite float or None for unusable values."""

    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def handle_agent_cpu_metrics_changed(camera: Any, entry_id: str) -> None:
    """Close local camera WebRTC sessions after the entry watchdog trips."""

    if entry_id != camera._entry.entry_id:
        return
    watchdog = getattr(camera._entry.runtime_data, "agent_cpu_watchdog", None)
    if not getattr(watchdog, "tripped", False):
        return
    camera._agent_cpu_watchdog = watchdog
    if camera._webrtc_sessions:
        camera.hass.async_create_task(
            async_handle_agent_cpu_watchdog(
                camera,
                watchdog.last_reason or "agent_cpu_high",
                duration_seconds=int(AGENT_CPU_WATCHDOG_SECONDS),
            )
        )
    camera._async_write_ha_state_if_ready()


def handle_runtime_cpu_metrics_changed(hass: Any, entry: Any) -> None:
    """Evaluate one pushed system-metrics event for the entry safety watchdog."""

    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None:
        return
    metrics = getattr(runtime_data, "system_metrics", {})
    if not isinstance(metrics, dict):
        return
    watchdog = getattr(runtime_data, "agent_cpu_watchdog", None)
    if watchdog is None:
        watchdog = AgentCpuWatchdog()
        with suppress(Exception):
            runtime_data.agent_cpu_watchdog = watchdog
    reason = watchdog.evaluate(
        metrics,
        asyncio.get_running_loop().time(),
        threshold_percent=AGENT_CPU_WATCHDOG_THRESHOLD_PERCENT,
        duration_seconds=AGENT_CPU_WATCHDOG_SECONDS,
    )
    if reason is None:
        return

    task = getattr(runtime_data, "agent_cpu_watchdog_task", None)
    if task is not None and not task.done():
        return
    task = _schedule_task(
        hass,
        async_handle_runtime_agent_cpu_watchdog(
            hass,
            entry,
            reason,
            duration_seconds=int(AGENT_CPU_WATCHDOG_SECONDS),
        ),
    )
    with suppress(Exception):
        runtime_data.agent_cpu_watchdog_task = task


def _schedule_task(hass: Any, coro: Any) -> asyncio.Task[Any]:
    """Schedule a coroutine on Home Assistant or the current event loop."""

    create_task = getattr(hass, "async_create_task", None)
    if callable(create_task):
        return create_task(coro)
    return asyncio.create_task(coro)


async def async_handle_runtime_agent_cpu_watchdog(
    hass: Any,
    entry: Any,
    reason: str,
    *,
    duration_seconds: int,
) -> None:
    """Report sustained CPU load and stop native HA-owned media."""

    runtime_data = getattr(entry, "runtime_data", None)
    watchdog = getattr(runtime_data, "agent_cpu_watchdog", None)
    with suppress(Exception):
        from .repair_issues import async_create_media_watchdog_issue

        async_create_media_watchdog_issue(
            hass,
            entry,
            reason=reason,
            cpu_percent=getattr(watchdog, "last_percent", None),
            duration_seconds=duration_seconds,
        )

    api = getattr(runtime_data, "api", None)
    if api is None:
        return

    status: dict[str, Any] | None = None
    with suppress(Exception):
        status = await api.async_doorbell_video_status()
    await _async_stop_media_for_watchdog(api, status)
    await _async_reload_display_gui_for_watchdog(api)


async def async_handle_agent_cpu_watchdog(
    camera: Any,
    reason: str,
    *,
    duration_seconds: int,
) -> None:
    """Report sustained CPU load and stop HA-owned media from the camera entity."""

    entry = camera._entry
    with suppress(Exception):
        from .repair_issues import async_create_media_watchdog_issue

        async_create_media_watchdog_issue(
            camera.hass,
            entry,
            reason=reason,
            cpu_percent=camera._agent_cpu_watchdog.last_percent,
            duration_seconds=duration_seconds,
        )

    if camera._webrtc_sessions:
        for session_id in list(camera._webrtc_sessions):
            await camera._async_close_webrtc_session(
                session_id,
                stop_media=False,
                notify_client=True,
                reason="agent_cpu_watchdog",
            )
        await _async_reload_display_gui_for_watchdog(entry.runtime_data.api)
        return

    with suppress(Exception):
        await camera._async_refresh_video_status(apply_status=True)
    await _async_stop_media_for_watchdog(
        entry.runtime_data.api,
        {
            "media_owner": camera._video_owner,
            "window_available": camera._video_window_available,
            "external_media_active": camera._external_media_active,
            "bridge": camera._bridge_status,
        },
    )
    await _async_reload_display_gui_for_watchdog(entry.runtime_data.api)


async def _async_stop_media_for_watchdog(
    api: Any,
    status: dict[str, Any] | None,
) -> None:
    """Stop media paths that can be owned by Home Assistant."""

    if status is None:
        with suppress(Exception):
            await api.async_hangup_doorbell_call()
        with suppress(Exception):
            await api.async_stop_home_call()
        with suppress(Exception):
            await api.async_stop_doorbell_video()
        return

    decision = derive_media_state(media_state_input_from_video_status(status))

    if decision.external_owner_blocks:
        return
    if decision.state in _HOME_CALL_STATES:
        with suppress(Exception):
            await api.async_stop_home_call()
        return
    if decision.state in _RING_STATES:
        with suppress(Exception):
            await api.async_hangup_doorbell_call()
        with suppress(Exception):
            await api.async_stop_doorbell_video()
        return
    if decision.state in _DOORBELL_VIDEO_STATES:
        with suppress(Exception):
            await api.async_stop_doorbell_video()


async def _async_reload_display_gui_for_watchdog(api: Any) -> None:
    """Reload the display GUI after sustained high CPU watchdog trips."""

    reload_gui = getattr(api, "async_reload_gui", None)
    if not callable(reload_gui):
        return
    with suppress(Exception):
        await reload_gui()
