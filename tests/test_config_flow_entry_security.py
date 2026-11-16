"""Entry-bound credentials, identity and concurrent flow regressions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import UNDEFINED

from custom_components.bticino_c300x import config_flow_auth
from custom_components.bticino_c300x.config_flow import (
    BticinoC300XConfigFlow,
    BticinoC300XOptionsFlow,
)
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
        data={CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091,
              CONF_AGENT_TOKEN: "old", CONF_MAINTENANCE_TOKEN: "", CONF_VIDEO_ENABLED: True},
        options={}, unique_id="devicea", entry_id="entry", title="Door",
        update_listeners=[], runtime_data=None,
    )

    def update(entry=entry, **kwargs):
        changed = False
        for key, value in kwargs.items():
            if value is not UNDEFINED and getattr(entry, key) != value:
                setattr(entry, key, dict(value) if key in {"data", "options"} else value)
                changed = True
        return changed

    hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_update_entry=Mock(side_effect=update),
        async_get_known_entry=lambda _: entry,
        async_entry_for_domain_unique_id=lambda *_: entry,
        async_schedule_reload=Mock(),
    ))
    return entry, hass


def bound_flow(entry, hass, route):
    flow = BticinoC300XOptionsFlow(entry) if route == "options" else BticinoC300XConfigFlow()
    flow.hass = hass
    flow.context = {"source": "reconfigure", "entry_id": entry.entry_id}
    flow._async_in_progress = lambda **_: []
    return flow


async def submit(flow, route, connection):
    if route == "options":
        return await flow.async_step_connection(connection)
    if route == "reconfigure":
        return await flow.async_step_reconfigure(connection)
    flow._reconfigure_connection = {**connection, CONF_ROTATE_SHARED_SECRET: False}
    return await flow._async_finish_reconfigure({})


@pytest.mark.parametrize("route", ["options", "reconfigure", "finish"])
@pytest.mark.parametrize("identity,error", [("device-b", "wrong_device"), (None, "cannot_connect")])
def test_wrong_or_missing_identity_cannot_persist(monkeypatch, route, identity, error):
    entry, hass = entry_hass()
    flow = bound_flow(entry, hass, route)
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", AsyncMock(return_value=({"device_id": identity}, {})))
    result = asyncio.run(submit(flow, route, {**current_connection_options(entry), CONF_AGENT_HOST: "b.local"}))
    assert result["errors"] == {"base": error}
    hass.config_entries.async_update_entry.assert_not_called()
    assert current_connection_options(entry)[CONF_AGENT_HOST] == "a.local"


@pytest.mark.parametrize("route", ["options", "reconfigure", "finish"])
def test_same_identity_can_change_endpoint(monkeypatch, route):
    entry, hass = entry_hass()
    flow = bound_flow(entry, hass, route)
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", AsyncMock(return_value=({"device_id": "device-a"}, {})))
    result = asyncio.run(submit(flow, route, {**current_connection_options(entry), CONF_AGENT_HOST: "new.local"}))
    assert not result.get("errors")
    if route != "reconfigure":
        assert current_connection_options(entry)[CONF_AGENT_HOST] == "new.local"
    assert entry.unique_id == "devicea"


@pytest.mark.parametrize("original,candidate", [("device-a", "device-b"), (None, "device-b"), ("device-a", "device-a")])
def test_manual_entry_endpoint_change_proves_original_identity(monkeypatch, original, candidate):
    entry, hass = entry_hass()
    entry.unique_id = "bticino_c300x:a.local:8091"
    flow = bound_flow(entry, hass, "options")
    validate = AsyncMock(side_effect=[({"device_id": original}, {}), ({"device_id": candidate}, {})])
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validate)
    result = asyncio.run(submit(flow, "options", {**current_connection_options(entry), CONF_AGENT_HOST: "b.local"}))
    assert bool(result.get("errors")) is (original != candidate)
    assert validate.call_args_list[0].args[1][CONF_AGENT_HOST] == "a.local"


@pytest.mark.parametrize("change", ["endpoint", "identity", "credentials"])
def test_connection_change_during_validation_cannot_persist(monkeypatch, change):
    entry, hass = entry_hass()
    flow = bound_flow(entry, hass, "options")

    async def validate(*args):
        if change == "identity":
            entry.unique_id = "deviceb"
        else:
            entry.options[CONF_AGENT_HOST if change == "endpoint" else CONF_AGENT_TOKEN] = "changed"
        return {"device_id": "device-a"}, {}

    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validate)
    result = asyncio.run(submit(flow, "options", dict(entry.data)))
    assert result["errors"] == {"base": "cannot_connect"}
    hass.config_entries.async_update_entry.assert_not_called()


def test_offline_feature_edit_does_not_require_credentials(monkeypatch):
    entry, hass = entry_hass()
    flow = bound_flow(entry, hass, "options")
    validate = AsyncMock(side_effect=AssertionError("offline feature editing must not probe"))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validate)
    result = asyncio.run(flow.async_step_features({CONF_VIDEO_ENABLED: False}))
    assert result["type"] == "menu"
    assert current_connection_options(entry)[CONF_AGENT_TOKEN] == "old"
    validate.assert_not_called()


@pytest.mark.parametrize("change", ["reauth", "options", "reconfigure"])
def test_open_feature_form_keeps_newer_connection_when_saved(monkeypatch, change):
    entry, hass = entry_hass()
    flow = bound_flow(entry, hass, "options")
    validate = AsyncMock(return_value=({"device_id": "device-a"}, {}))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validate)

    async def exercise():
        await flow.async_step_features()
        other = bound_flow(entry, hass, "options" if change == "options" else "reconfigure")
        if change == "reauth":
            other.context["source"] = "reauth"
            await other.async_step_reauth_confirm({CONF_AGENT_TOKEN: "new-valid"})
        else:
            await submit(other, "options" if change == "options" else "finish", {
                **current_connection_options(entry), CONF_AGENT_TOKEN: "new-valid",
                CONF_AGENT_HOST: "new.local",
            })
        before = current_connection_options(entry)
        entry.options["unrelated"] = "concurrent-value"
        calls = validate.await_count
        await flow.async_step_features({CONF_VIDEO_ENABLED: False})
        assert current_connection_options(entry) == before
        assert entry.options["unrelated"] == "concurrent-value"
        assert entry.options[CONF_VIDEO_ENABLED] is False
        assert validate.await_count == calls

    asyncio.run(exercise())


def test_connection_save_keeps_the_exact_validated_credential_pair(monkeypatch):
    entry, hass = entry_hass()
    flow = bound_flow(entry, hass, "options")
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", AsyncMock(return_value=({"device_id": "device-a"}, {})))

    async def exercise():
        await flow.async_step_connection()
        entry.data[CONF_AGENT_TOKEN] = "newer"
        await flow.async_step_connection({**current_connection_options(entry), CONF_AGENT_HOST: "new.local", CONF_AGENT_TOKEN: "old"})
        assert current_connection_options(entry)[CONF_AGENT_HOST] == "new.local"
        assert current_connection_options(entry)[CONF_AGENT_TOKEN] == "old"

    asyncio.run(exercise())


@pytest.mark.parametrize("route", ["options", "finish", "reauth"])
@pytest.mark.parametrize("listeners", [False, True])
@pytest.mark.parametrize("changed", [False, True])
def test_credential_recovery_reloads_exactly_once(monkeypatch, route, listeners, changed):
    entry, hass = entry_hass()
    entry.update_listeners = [object()] if listeners else []
    entry.runtime_data = SimpleNamespace(connection_state=SimpleNamespace(authentication_failed=True))
    flow = bound_flow(entry, hass, "options" if route == "options" else "reconfigure")
    update = hass.config_entries.async_update_entry.side_effect

    def with_listener(*args, **kwargs):
        did_change = update(*args, **kwargs)
        if listeners and did_change:
            hass.config_entries.async_schedule_reload(entry.entry_id)
            # An eager HA update listener can start unloading before returning.
            entry.update_listeners.clear()
        return did_change

    hass.config_entries.async_update_entry.side_effect = with_listener
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", AsyncMock(return_value=({"device_id": "device-a"}, {})))
    connection = current_connection_options(entry)
    entry.data.update(connection)
    if changed:
        entry.options[CONF_AGENT_TOKEN] = "override"
        connection[CONF_AGENT_TOKEN] = "new-valid"
    if route == "reauth":
        flow.context["source"] = "reauth"
        result = asyncio.run(flow.async_step_reauth_confirm({CONF_AGENT_TOKEN: connection[CONF_AGENT_TOKEN]}))
    else:
        result = asyncio.run(submit(flow, route, connection))
    assert not result.get("errors")
    hass.config_entries.async_schedule_reload.assert_called_once_with(entry.entry_id)
    # Clearing shadowing options and writing data must be one atomic update.
    assert hass.config_entries.async_update_entry.call_count <= 1


def test_healthy_unchanged_connection_options_do_not_reload(monkeypatch):
    entry, hass = entry_hass()
    entry.update_listeners = [object()]
    flow = bound_flow(entry, hass, "options")
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", AsyncMock(return_value=({"device_id": "device-a"}, {})))
    asyncio.run(flow.async_step_connection(current_connection_options(entry)))
    hass.config_entries.async_schedule_reload.assert_not_called()
    hass.config_entries.async_update_entry.assert_not_called()
