"""Concurrent options and recovery updates preserve current entry settings."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import UNDEFINED

from custom_components.bticino_c300x import config_flow
from custom_components.bticino_c300x.config_flow_features import (
    current_connection_options,
)
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_MAINTENANCE_TOKEN,
    CONF_ROTATE_SHARED_SECRET,
    CONF_VIDEO_ENABLED,
)


def entry_hass():
    entry = SimpleNamespace(
        data={CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091, CONF_AGENT_TOKEN: "old",
              CONF_MAINTENANCE_TOKEN: "", CONF_VIDEO_ENABLED: True},
        options={}, unique_id="devicea", entry_id="entry", title="Door", runtime_data=None,
        update_listeners=[],
    )

    def update(entry=entry, **kwargs):
        changed = False
        for key, value in kwargs.items():
            if value is not UNDEFINED and getattr(entry, key) != value:
                setattr(entry, key, dict(value) if key in {"data", "options"} else value)
                changed = True
        return changed

    hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_update_entry=Mock(side_effect=update), async_get_known_entry=lambda _: entry,
        async_entry_for_domain_unique_id=lambda *_: entry, async_schedule_reload=Mock(),
    ))
    return entry, hass


def flow_for(entry, hass, route):
    flow = config_flow.BticinoC300XOptionsFlow(entry) if route == "options" else config_flow.BticinoC300XConfigFlow()
    flow.hass = hass
    flow.context = {"source": "reconfigure", "entry_id": entry.entry_id}
    flow._async_in_progress = lambda **_: []
    return flow


async def submit(flow, route, connection):
    if route == "options":
        return await flow.async_step_connection(connection)
    flow._reconfigure_connection = {**connection, CONF_ROTATE_SHARED_SECRET: False}
    return await flow._async_finish_reconfigure({})


@pytest.mark.parametrize("route", ["options", "reconfigure"])
def test_stale_feature_form_cannot_restore_old_endpoint_or_credentials(monkeypatch, route):
    entry, hass = entry_hass()
    first = flow_for(entry, hass, "options")
    second = flow_for(entry, hass, route)
    read = AsyncMock(return_value={"device_id": "device-a"})
    monkeypatch.setattr(config_flow, "_async_agent_setup_data", read)

    async def exercise():
        await first.async_step_features()
        await submit(second, route, {**current_connection_options(entry), CONF_AGENT_HOST: "new.local", CONF_AGENT_TOKEN: "new-valid"})
        connection = current_connection_options(entry)
        entry.options["unrelated"] = "concurrent"
        calls = read.await_count
        await first.async_step_features({CONF_VIDEO_ENABLED: False})
        assert current_connection_options(entry) == connection
        assert entry.options["unrelated"] == "concurrent"
        assert entry.options[CONF_VIDEO_ENABLED] is False
        assert read.await_count == calls

    asyncio.run(exercise())


def test_connection_save_keeps_exact_validated_pair(monkeypatch):
    entry, hass = entry_hass()
    flow = flow_for(entry, hass, "options")
    monkeypatch.setattr(config_flow, "_async_agent_setup_data", AsyncMock(return_value={"device_id": "device-a"}))

    async def exercise():
        await flow.async_step_connection()
        entry.data[CONF_AGENT_TOKEN] = "newer"
        await flow.async_step_connection({**current_connection_options(entry), CONF_AGENT_HOST: "new.local", CONF_AGENT_TOKEN: "old"})
        assert current_connection_options(entry)[CONF_AGENT_HOST] == "new.local"
        assert current_connection_options(entry)[CONF_AGENT_TOKEN] == "old"

    asyncio.run(exercise())


@pytest.mark.parametrize("route", ["options", "reconfigure"])
@pytest.mark.parametrize("listeners", [False, True])
@pytest.mark.parametrize("changed", [False, True])
def test_recovery_reload_is_listener_aware_and_atomic(monkeypatch, route, listeners, changed):
    entry, hass = entry_hass()
    entry.update_listeners = [object()] if listeners else []
    flow = flow_for(entry, hass, route)
    update = hass.config_entries.async_update_entry.side_effect

    def with_listener(*args, **kwargs):
        did_change = update(*args, **kwargs)
        if listeners and did_change:
            hass.config_entries.async_schedule_reload(entry.entry_id)
            entry.update_listeners.clear()
        return did_change

    hass.config_entries.async_update_entry.side_effect = with_listener
    monkeypatch.setattr(config_flow, "_async_agent_setup_data", AsyncMock(return_value={"device_id": "device-a"}))
    connection = current_connection_options(entry)
    entry.data.update(connection)
    if changed:
        entry.options[CONF_AGENT_TOKEN] = "override"
        connection[CONF_AGENT_TOKEN] = "corrected"
    result = asyncio.run(submit(flow, route, connection))
    assert not result.get("errors")
    assert hass.config_entries.async_schedule_reload.call_count == (0 if listeners and not changed else 1)
    assert hass.config_entries.async_update_entry.call_count <= 1
