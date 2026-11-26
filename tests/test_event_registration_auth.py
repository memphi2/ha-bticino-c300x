"""Registration auth, transition-only logs and teardown regressions."""

import asyncio
import logging
from contextlib import suppress
from types import SimpleNamespace
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

from custom_components.bticino_c300x import events
from custom_components.bticino_c300x.api_errors import C300XAgentApiAuthError
from custom_components.bticino_c300x.data import (
    C300XConnectionState,
    C300XRuntimeResources,
)


def registration(api, state=None):
    hass, entry = _FakeHass(), _FakeEntry()
    entry.async_start_reauth = Mock()
    state = state or C300XConnectionState()
    entry.runtime_data = SimpleNamespace(
        api=api, capabilities={}, connection_state=state,
        resources=C300XRuntimeResources(),
    )
    return events._AgentEventRegistration(hass, entry, api, {}, state, None)


@pytest.mark.parametrize("maintenance", [False, True])
def test_rejected_registration_requests_reauth_without_retry(maintenance, caplog):
    api = _FakeApi([], subscriptions=C300XAgentApiAuthError(maintenance=maintenance))
    api.async_validate_maintenance_auth = AsyncMock(side_effect=C300XAgentApiAuthError(maintenance=True))
    worker = registration(api)
    asyncio.run(worker._register())
    assert api.list_calls == 1
    worker._entry.async_start_reauth.assert_called_once_with(worker._hass)
    assert worker._connection_state.authentication_failed
    assert not worker._connection_state.available
    assert _active_scheduled_delays() == []
    asyncio.run(worker._register())
    assert api.list_calls == 1
    assert "event-token" not in caplog.text


def test_disabled_maintenance_does_not_start_reauth():
    api = _FakeApi([], subscriptions=C300XAgentApiAuthError(maintenance=True))
    api.async_validate_maintenance_auth = AsyncMock(return_value={"maintenance_enabled": False})
    worker = registration(api)
    asyncio.run(worker._register())
    worker._entry.async_start_reauth.assert_not_called()
    assert not worker._connection_state.authentication_failed
    assert "not permitted" in worker._connection_state.event_subscription_last_error
    assert 30 in _active_scheduled_delays()
    worker.unregister()


def test_warning_and_recovery_once_per_outage_even_across_rediscovery(caplog):
    caplog.set_level(logging.INFO, logger=events.__name__)
    api = _FakeApi([{"subscription": {"id": "sub"}}] * 3, subscriptions=RuntimeError("offline"))
    worker = registration(api)

    async def exercise():
        await worker._register()
        worker._connection_state.mark_connected()  # Inbound webhook is not registration recovery.
        await worker._register()
        worker._entry.runtime_data.resources.unregister_event_registration = worker.unregister
        assert events.async_request_agent_event_registration(worker._hass, worker._entry)
        await _drain_hass_tasks(worker._hass)
        replacement_cancel = worker._entry.runtime_data.resources.unregister_event_registration
        replacement = replacement_cancel.__self__
        api.subscriptions = []
        await replacement._register()
        await replacement._register()
        api.subscriptions = RuntimeError("another outage")
        await replacement._register()
        api.subscriptions = []
        await replacement._register()
        replacement_cancel()

    asyncio.run(exercise())
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    recoveries = [r for r in caplog.records if r.getMessage() == "C300X event registration recovered"]
    assert len(warnings) == 2
    assert len(recoveries) == 2
    assert _active_scheduled_delays() == []


def test_initial_success_and_optional_diagnostics_failure_are_not_transitions(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=events.__name__)
    monkeypatch.setattr(events, "async_refresh_agent_diagnostics", AsyncMock(side_effect=RuntimeError("optional")))
    worker = registration(_FakeApi([{"subscription": {"id": "sub"}}]))
    asyncio.run(worker._register())
    assert worker._connection_state.available
    assert worker._connection_state.event_subscription_last_error is None
    assert not caplog.records
    worker.unregister()


@pytest.mark.parametrize("result", ["auth", "offline", "success"])
def test_unload_during_registration_has_no_late_state_logs_or_reauth(result, caplog):
    async def exercise():
        started = asyncio.Event()

        class Api(_FakeApi):
            async def async_list_event_subscriptions(self):
                started.set()
                with suppress(asyncio.CancelledError):
                    await asyncio.Future()
                if result == "auth":
                    raise C300XAgentApiAuthError()
                if result == "offline":
                    raise RuntimeError("offline")
                return {"subscriptions": []}

        worker = registration(Api([]))
        worker.start()
        await started.wait()
        worker.unregister()
        await _drain_hass_tasks(worker._hass)
        worker._entry.async_start_reauth.assert_not_called()
        assert worker._connection_state.event_subscription_last_error is None
        assert worker._api.subscription_calls == []
        assert _active_scheduled_delays() == []
        assert not caplog.records

    asyncio.run(exercise())


def test_no_events_cleanup_does_not_delete_after_unload(monkeypatch):
    monkeypatch.setattr(events, "_active_events_for_capabilities", lambda *_: [])

    async def exercise():
        started = asyncio.Event()

        class Api(_FakeApi):
            async def async_list_event_subscriptions(self):
                started.set()
                with suppress(asyncio.CancelledError):
                    await asyncio.Future()
                return {"subscriptions": [{
                    "id": "old", "callback_url": "http://localhost:8123/webhook/event-hook",
                }]}

        worker = registration(Api([]))
        worker.start()
        await started.wait()
        worker.unregister()
        await _drain_hass_tasks(worker._hass)
        assert worker._api.delete_calls == []

    asyncio.run(exercise())


def test_every_registration_pass_reads_units_and_calls_again(monkeypatch):
    # The agent does not resend a lost callback; a pass (setup, reconnect,
    # renewal) replaces the call mirror with the agent's list.
    from custom_components.bticino_c300x import call_sync

    resync = AsyncMock()
    monkeypatch.setattr(call_sync, "async_resync", resync)
    worker = registration(_FakeApi([{"subscription": {"id": "sub"}}] * 2))
    asyncio.run(worker._register())
    asyncio.run(worker._register())
    assert resync.await_count == 2
    worker.unregister()
