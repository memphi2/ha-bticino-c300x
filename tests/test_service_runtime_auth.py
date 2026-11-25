"""Service auth recovery probes only, never retries a device command."""

import asyncio
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.bticino_c300x import events
from custom_components.bticino_c300x.api_errors import (
    C300XAgentApiAuthError,
    C300XAgentApiConnectionError,
    C300XAgentApiResponseError,
)
from custom_components.bticino_c300x.const import SIGNAL_CONNECTION_STATE_CHANGED
from custom_components.bticino_c300x.data import (
    BticinoC300XRuntimeData,
    C300XConnectionState,
    C300XEventState,
)
from custom_components.bticino_c300x.use_cases import common
from custom_components.bticino_c300x.use_cases.device_actions import (
    DeviceActionsUseCase,
)


def setup(monkeypatch):
    api = SimpleNamespace(
        async_reload_gui=AsyncMock(), async_reboot=AsyncMock(),
        async_unlock_outdoor_unit=AsyncMock(return_value={"ok": True}),
        async_validate_maintenance_auth=AsyncMock(return_value={"maintenance_enabled": False}),
    )
    runtime = BticinoC300XRuntimeData(
        api=api, capabilities={"maintenance": {"supported": True, "gui_reload": True, "reboot": True}},
        event_state=C300XEventState(), connection_state=C300XConnectionState(),
        agent_info={}, loaded_platforms=(),
    )
    entry = SimpleNamespace(
        entry_id="entry", runtime_data=runtime, data={"maintenance_token": "saved"},
        options={}, async_start_reauth=Mock(), state=ConfigEntryState.LOADED,
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_entries=lambda _: [entry], async_loaded_entries=lambda _: [entry],
        ),
        bus=SimpleNamespace(async_fire=Mock()),
    )
    get_hass = Mock(return_value=hass)
    send = Mock()
    monkeypatch.setattr(common, "async_get_hass", get_hass)
    monkeypatch.setattr(common, "async_dispatcher_send", send)
    return hass, entry, api, get_hass, send


def _operation(hass, entry, operation):
    """The door the display and the ring analysis open."""

    return DeviceActionsUseCase(hass, entry).unlock()


@pytest.mark.parametrize("operation", ["unlock_outdoor_unit"])
@pytest.mark.parametrize("rejection", ["bearer", "maintenance", "policy", "probe_offline"])
def test_service_rejection_requests_reauth_only_for_confirmed_credentials(monkeypatch, operation, rejection):
    hass, entry, api, get_hass, send = setup(monkeypatch)
    command = getattr(api, f"async_{operation}")
    command.side_effect = C300XAgentApiAuthError(maintenance=rejection != "bearer")
    if rejection == "maintenance":
        api.async_validate_maintenance_auth.side_effect = C300XAgentApiAuthError(maintenance=True)
    elif rejection == "probe_offline":
        api.async_validate_maintenance_auth.side_effect = C300XAgentApiConnectionError("offline")
    cancel_grace = entry.runtime_data.connection_state.expire_unavailable = Mock()
    unregister = entry.runtime_data.resources.unregister_event_registration = Mock()
    with pytest.raises(HomeAssistantError) as error:
        asyncio.run(_operation(hass, entry, operation))
    assert error.value.translation_key == "agent_command_failed"
    # A rejected key or an unreachable agent is not invalid input.
    assert not isinstance(error.value, ServiceValidationError)
    command.assert_awaited_once()
    assert api.async_validate_maintenance_auth.await_count == (0 if rejection == "bearer" else 1)
    state = entry.runtime_data.connection_state
    if rejection == "maintenance":
        # Only maintenance is locked: the access key still works, the entry stays online.
        assert isinstance(error.value.__cause__, C300XAgentApiAuthError)
        entry.async_start_reauth.assert_called_once_with(hass, data={"maintenance_key_rejected": True})
        send.assert_not_called()
        unregister.assert_not_called()
        assert entry.runtime_data.resources.unregister_event_registration is unregister
        cancel_grace.assert_not_called()
        assert state.available and not state.authentication_failed
    elif rejection == "bearer":
        assert isinstance(error.value.__cause__, C300XAgentApiAuthError)
        entry.async_start_reauth.assert_called_once_with(hass)
        send.assert_called_once_with(hass, SIGNAL_CONNECTION_STATE_CHANGED, entry.entry_id)
        get_hass.assert_called_once()
        unregister.assert_called_once()
        assert entry.runtime_data.resources.unregister_event_registration is None
        cancel_grace.assert_called_once()
        assert state.expire_unavailable is None
        assert state.authentication_failed and not state.available
        assert state.last_reconnect_reason == "agent_auth"
        assert state.next_reconnect_delay_seconds is None
    else:
        assert isinstance(error.value.__cause__, C300XAgentApiResponseError)
        entry.async_start_reauth.assert_not_called()
        send.assert_not_called()
        get_hass.assert_not_called()
        unregister.assert_not_called()
        assert entry.runtime_data.resources.unregister_event_registration is unregister
        cancel_grace.assert_not_called()
        assert state.available and not state.authentication_failed


@pytest.mark.parametrize("result", ["success", "offline", "response"])
def test_non_auth_service_results_do_not_probe_or_start_reauth(monkeypatch, result):
    hass, entry, api, get_hass, send = setup(monkeypatch)
    if result != "success":
        api.async_unlock_outdoor_unit.side_effect = (
            C300XAgentApiConnectionError("offline") if result == "offline"
            else C300XAgentApiResponseError("busy")
        )
    if result == "success":
        assert asyncio.run(DeviceActionsUseCase(hass, entry).unlock()) is None
    else:
        with pytest.raises(HomeAssistantError) as error:
            asyncio.run(DeviceActionsUseCase(hass, entry).unlock())
        assert not isinstance(error.value, ServiceValidationError)
    api.async_unlock_outdoor_unit.assert_awaited_once()
    api.async_validate_maintenance_auth.assert_not_called()
    entry.async_start_reauth.assert_not_called()
    get_hass.assert_not_called()
    send.assert_not_called()


@pytest.mark.parametrize("stage", ["command", "probe"])
@pytest.mark.parametrize("transition", ["closed", "replaced", "removed", "cancelled"])
def test_service_auth_recovery_cannot_cross_runtime_boundary(monkeypatch, stage, transition):
    async def run():
        hass, entry, api, get_hass, send = setup(monkeypatch)
        old = entry.runtime_data
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked(*_args, **_kwargs):
            entered.set()
            await release.wait()
            raise C300XAgentApiAuthError(maintenance=True)

        api.async_unlock_outdoor_unit.side_effect = C300XAgentApiAuthError(maintenance=True)
        api.async_validate_maintenance_auth.side_effect = C300XAgentApiAuthError(maintenance=True)
        target = api.async_unlock_outdoor_unit if stage == "command" else api.async_validate_maintenance_auth
        target.side_effect = blocked
        task = asyncio.create_task(DeviceActionsUseCase(hass, entry).unlock())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            if transition == "closed":
                old.resources.close()
            elif transition == "removed":
                del entry.runtime_data
            elif transition == "replaced":
                entry.runtime_data = BticinoC300XRuntimeData(
                    api=api, capabilities={}, event_state=C300XEventState(),
                    connection_state=C300XConnectionState(), agent_info={}, loaded_platforms=(),
                )
            else:
                task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError if transition == "cancelled" else ServiceValidationError):
                await asyncio.wait_for(task, 1)
            api.async_unlock_outdoor_unit.assert_awaited_once()
            assert api.async_validate_maintenance_auth.await_count == (1 if stage == "probe" else 0)
            entry.async_start_reauth.assert_not_called()
            get_hass.assert_not_called()
            send.assert_not_called()
            assert not old.connection_state.authentication_failed
            if transition == "replaced":
                assert not entry.runtime_data.connection_state.authentication_failed
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_confirmed_maintenance_rejection_leaves_event_registration_running(monkeypatch):
    async def run():
        hass, entry, api, _, _ = setup(monkeypatch)
        entry.data.update(event_webhook_id="events", event_webhook_token="secret")
        entered = asyncio.Event()

        async def list_subscriptions():
            entered.set()
            with suppress(asyncio.CancelledError):
                await asyncio.Future()
            return {"subscriptions": []}

        api.async_list_event_subscriptions = AsyncMock(side_effect=list_subscriptions)
        api.async_register_event_subscription = AsyncMock()
        api.async_unlock_outdoor_unit.side_effect = C300XAgentApiAuthError(maintenance=True)
        api.async_validate_maintenance_auth.side_effect = C300XAgentApiAuthError(maintenance=True)
        monkeypatch.setattr(events, "async_generate_agent_callback_url", AsyncMock(return_value="http://ha/events"))
        monkeypatch.setattr(events, "_active_events_for_capabilities", lambda *_: ["doorbell.pressed"])
        worker = events._AgentEventRegistration(hass, entry, api, {}, entry.runtime_data.connection_state, None)
        entry.runtime_data.resources.unregister_event_registration = worker.unregister
        renewal = asyncio.create_task(worker._register())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            with pytest.raises(HomeAssistantError):
                await DeviceActionsUseCase(hass, entry).unlock()
            assert not renewal.done()
            assert not entry.runtime_data.connection_state.authentication_failed
            assert entry.runtime_data.connection_state.available
            assert entry.runtime_data.resources.unregister_event_registration == worker.unregister
            entry.async_start_reauth.assert_called_once_with(hass, data={"maintenance_key_rejected": True})
            api.async_unlock_outdoor_unit.assert_awaited_once()
            api.async_validate_maintenance_auth.assert_awaited_once()
            api.async_register_event_subscription.assert_not_called()
        finally:
            worker.unregister()
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)

    asyncio.run(run())
