"""Discovery hints never replace authenticated identity evidence."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.bticino_c300x import config_flow, config_flow_auth
from custom_components.bticino_c300x.api import (
    C300XAgentApiAuthError,
    C300XAgentApiConnectionError,
)
from custom_components.bticino_c300x.const import CONF_AGENT_HOST, CONF_AGENT_TOKEN
from tests.test_config_flow_entry_security import bound_flow, entry_hass


@pytest.mark.parametrize("mode", ["offline", "rejected", "no_key", "missing_id", "verified", "raced", "duplicate"])
def test_discovery_never_adopts_unverified_advertised_identity(monkeypatch, mode):
    entry, hass = entry_hass()
    entry.unique_id = "bticino_c300x:a.local:8091"
    if mode == "no_key":
        entry.data[CONF_AGENT_TOKEN] = ""
    entries = [entry]
    if mode == "duplicate":
        entries.append(SimpleNamespace(unique_id="devicea"))
    flow = bound_flow(entry, hass, "reconfigure")
    flow._async_current_entries = lambda: entries
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    flow._async_request_event_registration = Mock()

    async def read(_hass, connection, *, api_token):
        assert connection[CONF_AGENT_HOST] == "a.local"
        assert api_token == "old"
        if mode == "offline":
            raise C300XAgentApiConnectionError("offline")
        if mode == "rejected":
            raise C300XAgentApiAuthError()
        if mode == "raced":
            entry.options[CONF_AGENT_HOST] = "changed.local"
        return {} if mode == "missing_id" else {"device_id": "device-a"}

    probe = AsyncMock(side_effect=read)
    monkeypatch.setattr(config_flow, "_async_agent_setup_data", probe)
    result = asyncio.run(flow.async_step_zeroconf(SimpleNamespace(
        host="a.local", port=8091, properties={"id": "forged-device"}, name="Door",
    )))
    assert result["reason"] == "already_configured"
    if mode == "verified":
        assert entry.unique_id == "devicea"
    else:
        assert entry.unique_id == "bticino_c300x:a.local:8091"
        hass.config_entries.async_update_entry.assert_not_called()
    assert probe.await_count == (0 if mode == "no_key" else 1)


def test_new_discovery_identity_comes_from_authenticated_read(monkeypatch):
    entry, hass = entry_hass()
    flow = bound_flow(entry, hass, "reconfigure")
    flow._async_current_entries = lambda: []
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    monkeypatch.setattr(config_flow, "_async_probe_agent", AsyncMock(return_value="auth_required"))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", AsyncMock(return_value=({"device_id": "actual-device"}, {})))

    async def exercise():
        await flow.async_step_zeroconf(SimpleNamespace(host="new.local", port=8091, properties={"id": "forged-device"}, name="Door"))
        assert flow._setup_unique_id is None
        result = await flow.async_step_agent_auth({CONF_AGENT_TOKEN: "valid"})
        assert result["step_id"] == "user_features"
        assert flow._setup_unique_id == "actualdevice"

    asyncio.run(exercise())


@pytest.mark.parametrize("identity,error", [("device-b", "wrong_device"), (None, "cannot_connect")])
def test_setup_finish_cannot_change_authenticated_identity(monkeypatch, identity, error):
    entry, hass = entry_hass()
    flow = bound_flow(entry, hass, "reconfigure")
    flow._setup_unique_id = "devicea"
    flow._setup_connection = {**entry.data, "name": "Door"}
    flow.async_create_entry = Mock(side_effect=AssertionError("must not create"))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", AsyncMock(return_value=({"device_id": identity}, {})))
    result = asyncio.run(flow._async_create_setup_entry({}))
    assert result["errors"] == {"base": error}
    flow.async_create_entry.assert_not_called()
