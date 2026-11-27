"""Settings snapshots update entities internally, including in-flight reads."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_switch import _FakeEntry
from test_webhook import _FakeHass, _FakeRequest

from custom_components.bticino_c300x import (
    number,
    select,
    switch,
    switch_display,
    webhook,
)
from custom_components.bticino_c300x.api_errors import C300XAgentApiError
from custom_components.bticino_c300x.const import (
    CONF_EVENT_WEBHOOK_TOKEN,
    SIGNAL_FORWARDING_CHANGED,
    SIGNAL_SETTING_STATE,
)
from custom_components.bticino_c300x.data import C300XEventState
from custom_components.bticino_c300x.event_types import HA_EVENT_TYPES

pytestmark = pytest.mark.usefixtures("entity_ha_boundary")

# The agent pushes its own notation: smartphone_forwarding.changed, ...
AGENT_TYPES = {key: agent for agent, key in HA_EVENT_TYPES.items()}

CASES = [
    (switch.C300XRingerMuteSwitch, "ringer_muted", {"muted": True}, "is_on", True, "async_ringer_status", {"muted": False}),
    (number.C300XRingerVolumeNumber, "ringer_volume_changed", {"volume": 5}, "native_value", 5, "async_ringer_status", {"volume": 2}),
    (select.C300XSmartphoneForwardingModeSelect, "smartphone_forwarding_changed", {"mode": "blocked"}, "current_option", "blocked", "async_smartphone_forwarding_status", {"mode": 0, "state": "enabled"}),
    (switch_display.C300XTouchToneSwitch, "display_touch_tone_changed", {"enabled": False, "available": True}, "is_on", False, "async_touch_tone_status", {"enabled": True, "available": True}),
]


def snapshot_handler(entity):
    return entity._handle_snapshot if isinstance(entity, switch_display.C300XTouchToneSwitch) else entity._handle_setting_state


@pytest.mark.parametrize("cls,kind,data,attribute,expected,api_name,initial", CASES)
def test_snapshot_webhook_reaches_subscribed_entity_without_public_event_or_io(
    monkeypatch, cls, kind, data, attribute, expected, api_name, initial,
):
    entry = _FakeEntry()
    entry.data[CONF_EVENT_WEBHOOK_TOKEN] = "event-token"
    entry.runtime_data.event_state = C300XEventState()
    api = entry.runtime_data.api
    read = AsyncMock(return_value=initial)
    setattr(api, api_name, read)
    entity = cls(entry)
    hass = _FakeHass()
    hass.bus.async_listen = lambda *_: lambda: None
    entity.hass = hass
    handlers = {}
    signals = []

    def connect(_hass, signal, handler):
        handlers[signal] = handler
        return lambda: handlers.pop(signal)

    for module in (switch, number, select, switch_display):
        monkeypatch.setattr(module, "async_dispatcher_connect", connect)

    def send(_hass, signal, *args):
        signals.append(signal)
        if signal in handlers:
            handlers[signal](*args)

    monkeypatch.setattr(webhook, "async_dispatcher_send", send)
    asyncio.run(entity.async_added_to_hass())
    assert SIGNAL_SETTING_STATE in handlers
    read.reset_mock()
    for available in (True, False, True):
        payload = {**data, "available": available}
        response = asyncio.run(webhook._async_handle_agent_event(
            hass, entry, entry.runtime_data.event_state,
            _FakeRequest("event-token", {"type": AGENT_TYPES[kind], "snapshot": True, "data": payload}),
        ))
        assert response.status == 200
        assert entity.available is available
        if kind == "smartphone_forwarding_changed":
            assert entry.runtime_data.event_state.smartphone_forwarding_mode == ("blocked" if available else None)
            if not available:
                entity._apply_status({"mode": None, "state": "unknown"})
                assert not entity.available
                assert entry.runtime_data.event_state.smartphone_forwarding_mode is None
        if available:
            assert getattr(entity, attribute) == expected
    assert hass.bus.events == []
    assert entry.runtime_data.event_state.event_sequence == 0
    assert entry.runtime_data.event_state.last_event is None
    if kind == "smartphone_forwarding_changed":
        assert signals.count(SIGNAL_FORWARDING_CHANGED) == 3
        assert entry.runtime_data.event_state.smartphone_forwarding_mode == "blocked"
    read.assert_not_awaited()


@pytest.mark.parametrize("read_fails", [False, True])
@pytest.mark.parametrize("cls,kind,data,attribute,expected,api_name,initial", CASES)
def test_snapshot_supersedes_delayed_read_or_failure(
    cls, kind, data, attribute, expected, api_name, initial, read_fails,
):
    async def run():
        entry = _FakeEntry()
        entry.runtime_data.event_state = C300XEventState()
        entity = cls(entry)
        entity.hass = SimpleNamespace()
        entered, release = asyncio.Event(), asyncio.Event()

        async def read():
            entered.set()
            await release.wait()
            if read_fails:
                raise C300XAgentApiError("offline")
            return initial

        setattr(entry.runtime_data.api, api_name, AsyncMock(side_effect=read))
        task = asyncio.create_task(entity.async_update())
        await entered.wait()
        snapshot_handler(entity)(entry.entry_id, kind, data)
        release.set()
        await task
        assert entity.available
        assert getattr(entity, attribute) == expected

    asyncio.run(run())


@pytest.mark.parametrize("snapshot", [False, True])
@pytest.mark.parametrize("invalid", [True, 3.9, 11, -1, None, "invalid"])
def test_invalid_volume_cannot_diverge_shared_and_entity_state(monkeypatch, snapshot, invalid):
    entry = _FakeEntry()
    entry.data[CONF_EVENT_WEBHOOK_TOKEN] = "event-token"
    entry.runtime_data.event_state = C300XEventState(ringer_volume=3)
    entity = number.C300XRingerVolumeNumber(entry)
    entity._apply_status({"volume": 3})
    hass = _FakeHass()
    monkeypatch.setattr(webhook, "async_dispatcher_send",
                        lambda _hass, _signal, *args: entity._handle_setting_state(*args))
    response = asyncio.run(webhook._async_handle_agent_event(
        hass, entry, entry.runtime_data.event_state,
        _FakeRequest("event-token", {"type": "ringer.volume_changed", "snapshot": snapshot,
                                    "data": {"volume": invalid}}),
    ))
    assert response.status == 200
    if not snapshot:
        assert hass.bus.events[0][1]["volume"] is None
        entity._handle_agent_event(SimpleNamespace(data=hass.bus.events[0][1]))
    assert entry.runtime_data.event_state.ringer_volume == entity.native_value == 3


def test_identical_action_events_remain_repeatable():
    entry = _FakeEntry()
    entry.data[CONF_EVENT_WEBHOOK_TOKEN] = "event-token"
    state = entry.runtime_data.event_state = C300XEventState()
    hass = _FakeHass()
    for _ in range(2):
        response = asyncio.run(webhook._async_handle_agent_event(
            hass, entry, state,
            _FakeRequest("event-token", {"type": "door_unlock.started", "data": {"address": "1"}}),
        ))
        assert response.status == 200
    assert len(hass.bus.events) == state.event_sequence == 2
