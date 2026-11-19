"""Home Assistant touch-tone state, API validation and push handling."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from test_switch import _FakeEntry

from custom_components.bticino_c300x._api_display import (
    _ApiDisplayMixin,
    _touch_tone_status,
)
from custom_components.bticino_c300x.api_errors import (
    C300XAgentApiError,
    C300XAgentApiResponseError,
)
from custom_components.bticino_c300x.capabilities import events_for_capabilities
from custom_components.bticino_c300x.const import (
    EVENT_AGENT_EVENT_RECEIVED,
    SIGNAL_SETTING_STATE,
)
from custom_components.bticino_c300x.switch import async_setup_entry
from custom_components.bticino_c300x.switch_display import C300XTouchToneSwitch

pytestmark = pytest.mark.usefixtures("entity_ha_boundary")


@pytest.mark.parametrize("bad", [None, [], {}, {"ok": False}, {"ok": True},
                                  {"ok": True, "available": 1},
                                  {"ok": True, "available": True, "enabled": "true"}])
def test_api_rejects_unconfirmed_or_malformed_state(bad):
    with pytest.raises(C300XAgentApiResponseError):
        _touch_tone_status(bad)


def test_api_validates_the_post_confirmation():
    api = object.__new__(_ApiDisplayMixin)
    api._request_json = AsyncMock(return_value={"ok": True, "available": True, "enabled": False})
    assert asyncio.run(api.async_touch_tone_status())["enabled"] is False
    assert asyncio.run(api.async_set_touch_tone(False))["enabled"] is False
    api._request_json.assert_awaited_with("POST", "/api/v1/display/touch-tone", json_data={"enabled": False}, request_timeout=8.0)
    for data in ({"ok": True, "available": True, "enabled": True},
                 {"ok": True, "available": False, "enabled": None}):
        api._request_json.return_value = data
        with pytest.raises(C300XAgentApiResponseError):
            asyncio.run(api.async_set_touch_tone(False))


def make_switch():
    entry = _FakeEntry()
    entry.runtime_data.api.async_touch_tone_status = AsyncMock(
        return_value={"ok": True, "available": True, "enabled": True}
    )
    entry.runtime_data.api.async_set_touch_tone = AsyncMock(
        return_value={"ok": True, "available": True, "enabled": False}
    )
    return entry, C300XTouchToneSwitch(entry)


def test_config_switch_reads_and_waits_for_confirmation():
    entry, switch = make_switch()
    assert switch.entity_category is EntityCategory.CONFIG
    assert switch.should_poll is False
    assert not switch.available
    asyncio.run(switch.async_update())
    assert switch.available and switch.is_on
    asyncio.run(switch.async_turn_off())
    assert switch.is_on is False
    entry.runtime_data.api.async_set_touch_tone.return_value["enabled"] = True
    asyncio.run(switch.async_turn_on())
    assert switch.is_on is True
    entry.runtime_data.api.async_set_touch_tone.side_effect = C300XAgentApiError("timeout")
    with pytest.raises(HomeAssistantError, match="could not be confirmed"):
        asyncio.run(switch.async_turn_off())
    assert switch.is_on is True
    entry.runtime_data.api.async_touch_tone_status.side_effect = C300XAgentApiError("offline")
    asyncio.run(switch.async_update())
    assert not switch.available


def test_push_uses_confirmed_state_for_this_entry_only():
    _, switch = make_switch()
    asyncio.run(switch.async_update())
    def event(entry_id="entry-1", kind="display_touch_tone_changed", data=None):
        return SimpleNamespace(data={"entry_id": entry_id, "event_key": kind,
                                     "data": data if data is not None else {"enabled": False, "available": True}})
    switch._handle_event(event(entry_id="elsewhere"))
    switch._handle_event(event(kind="ringer_muted"))
    assert switch.is_on is True
    switch._handle_event(event())
    assert switch.is_on is False
    assert switch.available
    switch._handle_event(event(data={"enabled": None, "available": False}))
    assert switch.is_on is None and not switch.available
    switch._handle_event(event(data="invalid"))
    assert not switch.available


def test_setup_adds_switch_and_its_event_only_for_capable_agent():
    entry, _ = make_switch()
    entry.runtime_data.capabilities = {"touch_tone": {"supported": True}}
    entities = []
    asyncio.run(async_setup_entry(None, entry, entities.extend))
    assert any(isinstance(entity, C300XTouchToneSwitch) for entity in entities)
    assert "display.touch_tone_changed" in events_for_capabilities(entry.runtime_data.capabilities)
    assert "display.touch_tone_changed" not in events_for_capabilities({})


def test_legacy_first_change_is_applied_without_an_initial_read():
    entry, switch = make_switch()
    switch._handle_event(SimpleNamespace(data={
        "entry_id": entry.entry_id, "event_key": "display_touch_tone_changed",
        "data": {"enabled": False, "available": True},
    }))
    assert switch.available and switch.is_on is False
    entry.runtime_data.api.async_touch_tone_status.assert_not_awaited()
    entry.runtime_data.api.async_set_touch_tone.assert_not_awaited()


def test_snapshot_subscription_applies_payload_without_api_reads_or_writes(monkeypatch):
    import custom_components.bticino_c300x.switch_display as module

    listeners = {}
    def connect(hass, signal, handler):
        listeners[signal] = handler
        return lambda: listeners.pop(signal)
    monkeypatch.setattr(module, "async_dispatcher_connect", connect)
    entry, switch = make_switch()
    switch.hass = SimpleNamespace(bus=_EventBus())
    asyncio.run(switch.async_added_to_hass())
    entry.runtime_data.api.async_touch_tone_status.reset_mock()
    def handler(entry_id, data):
        listeners[SIGNAL_SETTING_STATE](entry_id, "display_touch_tone_changed", data)
    handler("elsewhere", {"enabled": False, "available": True})
    assert switch.available and switch.is_on is True
    for value, available in ((None, False), (False, True), (True, True)):
        handler(entry.entry_id, {"enabled": value, "available": available})
        assert switch.available is available and switch.is_on is value
    handler(entry.entry_id, "invalid")
    assert switch.available and switch.is_on is True
    entry.runtime_data.api.async_touch_tone_status.assert_not_awaited()
    entry.runtime_data.api.async_set_touch_tone.assert_not_awaited()
    switch._remove_callback()
    assert not listeners


class _EventBus:
    def __init__(self):
        self.listeners = []

    def async_listen(self, topic, handler):
        assert topic == EVENT_AGENT_EVENT_RECEIVED
        self.listeners.append(handler)
        return lambda: self.listeners.remove(handler)

    def push(self, entry, *, enabled, available=True):
        event = SimpleNamespace(data={
            "entry_id": entry.entry_id,
            "event_key": "display_touch_tone_changed",
            "data": {"enabled": enabled, "available": available},
        })
        for handler in tuple(self.listeners):
            handler(event)


def test_added_switch_recovers_push_lost_during_other_initial_reads():
    async def run():
        entry, _ = make_switch()
        entry.runtime_data.capabilities = {"touch_tone": True, "ringer": True}
        current = {"ok": True, "available": True, "enabled": True}
        api = entry.runtime_data.api
        api.async_touch_tone_status.side_effect = lambda: dict(current)
        entered, release = asyncio.Event(), asyncio.Event()

        async def ringer_status():
            entered.set()
            await release.wait()
            return {"muted": False}

        api.async_ringer_status = AsyncMock(side_effect=ringer_status)
        bus = _EventBus()
        hass = SimpleNamespace(bus=bus)
        entities = []
        setup = asyncio.create_task(async_setup_entry(hass, entry, entities.extend))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert not entities and not bus.listeners
            assert api.async_touch_tone_status.await_count == 1
            current["enabled"] = False
            bus.push(entry, enabled=False)
        finally:
            release.set()
            await setup
        switch = next(entity for entity in entities if isinstance(entity, C300XTouchToneSwitch))
        assert switch.is_on is True
        switch.hass = hass
        await switch.async_added_to_hass()
        assert switch.is_on is False and switch.available
        assert api.async_touch_tone_status.await_count == 2
        assert len(bus.listeners) == 1
        assert switch.should_poll is False

    asyncio.run(run())


@pytest.mark.parametrize("read_fails", [False, True])
@pytest.mark.parametrize("push_available", [False, True])
@pytest.mark.parametrize("snapshot", [False, True])
def test_push_during_added_resync_wins_over_delayed_read(read_fails, push_available, snapshot):
    async def run():
        entry, switch = make_switch()
        await switch.async_update()
        entered, release = asyncio.Event(), asyncio.Event()

        async def status():
            entered.set()
            await release.wait()
            if read_fails:
                raise C300XAgentApiError("offline")
            return {"ok": True, "available": True, "enabled": True}

        entry.runtime_data.api.async_touch_tone_status.side_effect = status
        bus = _EventBus()
        switch.hass = SimpleNamespace(bus=bus)
        added = asyncio.create_task(switch.async_added_to_hass())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            if snapshot:
                switch._handle_state(entry.entry_id, {
                    "enabled": False if push_available else None, "available": push_available,
                })
            else:
                bus.push(entry, enabled=False if push_available else None, available=push_available)
        finally:
            release.set()
            await added
        assert switch.is_on is (False if push_available else None)
        assert switch.available is push_available

    asyncio.run(run())


def test_added_resync_failure_without_push_marks_switch_unavailable():
    async def run():
        entry, switch = make_switch()
        await switch.async_update()
        assert switch.available
        entry.runtime_data.api.async_touch_tone_status.side_effect = C300XAgentApiError("offline")
        switch.hass = SimpleNamespace(bus=_EventBus())
        await switch.async_added_to_hass()
        assert not switch.available
        assert switch.should_poll is False
        assert entry.runtime_data.api.async_touch_tone_status.await_count == 2

    asyncio.run(run())


def test_confirmed_set_supersedes_an_inflight_status_read():
    async def run():
        entry, switch = make_switch()
        entered, release = asyncio.Event(), asyncio.Event()

        async def status():
            entered.set()
            await release.wait()
            return {"ok": True, "available": True, "enabled": True}

        entry.runtime_data.api.async_touch_tone_status.side_effect = status
        read = asyncio.create_task(switch.async_update())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await switch.async_turn_off()
        finally:
            release.set()
            await read
        assert switch.is_on is False and switch.available

    asyncio.run(run())


@pytest.mark.parametrize("set_fails", [False, True])
@pytest.mark.parametrize("snapshot", [False, True])
def test_new_push_wins_over_delayed_set_result(set_fails, snapshot):
    async def run():
        entry, switch = make_switch()
        entered, release = asyncio.Event(), asyncio.Event()

        async def set_enabled(enabled):
            entered.set()
            await release.wait()
            if set_fails:
                raise C300XAgentApiError("confirmation lost")
            return {"ok": True, "available": True, "enabled": enabled}

        entry.runtime_data.api.async_set_touch_tone.side_effect = set_enabled
        bus = _EventBus()
        switch.hass = SimpleNamespace(bus=bus)
        await switch.async_added_to_hass()
        entry.runtime_data.api.async_touch_tone_status.reset_mock()
        entry.runtime_data.api.async_touch_tone_status.side_effect = C300XAgentApiError("offline")
        setting = asyncio.create_task(switch.async_turn_off())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            if snapshot:
                switch._handle_state(entry.entry_id, {"enabled": True, "available": True})
            else:
                bus.push(entry, enabled=True)
        finally:
            release.set()
            if set_fails:
                with pytest.raises(HomeAssistantError, match="could not be confirmed"):
                    await setting
            else:
                await setting
        assert switch.is_on is True and switch.available
        entry.runtime_data.api.async_touch_tone_status.assert_not_awaited()

    asyncio.run(run())
