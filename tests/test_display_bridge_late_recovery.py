"""Startup bridge failures wake an idle registration worker, not an idle poll."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from test_display_bridge_recovery import setup
from test_events import (
    _active_scheduled_calls,
    _active_scheduled_delays,
    _drain_hass_tasks,
    event_ha_boundary,  # noqa: F401
    fake_dispatcher,
)

from custom_components.bticino_c300x import (
    agent_diagnostics,
    events,
    repair_issues,
    runtime_manager,
)
from custom_components.bticino_c300x.api_errors import (
    C300XAgentApiConnectionError,
    C300XAgentApiUnsupportedError,
)

_REAL_ACTIVE_EVENTS = events._active_events_for_capabilities


def setup_idle(monkeypatch):
    hass, entry, api, worker = setup(monkeypatch, no_events=True)
    capabilities = {
        "doorbell_events": {"supported": True},
        "ringer": {"supported": True},
        "system_metrics": {"supported": False},
        "diagnostics": {"supported": True},
    }
    entry.runtime_data.capabilities = worker._capabilities = capabilities
    hass.entity_registry = SimpleNamespace(
        async_get_entity_id=lambda *_: "disabled.entity",
        async_get=lambda _: SimpleNamespace(disabled_by="user"),
    )
    api.async_diagnostics = AsyncMock(return_value={})
    monkeypatch.setattr(agent_diagnostics, "async_dispatcher_send", Mock())
    monkeypatch.setattr(repair_issues, "async_sync_entry_repair_issues", Mock())
    # Disabled entities no longer silence events: only the diagnostics stay tied to their sensor.
    active = _REAL_ACTIVE_EVENTS(hass, entry, capabilities)
    assert "doorbell.pressed" in active and "agent.diagnostics_changed" not in active
    # An idle worker is one with nothing to subscribe.
    monkeypatch.setattr(events, "_active_events_for_capabilities", lambda *_: [])
    return hass, entry, api, worker


@pytest.mark.parametrize("failure", ["status", "configure"])
def test_late_startup_failure_rearms_idle_worker_once(monkeypatch, failure):
    async def run():
        hass, entry, api, worker = setup_idle(monkeypatch)
        runtime = entry.runtime_data
        worker.start()
        try:
            await _drain_hass_tasks(hass)
            assert not worker._active_tasks
            assert _active_scheduled_delays() == []
            failing = api.async_display_bridge_status if failure == "status" else api.async_configure_display_bridge
            failing.side_effect = C300XAgentApiConnectionError("late startup failure")
            await runtime_manager._async_configure_display_bridge(hass, entry, api)
            assert runtime.resources.display_bridge_registration_pending
            assert _active_scheduled_delays() == [300]
            await runtime_manager._async_configure_display_bridge(hass, entry, api)
            assert _active_scheduled_delays() == [300]
            failing.side_effect = None
            await _active_scheduled_calls(300)[0].callback(None)
            assert not runtime.resources.display_bridge_registration_pending
            assert runtime.diagnostics.display_bridge_diagnostics.last_error is None
            assert _active_scheduled_delays() == []
            assert api.subscription_calls == []
            events.async_notify_runtime_registration_failed(hass, entry)
            assert _active_scheduled_delays() == []
        finally:
            runtime.resources.close()
        assert fake_dispatcher.listeners == []

    asyncio.run(run())


def test_late_failure_during_final_diagnostics_also_rearms(monkeypatch):
    async def run():
        hass, entry, api, worker = setup_idle(monkeypatch)
        entered, release = asyncio.Event(), asyncio.Event()

        async def diagnostics():
            entered.set()
            await release.wait()
            return {}

        api.async_diagnostics.side_effect = diagnostics
        worker.start()
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert worker._active_tasks
            assert _active_scheduled_delays() == []
            api.async_configure_display_bridge.side_effect = C300XAgentApiConnectionError("late failure")
            await runtime_manager._async_configure_display_bridge(hass, entry, api)
            release.set()
            await _drain_hass_tasks(hass)
            assert _active_scheduled_delays() == [300]
        finally:
            release.set()
            entry.runtime_data.resources.close()
        assert _active_scheduled_delays() == []

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["list", "create"])
def test_startup_failure_overlapping_subscription_owns_one_renewal(monkeypatch, stage):
    async def run():
        hass, entry, api, worker = setup(monkeypatch)
        entered, release = asyncio.Event(), asyncio.Event()
        method = (
            "async_list_event_subscriptions"
            if stage == "list" else "async_register_event_subscription"
        )
        original = getattr(api, method)

        async def blocked_subscription(**kwargs):
            entered.set()
            await release.wait()
            return await original(**kwargs)

        monkeypatch.setattr(api, method, blocked_subscription)
        worker.start()
        try:
            await asyncio.wait_for(entered.wait(), 1)
            api.async_configure_display_bridge.side_effect = C300XAgentApiConnectionError("overlapping startup failure")
            await runtime_manager._async_configure_display_bridge(hass, entry, api)
            assert _active_scheduled_delays() == [300]
            renewal = _active_scheduled_calls(300)[0]
            release.set()
            await _drain_hass_tasks(hass)
            assert _active_scheduled_calls(300) == [renewal]
            api.async_configure_display_bridge.side_effect = None
            await renewal.callback(None)
            assert not entry.runtime_data.resources.display_bridge_registration_pending
            assert _active_scheduled_delays() == [300]
        finally:
            release.set()
            entry.runtime_data.resources.close()
            await asyncio.gather(*hass.async_tasks, return_exceptions=True)
        assert _active_scheduled_delays() == []
        assert fake_dispatcher.listeners == []

    asyncio.run(run())


@pytest.mark.parametrize("unsupported", [False, True])
def test_healthy_or_unsupported_startup_has_no_idle_poll(monkeypatch, unsupported):
    async def run():
        hass, entry, api, worker = setup_idle(monkeypatch)
        worker.start()
        try:
            await _drain_hass_tasks(hass)
            if unsupported:
                api.async_display_bridge_status.side_effect = C300XAgentApiUnsupportedError("unsupported")
            await runtime_manager._async_configure_display_bridge(hass, entry, api)
            assert not entry.runtime_data.resources.display_bridge_registration_pending
            assert _active_scheduled_delays() == []
        finally:
            entry.runtime_data.resources.close()

    asyncio.run(run())


def test_late_bridge_failure_does_not_rearm_rejected_credentials(monkeypatch):
    async def run():
        hass, entry, _, worker = setup_idle(monkeypatch)
        worker.start()
        try:
            await _drain_hass_tasks(hass)
            worker._auth_failed = True
            entry.runtime_data.resources.display_bridge_registration_pending = True
            events.async_notify_runtime_registration_failed(hass, entry)
            worker._schedule_renewal()
            assert _active_scheduled_delays() == []
        finally:
            entry.runtime_data.resources.close()

    asyncio.run(run())


@pytest.mark.parametrize("close_before_delivery", [False, True])
def test_real_dispatcher_is_entry_scoped_and_detached_on_unload(monkeypatch, tmp_path, close_before_delivery):
    async def run():
        _, entry, api, worker = setup_idle(monkeypatch)
        hass = worker._hass = HomeAssistant(str(tmp_path))
        monkeypatch.setattr(events, "async_dispatcher_connect", async_dispatcher_connect)
        monkeypatch.setattr(events, "async_dispatcher_send", async_dispatcher_send)
        monkeypatch.setattr(worker, "_register", AsyncMock())
        worker.start()
        try:
            await hass.async_block_till_done()
            entry.runtime_data.resources.display_bridge_registration_pending = True
            events.async_notify_runtime_registration_failed(hass, SimpleNamespace(entry_id="other"))
            await hass.async_block_till_done()
            assert _active_scheduled_delays() == []
            events.async_notify_runtime_registration_failed(hass, entry)
            if close_before_delivery:
                entry.runtime_data.resources.close()
            await hass.async_block_till_done()
            assert _active_scheduled_delays() == ([] if close_before_delivery else [300])
            entry.runtime_data.resources.close()
            assert worker._runtime_failure_cancel is None
            events.async_notify_runtime_registration_failed(hass, entry)
            await hass.async_block_till_done()
            assert _active_scheduled_delays() == []
        finally:
            worker.unregister()
            await hass.async_stop()

    asyncio.run(run())
