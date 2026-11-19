"""Auth rejection never enters the offline startup/recovery path."""

import asyncio
from contextlib import suppress
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.bticino_c300x import runtime_manager
from custom_components.bticino_c300x.api_errors import (
    C300XAgentApiAuthError,
    C300XAgentApiConnectionError,
)
from custom_components.bticino_c300x.const import DOMAIN
from custom_components.bticino_c300x.data import C300XConnectionState
from custom_components.bticino_c300x.runtime_auth import async_request_reauth


def test_startup_auth_failure_is_not_offline(monkeypatch, caplog):
    manager = runtime_manager.C300XRuntimeManager(SimpleNamespace(), SimpleNamespace())
    manager.api = SimpleNamespace(async_validate_setup=AsyncMock(side_effect=C300XAgentApiAuthError()))
    recovery = Mock()
    monkeypatch.setattr(runtime_manager, "_async_start_setup_recovery", recovery)
    with pytest.raises(ConfigEntryAuthFailed):
        asyncio.run(manager.async_validate_agent())
    recovery.assert_not_called()
    assert "offline" not in caplog.text
    assert manager.unregister_event_registration is None


def test_offline_startup_still_builds_unavailable_runtime(monkeypatch):
    manager = runtime_manager.C300XRuntimeManager(SimpleNamespace(), SimpleNamespace())
    manager.api = SimpleNamespace(async_validate_setup=AsyncMock(side_effect=C300XAgentApiConnectionError("offline")))
    cancel = Mock()
    recovery = Mock(return_value=cancel)
    monkeypatch.setattr(runtime_manager, "_async_start_setup_recovery", recovery)
    asyncio.run(manager.async_validate_agent())
    assert manager.setup_data["offline_error"]
    assert manager.capabilities == {}
    assert not manager.connection_state.available
    assert manager.unregister_event_registration is cancel


@pytest.mark.parametrize("maintenance", [False, True])
def test_runtime_reauth_cancels_grace_and_cannot_be_cleared_by_push(maintenance):
    state = C300XConnectionState()
    cancel = Mock()
    state.expire_unavailable = cancel
    entry = SimpleNamespace(async_start_reauth=Mock())
    hass = SimpleNamespace()
    async_request_reauth(hass, entry, state, C300XAgentApiAuthError(maintenance=maintenance))
    entry.async_start_reauth.assert_called_once_with(hass)
    cancel.assert_called_once()
    assert state.expire_unavailable is None
    state.mark_connected()
    state.mark_reconnecting("other_error", 30, "later")
    assert not state.available
    assert state.authentication_failed
    assert state.last_reconnect_reason == ("maintenance_auth" if maintenance else "agent_auth")
    assert state.next_reconnect_delay_seconds is None

    async_request_reauth(hass, entry, state, C300XAgentApiAuthError(maintenance=not maintenance))
    assert state.last_reconnect_reason == ("agent_auth" if maintenance else "maintenance_auth")


@pytest.mark.parametrize("cancelled", [False, True])
def test_offline_recovery_switches_to_reauth_unless_unloaded(monkeypatch, cancelled):
    from homeassistant.helpers import dispatcher, event

    timers = []
    monkeypatch.setattr(event, "async_call_later", lambda _hass, _delay, cb: timers.append(cb) or Mock())
    monkeypatch.setattr(dispatcher, "async_dispatcher_send", Mock())
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_reload=AsyncMock()))
    entry = SimpleNamespace(entry_id="entry", async_start_reauth=Mock())
    state = C300XConnectionState()

    async def exercise():
        started = asyncio.Event()

        async def validate():
            started.set()
            if cancelled:
                with suppress(asyncio.CancelledError):
                    await asyncio.Future()
            raise C300XAgentApiAuthError()

        cancel = runtime_manager._async_start_setup_recovery(
            hass, entry, SimpleNamespace(async_validate_setup=validate), state,
        )
        task = asyncio.create_task(timers[0]())
        await started.wait()
        if cancelled:
            cancel()
        await task
        await timers[0]()
        cancel()

    asyncio.run(exercise())
    assert len(timers) == 1
    assert entry.async_start_reauth.call_count == (0 if cancelled else 1)
    assert state.authentication_failed is not cancelled
    hass.config_entries.async_reload.assert_not_called()


@pytest.mark.parametrize("existing_flow", [None, "reauth", "reconfigure"])
def test_installed_ha_deduplicates_entry_bound_reauth(monkeypatch, existing_flow):
    """Use HA's real ConfigEntry lock and context construction, without starting HA."""
    from homeassistant.helpers import issue_registry

    monkeypatch.setattr(issue_registry, "async_create_issue", Mock())

    async def exercise():
        entry = ConfigEntry(
            version=1, minor_version=3, domain=DOMAIN, title="Door", source="user",
            unique_id="device", data={"agent_token": "old"}, options={},
            discovery_keys=MappingProxyType({}), subentries_data=None,
        )
        active = [] if existing_flow is None else [{"context": {"source": existing_flow}}]
        tasks = []
        calls = []

        async def init(domain, *, context, data):
            calls.append((domain, context, data))
            active.append({"context": context})
            return {"type": "form", "flow_id": "reauth-flow"}

        def create_task(coro, *args, **kwargs):
            task = asyncio.create_task(coro)
            tasks.append(task)
            return task

        hass = SimpleNamespace(
            async_create_task=create_task,
            config_entries=SimpleNamespace(flow=SimpleNamespace(
                async_progress_by_handler=lambda *args, **kwargs: active,
                async_init=init,
            )),
        )
        entry.async_start_reauth(hass)
        entry.async_start_reauth(hass)
        await asyncio.gather(*tasks)
        assert len(calls) == (1 if existing_flow is None else 0)
        if calls:
            assert calls[0][1]["entry_id"] == entry.entry_id
            assert calls[0][1]["source"] == "reauth"
            assert calls[0][1]["unique_id"] == "device"

    asyncio.run(exercise())
