"""Authenticated config flows, using actual HA flow helpers and mocked I/O."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.const import CONF_NAME

from custom_components.bticino_c300x import config_flow, config_flow_auth
from custom_components.bticino_c300x.api import C300XAgentApiAuthError
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
from tests.test_api import _QueuedSession

CONNECTION = {CONF_AGENT_HOST: "c300x.local", CONF_AGENT_PORT: 8091, CONF_AGENT_TOKEN: "old"}


def entry():
    return SimpleNamespace(
        data={**CONNECTION, "shared_secret": "keep"},
        options={CONF_AGENT_TOKEN: "override", "unrelated": "keep"},
        unique_id="bticino_c300x:c300x.local:8091", entry_id="entry", title="Door",
        update_listeners=[], runtime_data=None,
    )


@pytest.mark.parametrize(
    ("responses", "key", "error"),
    [
        ([(401, "secret")], "key", "invalid_auth"),
        ([(200, "{}"), (403, "secret")], "key", "invalid_auth"),
        ([(200, "{}"), (200, "{}"), (403, "secret")], "key", "invalid_maintenance_auth"),
        ([(503, "offline")], "key", "cannot_connect"),
        ([(200, "bad json")], "key", "cannot_connect"),
        ([(200, "{}"), (404, "{}")], "key", "cannot_connect"),
        ([(200, "{}"), (200, "{}")], "", None),
        ([(200, "{}"), (200, "{}"), (200, "{}")], "key", None),
    ],
)
def test_shared_validation_is_read_only(monkeypatch, responses, key, error):
    session = _QueuedSession(responses)
    monkeypatch.setattr(config_flow_auth, "async_get_clientsession", lambda _: session)
    _, errors = asyncio.run(config_flow_auth.async_validate_connection(
        object(), {**CONNECTION, CONF_AGENT_TOKEN: key, CONF_MAINTENANCE_TOKEN: key},
    ))
    assert errors == ({"base": error} if error else {})
    assert all(request["args"][0] == "GET" for request in session.requests)


@pytest.mark.parametrize("error", ["invalid_auth", "invalid_maintenance_auth", "cannot_connect"])
@pytest.mark.parametrize("route", ["manual", "zeroconf", "skip_installer", "create", "reconfigure", "finish", "options"])
def test_all_credential_routes_reject_without_persistence(monkeypatch, route, error):
    existing = entry()
    flow = BticinoC300XOptionsFlow(existing) if route == "options" else BticinoC300XConfigFlow()
    update = Mock()
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))
    flow.context = {}
    flow.async_show_form = lambda **kwargs: kwargs
    flow.async_create_entry = Mock(side_effect=AssertionError("must not create"))
    flow.async_update_and_abort = Mock(side_effect=AssertionError("must not save"))
    validate = AsyncMock(return_value=({}, {"base": error}))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validate)
    flow._setup_connection = {**CONNECTION, CONF_NAME: "Door"}
    flow._reconfigure_connection = {**CONNECTION, CONF_ROTATE_SHARED_SECRET: True}
    flow._get_reconfigure_entry = lambda: existing
    flow._async_save_options = AsyncMock(side_effect=AssertionError("must not save options"))

    async def exercise():
        if route == "skip_installer":
            await flow.async_step_agent_missing({"bootstrap_install_agent": False})
        if route == "zeroconf":
            flow._setup_unique_id = "discovered"
        if route in {"manual", "zeroconf", "skip_installer"}:
            return await flow.async_step_agent_auth({CONF_AGENT_TOKEN: "bad"})
        if route == "create":
            return await flow._async_create_setup_entry({})
        if route == "reconfigure":
            return await flow.async_step_reconfigure({**CONNECTION, CONF_AGENT_TOKEN: "bad"})
        if route == "finish":
            return await flow._async_finish_reconfigure({})
        return await flow.async_step_connection({**CONNECTION, CONF_AGENT_TOKEN: "bad"})

    result = asyncio.run(exercise())
    assert result["errors"] == {"base": error}
    assert result["step_id"] == (
        "connection" if route == "options" else "reconfigure" if route in {"reconfigure", "finish"} else "agent_auth"
    )
    update.assert_not_called()
    assert existing.options[CONF_AGENT_TOKEN] == "override"
    assert existing.data[CONF_AGENT_TOKEN] == "old"


def test_probe_uses_exception_type_not_error_message(monkeypatch):
    monkeypatch.setattr(config_flow, "_async_agent_ready_for_setup", AsyncMock(side_effect=C300XAgentApiAuthError()))
    assert asyncio.run(config_flow._async_probe_agent(object(), CONNECTION)) == "auth_required"


@pytest.mark.parametrize("listeners", [False, True])
@pytest.mark.parametrize("changed", [False, True])
def test_reauth_updates_only_keys_and_reloads_once(monkeypatch, listeners, changed):
    existing = entry()
    existing.options = {"unrelated": "keep"}
    existing.data[CONF_MAINTENANCE_TOKEN] = ""
    existing.update_listeners = [object()] if listeners else []
    flow = BticinoC300XConfigFlow()
    flow.context = {"source": "reauth", "entry_id": "entry"}
    reload = Mock()
    updates = []

    def update_entry(**kwargs):
        updates.append(kwargs)
        existing.data = dict(kwargs["data"])
        existing.options = dict(kwargs["options"])
        if listeners and changed:
            reload(existing.entry_id)
        return changed

    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_get_known_entry=lambda _: existing,
        async_update_entry=update_entry, async_schedule_reload=reload,
    ))
    validate = AsyncMock(return_value=({}, {}))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validate)
    result = asyncio.run(flow.async_step_reauth_confirm({CONF_AGENT_TOKEN: "new" if changed else ""}))
    assert result["reason"] == "reauth_successful"
    assert len(updates) == 1
    reload.assert_called_once_with("entry")
    assert existing.data["shared_secret"] == "keep"
    assert existing.options == {"unrelated": "keep"}
    assert existing.data[CONF_AGENT_TOKEN] == ("new" if changed else "old")
    assert validate.call_args.args[1][CONF_AGENT_HOST] == "c300x.local"


def test_reauth_replaces_shadowing_option_key(monkeypatch):
    existing = entry()
    flow = BticinoC300XConfigFlow()
    flow._get_reauth_entry = lambda: existing
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_schedule_reload=Mock()))
    flow.async_update_and_abort = Mock(return_value={"reason": "reauth_successful"})
    validate = AsyncMock(return_value=({}, {}))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validate)
    asyncio.run(flow.async_step_reauth_confirm({CONF_AGENT_TOKEN: "new"}))
    assert flow.async_update_and_abort.call_args.kwargs["options"] == {"unrelated": "keep"}


@pytest.mark.parametrize("error", ["invalid_auth", "invalid_maintenance_auth", "cannot_connect"])
def test_reauth_failure_keeps_entry_and_secrets_hidden(monkeypatch, error):
    flow = BticinoC300XConfigFlow()
    flow._get_reauth_entry = entry
    flow.hass = SimpleNamespace()
    flow.context = {"source": "reauth", "entry_id": "entry"}
    flow.async_update_and_abort = Mock(side_effect=AssertionError("must not save"))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", AsyncMock(return_value=({}, {"base": error})))
    result = asyncio.run(flow.async_step_reauth_confirm({CONF_AGENT_TOKEN: "rejected-secret"}))
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": error}
    assert "rejected-secret" not in str(result)


def test_reauth_wrong_identity_is_not_saved(monkeypatch):
    existing = entry()
    existing.unique_id = "bticino_c300x:device:expected"
    flow = BticinoC300XConfigFlow()
    flow._get_reauth_entry = lambda: existing
    flow.hass = SimpleNamespace()
    flow.async_update_and_abort = Mock(side_effect=AssertionError("must not save"))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", AsyncMock(return_value=({"device_id": "other"}, {})))
    # Use a stable discovery identity, not the host-based legacy identity.
    from custom_components.bticino_c300x.discovery import discovery_unique_id
    existing.unique_id = discovery_unique_id({"id": "expected"})
    assert asyncio.run(flow.async_step_reauth_confirm({CONF_AGENT_TOKEN: "new"}))["reason"] == "reauth_wrong_device"


def test_reauth_entry_data_cannot_redirect_credentials():
    flow = BticinoC300XConfigFlow()
    flow._get_reauth_entry = entry
    flow.context = {"source": "reauth", "entry_id": "entry"}
    result = asyncio.run(flow.async_step_reauth({CONF_AGENT_HOST: "attacker.invalid"}))
    assert result["step_id"] == "reauth_confirm"
    assert "attacker.invalid" not in str(result)


def test_reauth_does_not_save_keys_when_endpoint_changes_during_probe(monkeypatch):
    existing = entry()
    flow = BticinoC300XConfigFlow()
    flow._get_reauth_entry = lambda: existing
    flow.hass = SimpleNamespace()
    flow.context = {"source": "reauth", "entry_id": "entry"}
    flow.async_update_and_abort = Mock(side_effect=AssertionError("must not save"))

    async def validate(*args):
        existing.options[CONF_AGENT_HOST] = "changed.local"
        return {}, {}

    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validate)
    result = asyncio.run(flow.async_step_reauth_confirm({CONF_AGENT_TOKEN: "new"}))
    assert result["errors"] == {"base": "cannot_connect"}
    assert existing.data[CONF_AGENT_TOKEN] == "old"


def test_validation_cancellation_is_not_a_form_error(monkeypatch):
    api = SimpleNamespace(async_validate_setup=AsyncMock(side_effect=asyncio.CancelledError))
    monkeypatch.setattr(config_flow_auth, "async_get_clientsession", lambda _: object())
    monkeypatch.setattr(config_flow_auth, "C300XAgentApi", lambda *_: api)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(config_flow_auth.async_validate_connection(object(), CONNECTION))


@pytest.mark.parametrize("language", ["en", "de", "fr", "it"])
def test_auth_forms_and_errors_are_translated(language):
    root = Path(__file__).resolve().parents[1] / "custom_components/bticino_c300x"
    translation = json.loads((root / f"translations/{language}.json").read_text())
    assert translation["config"]["step"]["reauth_confirm"]["data"].keys() == {
        "agent_token", "maintenance_token",
    }
    assert translation["config"]["abort"]["reauth_wrong_device"]
    for section in ("config", "options"):
        for key in ("invalid_auth", "invalid_maintenance_auth", "cannot_connect"):
            assert translation[section]["error"][key]
