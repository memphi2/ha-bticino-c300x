"""Concurrent registry refreshes must not restore an obsolete subscription."""

import asyncio

import pytest
from test_events import (
    _active_scheduled_calls,
    _drain_hass_tasks,
    _FakeApi,
    _FakeConnectionState,
    _FakeEntry,
    _FakeHass,
    event_ha_boundary,  # noqa: F401
    events_module,
)

from custom_components.bticino_c300x.data import C300XConnectionState


@pytest.mark.parametrize("refreshes", [1, 3])
def test_registry_refresh_during_registration_keeps_newest_event_selection(monkeypatch, refreshes):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        selected = ["doorbell.pressed"]

        class Api(_FakeApi):
            async def async_list_event_subscriptions(self):
                self.list_calls += 1
                if self.list_calls == 1:
                    entered.set()
                    await release.wait()
                return {"subscriptions": []}

        api = Api([{"subscription": {"id": "sub"}}] * (refreshes + 1))
        hass = _FakeHass()
        monkeypatch.setattr(
            events_module, "_active_events_for_capabilities", lambda *_: list(selected),
        )
        unregister = await events_module.async_start_agent_event_registration(
            hass, _FakeEntry(), api, {}, _FakeConnectionState(),
        )
        refresh = None
        try:
            await asyncio.wait_for(entered.wait(), 1)
            for _ in range(refreshes):
                hass.bus.fire("entity_registry_updated", {"entity_id": "switch.ringer_mute"})
                registry_timer = _active_scheduled_calls(1)[0]
                refresh = asyncio.create_task(registry_timer.callback())
                await asyncio.wait_for(refresh, 1)
            selected.append("ringer.muted")
            release.set()
            await asyncio.wait_for(refresh, 1)
            await asyncio.wait_for(_drain_hass_tasks(hass), 1)
            assert api.subscription_calls[-1][2] == selected
            assert api.list_calls == len(api.subscription_calls) == 2
            assert len(_active_scheduled_calls(300)) == 1
        finally:
            release.set()
            unregister()
            if refresh is not None:
                await asyncio.gather(refresh, return_exceptions=True)
            await _drain_hass_tasks(hass)
            assert not _active_scheduled_calls(300)

    asyncio.run(run())


@pytest.mark.parametrize("failure_attempt", [1, 2])
def test_coalesced_registration_failure_retains_one_retry(monkeypatch, failure_attempt):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        selected = ["doorbell.pressed"]

        class Api(_FakeApi):
            async def async_list_event_subscriptions(self):
                self.list_calls += 1
                attempt = self.list_calls
                if attempt == 1:
                    entered.set()
                    await release.wait()
                if attempt == failure_attempt:
                    raise RuntimeError("agent temporarily unavailable")
                return {"subscriptions": []}

        api = Api([{"subscription": {"id": "sub"}}] * 2)
        hass = _FakeHass()
        state = C300XConnectionState()
        monkeypatch.setattr(
            events_module, "_active_events_for_capabilities", lambda *_: list(selected),
        )
        unregister = await events_module.async_start_agent_event_registration(
            hass, _FakeEntry(), api, {}, state,
        )
        try:
            await asyncio.wait_for(entered.wait(), 1)
            selected.append("ringer.muted")
            hass.bus.fire("entity_registry_updated", {"entity_id": "switch.ringer_mute"})
            await _active_scheduled_calls(1)[0].callback()
            release.set()
            await asyncio.wait_for(_drain_hass_tasks(hass), 1)
            assert api.list_calls == 2
            if failure_attempt == 2:
                assert state.connection_state == "reconnecting"
                assert state.event_subscription_last_error == "RuntimeError: agent temporarily unavailable"
                assert len(_active_scheduled_calls(30)) == 1
                assert not _active_scheduled_calls(300)
                await _active_scheduled_calls(30)[0].callback()
            assert state.connection_state == "connected"
            assert state.event_subscription_last_error is None
            assert api.subscription_calls[-1][2] == selected
            assert len(_active_scheduled_calls(300)) == 1
            assert not _active_scheduled_calls(30)
        finally:
            release.set()
            unregister()
            await _drain_hass_tasks(hass)
            assert not _active_scheduled_calls(300)
            assert not _active_scheduled_calls(30)

    asyncio.run(run())


@pytest.mark.parametrize("blocked_attempt", [1, 2])
def test_unload_cancels_registration_and_its_coalesced_refresh(monkeypatch, blocked_attempt):
    async def run():
        entered = [asyncio.Event(), asyncio.Event()]
        release_first = asyncio.Event()

        class Api(_FakeApi):
            async def async_list_event_subscriptions(self):
                self.list_calls += 1
                attempt = self.list_calls
                entered[attempt - 1].set()
                if attempt == 1:
                    await release_first.wait()
                else:
                    await asyncio.Future()
                return {"subscriptions": []}

        api = Api([{"subscription": {"id": "sub"}}])
        hass = _FakeHass()
        monkeypatch.setattr(
            events_module, "_active_events_for_capabilities", lambda *_: ["doorbell.pressed"],
        )
        unregister = await events_module.async_start_agent_event_registration(
            hass, _FakeEntry(), api, {}, _FakeConnectionState(),
        )
        try:
            await asyncio.wait_for(entered[0].wait(), 1)
            hass.bus.fire("entity_registry_updated", {"entity_id": "switch.ringer_mute"})
            await _active_scheduled_calls(1)[0].callback()
            if blocked_attempt == 2:
                release_first.set()
                await asyncio.wait_for(entered[1].wait(), 1)
                hass.bus.fire("entity_registry_updated", {"entity_id": "switch.ringer_mute"})
                await _active_scheduled_calls(1)[0].callback()
            unregister()
            await asyncio.wait_for(_drain_hass_tasks(hass), 1)
            assert all(task.cancelled() for task in hass.async_tasks)
            assert api.list_calls == blocked_attempt
            assert len(api.subscription_calls) == blocked_attempt - 1
            assert not _active_scheduled_calls(300)
            assert not _active_scheduled_calls(30)
            assert not _active_scheduled_calls(1)
        finally:
            release_first.set()
            unregister()
            await _drain_hass_tasks(hass)

    asyncio.run(run())
