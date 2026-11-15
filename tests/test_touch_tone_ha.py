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
