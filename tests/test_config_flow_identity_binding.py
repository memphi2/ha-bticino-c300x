"""Existing entries must not be rebound to an unverified physical device."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.bticino_c300x import config_flow
from custom_components.bticino_c300x.api import C300XAgentApiConnectionError
from custom_components.bticino_c300x.config_flow import (
    BticinoC300XConfigFlow,
    BticinoC300XOptionsFlow,
)
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_MAINTENANCE_TOKEN,
    CONF_ROTATE_SHARED_SECRET,
)


def existing_entry():
    return SimpleNamespace(
        unique_id="devicea", entry_id="entry", title="Door A", runtime_data=None,
        data={CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091,
              CONF_AGENT_TOKEN: "access-a", CONF_MAINTENANCE_TOKEN: "admin-a"},
        options={}, update_listeners=[],
    )


def bound_flow(entry, route):
    flow = BticinoC300XOptionsFlow(entry) if route == "options" else BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))
    flow.context = {"source": "reconfigure", "entry_id": entry.entry_id}
    flow._get_reconfigure_entry = lambda: entry
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_mismatch = Mock()
    flow.async_update_and_abort = Mock(return_value={"type": "saved"})
    flow._async_save_options = AsyncMock(return_value={"type": "saved"})
    flow.async_step_reconfigure_features = AsyncMock(return_value={"type": "features"})
    return flow


async def submit(flow, route, connection):
    if route == "options":
        return await flow.async_step_connection(connection)
    if route == "reconfigure":
        return await flow.async_step_reconfigure(connection)
    flow._reconfigure_connection = {**connection, CONF_ROTATE_SHARED_SECRET: False}
    return await flow._async_finish_reconfigure({})


@pytest.mark.parametrize("route", ["options", "reconfigure", "finish"])
@pytest.mark.parametrize("identity", ["device-b", None])
def test_wrong_or_missing_stable_identity_never_persists(monkeypatch, route, identity):
    entry = existing_entry()
    flow = bound_flow(entry, route)
    read = AsyncMock(return_value={"device_id": identity})
    monkeypatch.setattr(config_flow, "_async_agent_setup_data", read)
    result = asyncio.run(submit(flow, route, {**entry.data, CONF_AGENT_HOST: "b.local"}))
    assert result.get("reason") == "unique_id_mismatch" or result.get("errors") == {"base": "cannot_connect"}
    flow.async_update_and_abort.assert_not_called()
    flow._async_save_options.assert_not_called()
    flow.async_step_reconfigure_features.assert_not_called()
    flow.hass.config_entries.async_update_entry.assert_not_called()
    assert entry.unique_id == "devicea"
    assert entry.data[CONF_AGENT_HOST] == "a.local"


@pytest.mark.parametrize("route", ["options", "reconfigure", "finish"])
def test_matching_identity_accepts_address_change(monkeypatch, route):
    entry = existing_entry()
    flow = bound_flow(entry, route)
    read = AsyncMock(return_value={"device_id": "device-a"})
    monkeypatch.setattr(config_flow, "_async_agent_setup_data", read)
    result = asyncio.run(submit(flow, route, {**entry.data, CONF_AGENT_HOST: "new.local"}))
    assert result["type"] in {"saved", "features"}
    assert read.call_args.kwargs["api_token"] == "access-a"


@pytest.mark.parametrize("changed", [False, True])
def test_offline_unchanged_connection_is_retained_but_new_keys_are_not_saved(monkeypatch, changed):
    entry = existing_entry()
    flow = bound_flow(entry, "finish")
    monkeypatch.setattr(config_flow, "_async_agent_setup_data", AsyncMock(side_effect=C300XAgentApiConnectionError("offline")))
    result = asyncio.run(submit(flow, "finish", {**entry.data, CONF_AGENT_TOKEN: "new" if changed else "access-a"}))
    assert result.get("errors") == ({"base": "cannot_connect"} if changed else None)
    assert flow.async_update_and_abort.call_count == (0 if changed else 1)


@pytest.mark.parametrize("original_id,candidate_id", [("device-a", "device-b"), (None, "device-b"), ("device-a", "device-a")])
def test_legacy_address_change_requires_original_device_identity(monkeypatch, original_id, candidate_id):
    entry = existing_entry()
    entry.unique_id = "bticino_c300x:a.local:8091"
    flow = bound_flow(entry, "options")
    read = AsyncMock(side_effect=[{"device_id": original_id}, {"device_id": candidate_id}])
    monkeypatch.setattr(config_flow, "_async_agent_setup_data", read)
    result = asyncio.run(submit(flow, "options", {**entry.data, CONF_AGENT_HOST: "new.local"}))
    assert (result["type"] == "saved") is (original_id == candidate_id)


def test_entry_change_during_identity_read_cannot_persist(monkeypatch):
    entry = existing_entry()
    flow = bound_flow(entry, "options")

    async def read(*args, **kwargs):
        entry.options[CONF_AGENT_TOKEN] = "newer-key"
        return {"device_id": "device-a"}

    monkeypatch.setattr(config_flow, "_async_agent_setup_data", read)
    result = asyncio.run(submit(flow, "options", dict(entry.data)))
    assert result["errors"] == {"base": "cannot_connect"}
    flow._async_save_options.assert_not_called()


@pytest.mark.parametrize("mode", ["offline", "rejected", "no_key", "missing_id", "verified", "raced", "duplicate"])
def test_discovery_never_adopts_an_unverified_advertised_identity(monkeypatch, mode):
    entry = existing_entry()
    entry.unique_id = "bticino_c300x:a.local:8091"
    if mode == "no_key":
        entry.data[CONF_AGENT_TOKEN] = ""
    entries = [entry]
    if mode == "duplicate":
        entries.append(SimpleNamespace(unique_id="devicea"))
    flow = bound_flow(entry, "reconfigure")
    flow._async_current_entries = lambda: entries
    flow._abort_if_unique_id_configured = Mock()
    flow._async_request_event_registration = Mock()

    async def read(_hass, connection, *, api_token):
        assert connection[CONF_AGENT_HOST] == "a.local"
        assert api_token == "access-a"
        if mode in {"offline", "rejected"}:
            raise C300XAgentApiConnectionError("HTTP 401" if mode == "rejected" else "offline")
        if mode == "raced":
            entry.options[CONF_AGENT_HOST] = "changed.local"
        return {} if mode == "missing_id" else {"device_id": "device-a"}

    probe = AsyncMock(side_effect=read)
    monkeypatch.setattr(config_flow, "_async_agent_setup_data", probe)
    result = asyncio.run(flow.async_step_zeroconf(SimpleNamespace(
        host="a.local", port=8091, properties={"id": "forged-device"}, name="Door",
    )))
    assert result["reason"] == "already_configured"
    update = flow.hass.config_entries.async_update_entry
    if mode == "verified":
        update.assert_called_once_with(entry, unique_id="devicea")
    else:
        update.assert_not_called()
    assert probe.await_count == (0 if mode == "no_key" else 1)
