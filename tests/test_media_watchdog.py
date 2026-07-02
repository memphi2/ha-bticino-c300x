from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.bticino_c300x.media_watchdog import (
    AgentCpuWatchdog,
    _async_stop_media_for_watchdog,
    _schedule_task,
    async_handle_agent_cpu_watchdog,
    async_handle_runtime_agent_cpu_watchdog,
    handle_agent_cpu_metrics_changed,
    handle_runtime_cpu_metrics_changed,
)


class _Api:
    def __init__(self) -> None:
        self.hangup_calls = 0
        self.stop_calls = 0
        self.home_call_stop_calls = 0
        self.reload_gui_calls = 0

    async def async_hangup_doorbell_call(self) -> dict[str, bool]:
        self.hangup_calls += 1
        return {"ok": True}

    async def async_stop_doorbell_video(self) -> dict[str, bool]:
        self.stop_calls += 1
        return {"ok": True}

    async def async_stop_home_call(self) -> dict[str, bool]:
        self.home_call_stop_calls += 1
        return {"ok": True}

    async def async_reload_gui(self) -> dict[str, bool]:
        self.reload_gui_calls += 1
        return {"ok": True}


def test_agent_cpu_watchdog_counts_real_triggers_once_per_high_run() -> None:
    watchdog = AgentCpuWatchdog()

    assert (
        watchdog.evaluate(
            {"cpu_usage_percent": 95.0},
            0.0,
            threshold_percent=90.0,
            duration_seconds=5.0,
        )
        is None
    )
    assert watchdog.evaluate(
        {"cpu_usage_percent": 96.0},
        5.0,
        threshold_percent=90.0,
        duration_seconds=5.0,
    )
    assert watchdog.trigger_count == 1
    assert (
        watchdog.evaluate(
            {"cpu_usage_percent": 97.0},
            10.0,
            threshold_percent=90.0,
            duration_seconds=5.0,
        )
        is None
    )
    assert watchdog.trigger_count == 1

    assert (
        watchdog.evaluate(
            {"cpu_usage_percent": 10.0},
            11.0,
            threshold_percent=90.0,
            duration_seconds=5.0,
        )
        is None
    )
    watchdog.evaluate(
        {"cpu_usage_percent": 95.0},
        12.0,
        threshold_percent=90.0,
        duration_seconds=5.0,
    )
    assert watchdog.evaluate(
        {"cpu_usage_percent": 96.0},
        17.0,
        threshold_percent=90.0,
        duration_seconds=5.0,
    )
    assert watchdog.trigger_count == 2


def test_agent_cpu_watchdog_ignores_unusable_cpu_values() -> None:
    watchdog = AgentCpuWatchdog()

    for value in (None, True, "busy", float("nan"), float("inf")):
        assert watchdog.evaluate({"cpu_usage_percent": value}, 0.0) is None

    assert watchdog.high_since is None
    assert watchdog.trigger_count == 0


def test_agent_cpu_metric_signal_ignores_wrong_or_untripped_entry() -> None:
    class _RuntimeData:
        agent_cpu_watchdog = AgentCpuWatchdog()

    class _Entry:
        entry_id = "entry-1"
        runtime_data = _RuntimeData()

    class _Camera:
        _entry = _Entry()
        writes = 0

        def _webrtc_session_ids(self) -> list[str]:
            return []

        def _async_write_ha_state_if_ready(self) -> None:
            self.writes += 1

    camera = _Camera()

    handle_agent_cpu_metrics_changed(camera, "other-entry")
    handle_agent_cpu_metrics_changed(camera, "entry-1")

    assert camera.writes == 0


def test_runtime_cpu_metric_signal_ignores_missing_runtime_or_metrics() -> None:
    class _EntryWithoutRuntime:
        pass

    class _RuntimeData:
        system_metrics = []
        agent_cpu_watchdog = AgentCpuWatchdog()

    class _EntryWithBadMetrics:
        runtime_data = _RuntimeData()

    handle_runtime_cpu_metrics_changed(object(), _EntryWithoutRuntime())
    handle_runtime_cpu_metrics_changed(object(), _EntryWithBadMetrics())

    assert _RuntimeData.agent_cpu_watchdog.trigger_count == 0


def test_media_watchdog_stops_ring_call_from_bridge_state() -> None:
    api = _Api()

    asyncio.run(
        _async_stop_media_for_watchdog(
            api,
            {
                "media_owner": "unknown",
                "bridge": {"media_owner": "ring", "ring_call_active": True},
            },
        )
    )

    assert api.hangup_calls == 1
    assert api.stop_calls == 1
    assert api.home_call_stop_calls == 0


def test_media_watchdog_stops_all_local_media_when_status_is_missing() -> None:
    api = _Api()

    asyncio.run(_async_stop_media_for_watchdog(api, None))

    assert api.hangup_calls == 1
    assert api.home_call_stop_calls == 1
    assert api.stop_calls == 1


def test_media_watchdog_does_not_stop_external_owner() -> None:
    api = _Api()

    asyncio.run(
        _async_stop_media_for_watchdog(
            api,
            {
                "media_owner": "external_media",
                "external_media_active": True,
                "external_owner": "smartphone",
                "bridge": {"media_owner": "external_media"},
            },
        )
    )

    assert api.hangup_calls == 0
    assert api.home_call_stop_calls == 0
    assert api.stop_calls == 0


def test_media_watchdog_stops_home_call_from_bridge_state() -> None:
    api = _Api()

    asyncio.run(
        _async_stop_media_for_watchdog(
            api,
            {
                "media_owner": "unknown",
                "bridge": {"media_owner": "home_call", "home_call_active": True},
            },
        )
    )

    assert api.home_call_stop_calls == 1
    assert api.hangup_calls == 0
    assert api.stop_calls == 0


def test_media_watchdog_stops_on_demand_from_state_machine_status() -> None:
    api = _Api()

    asyncio.run(
        _async_stop_media_for_watchdog(
            api,
            {
                "media_owner": "agent",
                "window_available": True,
                "bridge": {"media_owner": "agent", "clients": 1},
            },
        )
    )

    assert api.stop_calls == 1
    assert api.hangup_calls == 0
    assert api.home_call_stop_calls == 0


def test_media_watchdog_stops_unknown_rtsp_busy_state() -> None:
    api = _Api()

    asyncio.run(
        _async_stop_media_for_watchdog(
            api,
            {
                "media_owner": "idle",
                "window_available": False,
                "bridge": {"media_owner": "idle", "clients": 1},
            },
        )
    )

    assert api.stop_calls == 1
    assert api.hangup_calls == 0
    assert api.home_call_stop_calls == 0


def test_runtime_watchdog_returns_without_api() -> None:
    class _RuntimeData:
        agent_cpu_watchdog = AgentCpuWatchdog(last_percent=99.0)

    class _Entry:
        runtime_data = _RuntimeData()

    asyncio.run(
        async_handle_runtime_agent_cpu_watchdog(
            object(),
            _Entry(),
            "agent_cpu_high",
            duration_seconds=300,
        )
    )


def test_runtime_watchdog_does_not_schedule_duplicate_stop_task() -> None:
    class _Task:
        def done(self) -> bool:
            return False

    task = _Task()
    runtime_data = SimpleNamespace(
        system_metrics={"cpu_usage_percent": 95.0},
        agent_cpu_watchdog=AgentCpuWatchdog(high_since=0.0),
        agent_cpu_watchdog_task=task,
    )
    entry = SimpleNamespace(runtime_data=runtime_data)

    async def _run() -> None:
        runtime_data.agent_cpu_watchdog.high_since = (
            asyncio.get_running_loop().time() - 301.0
        )
        handle_runtime_cpu_metrics_changed(object(), entry)

    asyncio.run(_run())

    assert runtime_data.agent_cpu_watchdog.trigger_count == 1
    assert runtime_data.agent_cpu_watchdog_task is task


def test_camera_watchdog_refreshes_status_and_stops_on_demand_without_sessions() -> None:
    api = _Api()
    runtime_data = SimpleNamespace(
        agent_cpu_watchdog=AgentCpuWatchdog(last_percent=99.0),
        api=api,
    )
    entry = SimpleNamespace(runtime_data=runtime_data)

    class _Camera:
        hass = object()
        _entry = entry
        _agent_cpu_watchdog = runtime_data.agent_cpu_watchdog
        _video_owner = "agent"
        _video_window_available = True
        _external_media_active = False
        _bridge_status = {"media_owner": "agent", "clients": 1}
        refreshed = False

        async def _async_refresh_video_status(self, *, apply_status: bool) -> None:
            assert apply_status is True
            self.refreshed = True

        def _webrtc_session_ids(self) -> list[str]:
            return []

    camera = _Camera()

    asyncio.run(
        async_handle_agent_cpu_watchdog(
            camera,
            "agent_cpu_high",
            duration_seconds=300,
        )
    )

    assert camera.refreshed is True
    assert api.stop_calls == 1
    assert api.reload_gui_calls == 1


def test_schedule_task_uses_running_loop_without_hass_helper() -> None:
    async def _noop() -> str:
        return "ok"

    async def _run() -> str:
        task = _schedule_task(object(), _noop())
        return await task

    assert asyncio.run(_run()) == "ok"


def test_media_watchdog_does_not_stop_external_media() -> None:
    api = _Api()

    asyncio.run(
        _async_stop_media_for_watchdog(
            api,
            {
                "external_media_active": True,
                "window_available": True,
                "bridge": {"external_media_active": True},
            },
        )
    )

    assert api.hangup_calls == 0
    assert api.home_call_stop_calls == 0
    assert api.stop_calls == 0
