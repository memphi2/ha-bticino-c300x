"""Failed bridge reconciliation remains owned by the registration lifecycle."""

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, Mock

import pytest
from test_events import (
    _active_scheduled_delays,
    _drain_hass_tasks,
    _FakeApi,
    _FakeEntry,
    _FakeHass,
    event_ha_boundary,  # noqa: F401
)

from custom_components.bticino_c300x import callback_url, events, runtime_manager
from custom_components.bticino_c300x.api_errors import (
    C300XAgentApiConnectionError,
    C300XAgentApiUnsupportedError,
)
from custom_components.bticino_c300x.data import (
    BticinoC300XRuntimeData,
    C300XConnectionState,
    C300XEventState,
)


class Api(_FakeApi):
    def __init__(self):
        super().__init__([{"subscription": {"id": "sub"}}])
        self.async_display_bridge_status = AsyncMock(return_value={"configured": False})
        self.async_configure_display_bridge = AsyncMock()
        self.async_notify_display_bridge_event = AsyncMock()

    async def async_register_event_subscription(self, **kwargs):
        result = await super().async_register_event_subscription(**kwargs)
        self.subscriptions = [{
            "id": "sub", "callback_url": kwargs["callback_url"],
            "token_fingerprint": events.event_token_fingerprint(kwargs["token"]),
            "events": kwargs["events"],
        }]
        return result


def setup(monkeypatch, *, no_events=False):
    hass, entry, api = _FakeHass(), _FakeEntry(), Api()
    entry.data.update(webhook_id="display", shared_secret="secret", device_ui_enabled=True)
    runtime = entry.runtime_data = BticinoC300XRuntimeData(
        api=api, capabilities={}, event_state=C300XEventState(),
        connection_state=C300XConnectionState(), agent_info={}, loaded_platforms=(),
    )
    monkeypatch.setattr(callback_url, "async_generate_agent_callback_url", AsyncMock(return_value="http://ha/display"))
    monkeypatch.setattr(events, "_active_events_for_capabilities", lambda *_: [] if no_events else ["doorbell.pressed"])
    monkeypatch.setattr(events, "_sync_repair_issues", Mock())

    async def refresh():
        await runtime_manager._async_configure_display_bridge(hass, entry, api)

    worker = events._AgentEventRegistration(hass, entry, api, {}, runtime.connection_state, refresh)
    runtime.resources.unregister_event_registration = worker.unregister
    runtime.resources.on_runtime_registration_created = refresh
    return hass, entry, api, worker


@pytest.mark.parametrize("failure", ["status", "configure"])
@pytest.mark.parametrize("restart", [False, True])
def test_bridge_failure_retries_without_recreating_subscription(monkeypatch, failure, restart):
    async def run():
        hass, entry, api, worker = setup(monkeypatch)
        failing = api.async_display_bridge_status if failure == "status" else api.async_configure_display_bridge
        failing.side_effect = C300XAgentApiConnectionError("temporary failure")
        try:
            await worker._register()
            runtime = entry.runtime_data
            assert runtime.resources.display_bridge_registration_pending
            assert runtime.connection_state.available
            assert runtime.connection_state.event_subscription_last_error is None
            assert _active_scheduled_delays() == [300]
            failing.side_effect = None
            if restart:
                assert events.async_request_agent_event_registration(hass, entry)
                await _drain_hass_tasks(hass)
                worker = runtime.resources.unregister_event_registration.__self__
            else:
                await worker._register()
            assert not runtime.resources.display_bridge_registration_pending
            assert runtime.diagnostics.display_bridge_diagnostics.last_error is None
            assert len(api.subscription_calls) == 1
            attempts = api.async_display_bridge_status.await_count
            await worker._register()
            assert api.async_display_bridge_status.await_count == attempts
            assert _active_scheduled_delays() == [300]
        finally:
            entry.runtime_data.resources.close()
        assert _active_scheduled_delays() == []

    asyncio.run(run())


def test_pending_startup_bridge_without_events_keeps_one_recovery_timer(monkeypatch):
    async def run():
        hass, entry, api, worker = setup(monkeypatch, no_events=True)
        api.async_configure_display_bridge.side_effect = C300XAgentApiConnectionError("temporary failure")
        await runtime_manager._async_configure_display_bridge(hass, entry, api)
        try:
            await worker._register()
            assert entry.runtime_data.resources.display_bridge_registration_pending
            assert _active_scheduled_delays() == [300]
            api.async_configure_display_bridge.side_effect = None
            await worker._register()
            assert not entry.runtime_data.resources.display_bridge_registration_pending
            assert _active_scheduled_delays() == []
            assert api.subscription_calls == []
        finally:
            entry.runtime_data.resources.close()

    asyncio.run(run())


def test_unsupported_bridge_does_not_retry_on_healthy_renewals(monkeypatch):
    async def run():
        _, entry, api, worker = setup(monkeypatch)
        api.async_display_bridge_status.side_effect = C300XAgentApiUnsupportedError("unsupported")
        try:
            await worker._register()
            await worker._register()
            api.async_display_bridge_status.assert_awaited_once()
            assert not entry.runtime_data.resources.display_bridge_registration_pending
        finally:
            entry.runtime_data.resources.close()

    asyncio.run(run())


def test_late_startup_failure_retains_retry_after_concurrent_success(monkeypatch):
    async def run():
        hass, entry, api, worker = setup(monkeypatch)
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def status():
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
                raise C300XAgentApiConnectionError("late startup failure")
            return {"configured": False}

        api.async_display_bridge_status.side_effect = status
        startup = asyncio.create_task(runtime_manager._async_configure_display_bridge(hass, entry, api))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await worker._register()
            assert not entry.runtime_data.resources.display_bridge_registration_pending
            release.set()
            await asyncio.wait_for(startup, 1)
            assert entry.runtime_data.resources.display_bridge_registration_pending
            await worker._register()
            assert not entry.runtime_data.resources.display_bridge_registration_pending
        finally:
            release.set()
            startup.cancel()
            await asyncio.gather(startup, return_exceptions=True)
            entry.runtime_data.resources.close()

    asyncio.run(run())


@pytest.mark.parametrize("replace", [False, True])
def test_unload_during_bridge_status_cannot_register_or_rearm(monkeypatch, replace):
    async def run():
        _, entry, api, worker = setup(monkeypatch)
        entered = asyncio.Event()

        async def status():
            entered.set()
            with suppress(asyncio.CancelledError):
                await asyncio.Future()
            return {"configured": False}

        api.async_display_bridge_status.side_effect = status
        old = entry.runtime_data
        task = asyncio.create_task(worker._register())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            old.resources.close()
            if replace:
                entry.runtime_data = BticinoC300XRuntimeData(
                    api=Api(), capabilities={}, event_state=C300XEventState(),
                    connection_state=C300XConnectionState(), agent_info={}, loaded_platforms=(),
                )
            with pytest.raises(asyncio.CancelledError):
                await task
            api.async_configure_display_bridge.assert_not_called()
            api.async_notify_display_bridge_event.assert_not_called()
            assert not old.resources.display_bridge_registration_pending
            assert old.diagnostics.display_bridge_diagnostics.last_error is None
            assert _active_scheduled_delays() == []
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            old.resources.close()

    asyncio.run(run())
