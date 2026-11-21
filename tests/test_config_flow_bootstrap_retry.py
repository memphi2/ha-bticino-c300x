"""Bootstrap recovery retains generated keys without persisting SSH secrets."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.bticino_c300x import config_flow, config_flow_auth
from custom_components.bticino_c300x.config_flow import BticinoC300XConfigFlow
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
    CONF_MAINTENANCE_TOKEN,
    CONF_VIDEO_ENABLED,
)


@pytest.mark.parametrize("failure", ["cannot_connect", "invalid_auth", "invalid_maintenance_auth"])
@pytest.mark.parametrize("replace_access", [False, True])
def test_bootstrap_final_validation_retry_retains_generated_keys(monkeypatch, failure, replace_access):
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {"source": "user"}
    flow._setup_connection = {"name": "Door", CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091}
    flow._async_abort_if_manual_setup_duplicate = AsyncMock()
    flow._async_adopt_agent_unique_id = AsyncMock()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    installer = AsyncMock()
    monkeypatch.setattr(config_flow, "async_ensure_installer_dependencies", AsyncMock())
    monkeypatch.setattr(config_flow, "async_install_device_agent", installer)
    monkeypatch.setattr(config_flow, "_async_probe_agent", AsyncMock(return_value="reachable"))
    monkeypatch.setattr(config_flow, "async_migrate_legacy_mqtt_for_connection", AsyncMock())
    validator = AsyncMock(return_value=({}, {"base": failure}))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validator)

    async def exercise():
        result = await flow.async_step_bootstrap_install({
            CONF_BOOTSTRAP_SSH_USERNAME: "ssh-user", CONF_BOOTSTRAP_SSH_PASSWORD: "ssh-secret",
        })
        assert result["step_id"] == "user_features"
        generated = dict(flow._setup_connection)
        feature_data, errors = config_flow._feature_input({CONF_VIDEO_ENABLED: False})
        assert not errors
        result = await flow._async_create_setup_entry(feature_data)
        assert result["step_id"] == "agent_auth"
        assert result["errors"] == {"base": failure}
        submitted = result["data_schema"]({})
        assert submitted[CONF_AGENT_TOKEN] == submitted[CONF_MAINTENANCE_TOKEN] == ""
        assert "ssh-secret" not in str(flow._setup_connection)
        assert "ssh-user" not in str(flow._setup_connection)
        if replace_access:
            submitted[CONF_AGENT_TOKEN] = "replacement"
        expected_access = "replacement" if replace_access else generated[CONF_AGENT_TOKEN]

        async def validated(_hass, candidate):
            assert candidate[CONF_AGENT_TOKEN] == expected_access
            assert candidate[CONF_MAINTENANCE_TOKEN] == generated[CONF_MAINTENANCE_TOKEN]
            return {"device_id": "device-a"}, {}

        validator.side_effect = validated
        result = await flow.async_step_agent_auth(submitted)
        assert result["type"] == "create_entry"
        assert result["data"][CONF_AGENT_TOKEN] == expected_access
        assert result["data"][CONF_MAINTENANCE_TOKEN] == generated[CONF_MAINTENANCE_TOKEN]
        assert result["data"][CONF_VIDEO_ENABLED] is False
        installer.assert_awaited_once()

    asyncio.run(exercise())


def test_manual_setup_blank_keys_do_not_inherit_prior_input(monkeypatch):
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {"source": "user"}
    flow._setup_connection = {CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091, CONF_AGENT_TOKEN: "prior", CONF_MAINTENANCE_TOKEN: "prior-admin"}
    validator = AsyncMock(return_value=({}, {}))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validator)
    result = asyncio.run(flow.async_step_agent_auth({}))
    assert result["step_id"] == "user_features"
    candidate = validator.call_args.args[1]
    assert candidate[CONF_AGENT_TOKEN] == candidate[CONF_MAINTENANCE_TOKEN] == ""


def test_manual_final_validation_retry_keeps_the_typed_maintenance_key(monkeypatch):
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {"source": "user"}
    flow._setup_connection = {
        "name": "Door", CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091,
        CONF_AGENT_TOKEN: "typed-access", CONF_MAINTENANCE_TOKEN: "typed-maintenance",
    }
    flow._async_abort_if_manual_setup_duplicate = AsyncMock()
    flow._async_adopt_agent_unique_id = AsyncMock()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    monkeypatch.setattr(config_flow, "async_migrate_legacy_mqtt_for_connection", AsyncMock())
    validator = AsyncMock(return_value=({}, {"base": "cannot_connect"}))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validator)

    async def exercise():
        feature_data, errors = config_flow._feature_input({CONF_VIDEO_ENABLED: False})
        assert not errors
        result = await flow._async_create_setup_entry(feature_data)
        assert result["step_id"] == "agent_auth"
        submitted = result["data_schema"]({})
        submitted[CONF_AGENT_TOKEN] = "retyped-access"

        async def validated(_hass, candidate):
            assert candidate[CONF_AGENT_TOKEN] == "retyped-access"
            assert candidate[CONF_MAINTENANCE_TOKEN] == "typed-maintenance"
            return {"device_id": "device-a"}, {}

        validator.side_effect = validated
        result = await flow.async_step_agent_auth(submitted)
        assert result["type"] == "create_entry"
        assert result["data"][CONF_MAINTENANCE_TOKEN] == "typed-maintenance"

    asyncio.run(exercise())



def test_manual_retry_after_a_rejected_maintenance_key_can_clear_it(monkeypatch):
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {"source": "user"}
    flow._setup_connection = {
        "name": "Door", CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091,
        CONF_AGENT_TOKEN: "typed-access", CONF_MAINTENANCE_TOKEN: "rejected-maintenance",
    }
    flow._async_abort_if_manual_setup_duplicate = AsyncMock()
    flow._async_adopt_agent_unique_id = AsyncMock()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    monkeypatch.setattr(config_flow, "async_migrate_legacy_mqtt_for_connection", AsyncMock())
    validator = AsyncMock(return_value=({}, {"base": "invalid_maintenance_auth"}))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validator)

    async def exercise():
        feature_data, errors = config_flow._feature_input({CONF_VIDEO_ENABLED: False})
        assert not errors
        result = await flow._async_create_setup_entry(feature_data)
        assert result["errors"] == {"base": "invalid_maintenance_auth"}
        submitted = result["data_schema"]({})

        async def validated(_hass, candidate):
            assert candidate[CONF_AGENT_TOKEN] == "typed-access"
            assert candidate[CONF_MAINTENANCE_TOKEN] == ""
            return {"device_id": "device-a"}, {}

        validator.side_effect = validated
        result = await flow.async_step_agent_auth(submitted)
        assert result["type"] == "create_entry"
        assert result["data"][CONF_MAINTENANCE_TOKEN] == ""

    asyncio.run(exercise())


def test_a_key_rejected_on_the_retry_itself_can_be_cleared(monkeypatch):
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {"source": "user"}
    flow._setup_connection = {
        "name": "Door", CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091,
        CONF_AGENT_TOKEN: "old-access", CONF_MAINTENANCE_TOKEN: "old-maintenance",
    }
    flow._async_abort_if_manual_setup_duplicate = AsyncMock()
    flow._async_adopt_agent_unique_id = AsyncMock()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    monkeypatch.setattr(config_flow, "async_migrate_legacy_mqtt_for_connection", AsyncMock())
    seen = []

    async def validated(_hass, candidate):
        seen.append(candidate[CONF_MAINTENANCE_TOKEN])
        if len(seen) == 1:
            return {}, {"base": "cannot_connect"}
        if candidate[CONF_MAINTENANCE_TOKEN]:
            return {}, {"base": "invalid_maintenance_auth"}
        return {"device_id": "device-a"}, {}

    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validated)

    async def exercise():
        feature_data, errors = config_flow._feature_input({CONF_VIDEO_ENABLED: False})
        assert not errors
        result = await flow._async_create_setup_entry(feature_data)
        assert result["errors"] == {"base": "cannot_connect"}
        submitted = result["data_schema"]({})
        submitted[CONF_AGENT_TOKEN] = "new-access"
        result = await flow.async_step_agent_auth(submitted)
        assert result["errors"] == {"base": "invalid_maintenance_auth"}
        submitted = result["data_schema"]({})
        submitted[CONF_AGENT_TOKEN] = "new-access"
        result = await flow.async_step_agent_auth(submitted)
        assert result["type"] == "create_entry"
        # final check, first retry, second retry, final check after it
        assert seen == ["old-maintenance", "old-maintenance", "", ""]

    asyncio.run(exercise())


def test_a_key_typed_on_a_failed_retry_is_kept_when_another_key_is_rejected(monkeypatch):
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {"source": "user"}
    flow._setup_connection = {
        "name": "Door", CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091,
        CONF_AGENT_TOKEN: "rejected-access", CONF_MAINTENANCE_TOKEN: "rejected-maintenance",
    }
    flow._async_abort_if_manual_setup_duplicate = AsyncMock()
    flow._async_adopt_agent_unique_id = AsyncMock()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    monkeypatch.setattr(config_flow, "async_migrate_legacy_mqtt_for_connection", AsyncMock())
    seen = []

    async def validated(_hass, candidate):
        seen.append((candidate[CONF_AGENT_TOKEN], candidate[CONF_MAINTENANCE_TOKEN]))
        if candidate[CONF_AGENT_TOKEN] != "good-access":
            return {}, {"base": "invalid_auth"}
        if candidate[CONF_MAINTENANCE_TOKEN]:
            return {}, {"base": "invalid_maintenance_auth"}
        if len(seen) == 3:
            return {}, {"base": "cannot_connect"}
        return {"device_id": "device-a"}, {}

    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validated)

    async def exercise():
        feature_data, errors = config_flow._feature_input({CONF_VIDEO_ENABLED: False})
        assert not errors
        result = await flow._async_create_setup_entry(feature_data)
        assert result["errors"] == {"base": "invalid_auth"}
        submitted = result["data_schema"]({})
        submitted[CONF_AGENT_TOKEN] = "good-access"
        result = await flow.async_step_agent_auth(submitted)
        assert result["errors"] == {"base": "invalid_maintenance_auth"}
        result = await flow.async_step_agent_auth(result["data_schema"]({}))
        assert result["errors"] == {"base": "cannot_connect"}
        result = await flow.async_step_agent_auth(result["data_schema"]({}))
        assert result["type"] == "create_entry"
        assert result["data"][CONF_AGENT_TOKEN] == "good-access"
        assert seen[2:] == [("good-access", ""), ("good-access", ""), ("good-access", "")]

    asyncio.run(exercise())


def test_a_rejected_key_the_device_later_accepts_is_kept(monkeypatch):
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {"source": "user"}
    flow._setup_connection = {
        "name": "Door", CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091,
        CONF_AGENT_TOKEN: "access", CONF_MAINTENANCE_TOKEN: "maintenance",
    }
    flow._async_abort_if_manual_setup_duplicate = AsyncMock()
    flow._async_adopt_agent_unique_id = AsyncMock()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    monkeypatch.setattr(config_flow, "async_migrate_legacy_mqtt_for_connection", AsyncMock())
    seen = []

    async def validated(_hass, candidate):
        seen.append((candidate[CONF_AGENT_TOKEN], candidate[CONF_MAINTENANCE_TOKEN]))
        if len(seen) == 1:
            return {}, {"base": "invalid_auth"}  # a passing 401 while the agent restarts
        if candidate[CONF_MAINTENANCE_TOKEN]:
            return {}, {"base": "invalid_maintenance_auth"}
        return {"device_id": "device-a"}, {}

    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validated)

    async def exercise():
        feature_data, errors = config_flow._feature_input({CONF_VIDEO_ENABLED: False})
        assert not errors
        result = await flow._async_create_setup_entry(feature_data)
        assert result["errors"] == {"base": "invalid_auth"}
        submitted = result["data_schema"]({})
        submitted[CONF_AGENT_TOKEN] = "access"
        result = await flow.async_step_agent_auth(submitted)
        assert result["errors"] == {"base": "invalid_maintenance_auth"}
        result = await flow.async_step_agent_auth(result["data_schema"]({}))
        assert result["type"] == "create_entry"
        assert result["data"][CONF_AGENT_TOKEN] == "access"

    asyncio.run(exercise())


def test_keys_accepted_before_a_wrong_device_answer_are_kept(monkeypatch):
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {"source": "user"}
    flow._setup_connection = {
        "name": "Door", CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091,
        CONF_AGENT_TOKEN: "rejected-access", CONF_MAINTENANCE_TOKEN: "",
    }
    flow._async_abort_if_manual_setup_duplicate = AsyncMock()
    flow._async_adopt_agent_unique_id = AsyncMock()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    monkeypatch.setattr(config_flow, "async_migrate_legacy_mqtt_for_connection", AsyncMock())
    seen = []
    wrong_device = Mock(side_effect=[{"base": "wrong_device"}, {}])
    flow._setup_identity_error = wrong_device

    async def validated(_hass, candidate):
        seen.append(candidate[CONF_AGENT_TOKEN])
        if candidate[CONF_AGENT_TOKEN] != "good-access":
            return {}, {"base": "invalid_auth"}
        return {"device_id": "device-a"}, {}

    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validated)
    monkeypatch.setattr(flow, "_async_validate_setup_identity", AsyncMock(side_effect=[{"base": "invalid_auth"}, {}]))

    async def exercise():
        feature_data, errors = config_flow._feature_input({CONF_VIDEO_ENABLED: False})
        assert not errors
        flow._note_setup_rejection({"base": "invalid_auth"}, flow._setup_connection)
        result = await flow._async_create_setup_entry(feature_data)
        assert result["errors"] == {"base": "invalid_auth"}
        submitted = result["data_schema"]({})
        submitted[CONF_AGENT_TOKEN] = "good-access"
        result = await flow.async_step_agent_auth(submitted)
        assert result["errors"] == {"base": "wrong_device"}
        result = await flow.async_step_agent_auth(result["data_schema"]({}))
        assert seen == ["good-access", "good-access"]
        assert result["type"] == "create_entry"

    asyncio.run(exercise())


def _bootstrap_flow(monkeypatch, installer):
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {"source": "user"}
    flow._setup_connection = {"name": "Door", CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091}
    flow._async_abort_if_manual_setup_duplicate = AsyncMock()
    flow._async_adopt_agent_unique_id = AsyncMock()
    monkeypatch.setattr(config_flow, "async_ensure_installer_dependencies", AsyncMock())
    monkeypatch.setattr(config_flow, "async_install_device_agent", installer)
    monkeypatch.setattr(config_flow, "_async_probe_agent", AsyncMock(return_value="reachable"))
    monkeypatch.setattr(config_flow, "async_migrate_legacy_mqtt_for_connection", AsyncMock())
    return flow


def test_bootstrap_installs_with_the_factory_login_without_asking(monkeypatch):
    from custom_components.bticino_c300x.factory_login import factory_ssh_login

    installer = AsyncMock()
    flow = _bootstrap_flow(monkeypatch, installer)
    result = asyncio.run(flow.async_step_agent_missing({"bootstrap_install_agent": True}))
    assert result["step_id"] == "user_features"
    request = installer.call_args.args[0]
    assert (request.ssh_username, request.ssh_password) == factory_ssh_login()


def test_bootstrap_asks_for_a_login_only_after_the_factory_login_was_refused(monkeypatch):
    from custom_components.bticino_c300x.device_installer import C300XDeviceInstallError
    from custom_components.bticino_c300x.factory_login import factory_ssh_login

    installer = AsyncMock(side_effect=C300XDeviceInstallError("ssh_login_refused"))
    flow = _bootstrap_flow(monkeypatch, installer)

    async def exercise():
        result = await flow.async_step_agent_missing({"bootstrap_install_agent": True})
        assert result["step_id"] == "bootstrap_install"
        assert result["errors"] == {"base": "ssh_login_refused"}
        request = installer.call_args.args[0]
        assert (request.ssh_username, request.ssh_password) == factory_ssh_login()
        installer.side_effect = None
        result = await flow.async_step_bootstrap_install({
            CONF_BOOTSTRAP_SSH_USERNAME: " admin ", CONF_BOOTSTRAP_SSH_PASSWORD: "typed",
        })
        assert result["step_id"] == "user_features"
        request = installer.call_args.args[0]
        assert (request.ssh_username, request.ssh_password) == ("admin", "typed")
        assert installer.await_count == 2

    asyncio.run(exercise())
