"""An optional private key on every SSH credential form; used for one install, never kept."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.bticino_c300x import config_flow
from custom_components.bticino_c300x.config_flow import BticinoC300XConfigFlow
from custom_components.bticino_c300x.config_flow_input import _bootstrap_install_schema
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_BOOTSTRAP_SSH_KEY,
    CONF_BOOTSTRAP_SSH_KEY_PASSPHRASE,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
)
from custom_components.bticino_c300x.device_installer import (
    C300XDeviceInstallError,
    C300XDeviceInstallRequest,
    _validate_request,
)
from custom_components.bticino_c300x.factory_login import (
    factory_ssh_login,
    install_login,
)
from custom_components.bticino_c300x.repairs import (
    _ssh_install_error,
    _ssh_install_schema,
)

KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nkey-material-for-the-test\n-----END OPENSSH PRIVATE KEY-----"
FIELDS = {CONF_BOOTSTRAP_SSH_USERNAME, CONF_BOOTSTRAP_SSH_PASSWORD, CONF_BOOTSTRAP_SSH_KEY,
          CONF_BOOTSTRAP_SSH_KEY_PASSPHRASE}


@pytest.mark.parametrize(("typed", "expected"), [
    # Nothing typed: the factory login, as before.
    ({}, ("root", factory_ssh_login()[1], "", "", True)),
    # A key alone logs in as the factory user, without the factory password.
    ({CONF_BOOTSTRAP_SSH_KEY: KEY}, ("root", "", KEY, "", False)),
    ({CONF_BOOTSTRAP_SSH_KEY: f"  {KEY}\n", CONF_BOOTSTRAP_SSH_KEY_PASSPHRASE: "phrase"},
     ("root", "", KEY, "phrase", False)),
    ({CONF_BOOTSTRAP_SSH_USERNAME: " root2 ", CONF_BOOTSTRAP_SSH_KEY: KEY}, ("root2", "", KEY, "", False)),
    # The typed password is the key's fallback.
    ({CONF_BOOTSTRAP_SSH_USERNAME: "root", CONF_BOOTSTRAP_SSH_PASSWORD: "typed", CONF_BOOTSTRAP_SSH_KEY: KEY},
     ("root", "typed", KEY, "", False)),
    # A passphrase without a key means nothing.
    ({CONF_BOOTSTRAP_SSH_USERNAME: "u", CONF_BOOTSTRAP_SSH_PASSWORD: "p", CONF_BOOTSTRAP_SSH_KEY_PASSPHRASE: "x"},
     ("u", "p", "", "", False)),
])
def test_the_form_values_become_the_login_of_the_install(typed, expected):
    login = install_login(typed, "C300X")
    assert (login["ssh_username"], login["ssh_password"], login["ssh_private_key"],
            login["ssh_key_passphrase"], login["factory_login"]) == expected
    assert login["device_model"] == "C300X"


def test_a_key_without_a_password_is_a_valid_request_and_is_never_shown():
    request = C300XDeviceInstallRequest(
        host="station.local", **install_login({CONF_BOOTSTRAP_SSH_KEY: KEY, CONF_BOOTSTRAP_SSH_KEY_PASSPHRASE: "phrase"}),
    )
    _validate_request(request)
    assert "key-material" not in repr(request) and "phrase" not in repr(request)
    with pytest.raises(C300XDeviceInstallError, match="invalid_ssh_password"):
        _validate_request(C300XDeviceInstallRequest(host="station.local", ssh_username="root", ssh_password=""))


def test_every_ssh_credential_form_offers_the_key_and_its_passphrase():
    assert {str(key) for key in _bootstrap_install_schema().schema} == FIELDS
    assert {str(key) for key in _ssh_install_schema(True).schema} == FIELDS
    assert _ssh_install_schema(False).schema == {}
    # The repair names an unreadable key instead of a general failure.
    assert _ssh_install_error(C300XDeviceInstallError("invalid_ssh_key")) == "invalid_ssh_key"


def test_setup_installs_with_the_key_and_keeps_it_nowhere(monkeypatch):
    installer = AsyncMock(side_effect=C300XDeviceInstallError("ssh_login_refused"))
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

    async def exercise():
        result = await flow.async_step_agent_missing({"bootstrap_install_agent": True})
        # The factory login comes first, without asking.
        assert result["errors"] == {"base": "ssh_login_refused"}
        assert installer.await_args.args[0].factory_login is True
        assert {str(key) for key in result["data_schema"].schema} == FIELDS
        installer.side_effect = None
        result = await flow.async_step_bootstrap_install({
            CONF_BOOTSTRAP_SSH_USERNAME: "", CONF_BOOTSTRAP_SSH_PASSWORD: "",
            CONF_BOOTSTRAP_SSH_KEY: KEY, CONF_BOOTSTRAP_SSH_KEY_PASSPHRASE: "phrase",
        })
        assert result["step_id"] == "user_features"
        request = installer.await_args.args[0]
        assert (request.ssh_username, request.ssh_private_key, request.ssh_key_passphrase) == ("root", KEY, "phrase")
        assert request.factory_login is False and request.ssh_password == ""

    asyncio.run(exercise())
    # Nothing of the key stays in the flow, whose connection becomes the entry.
    assert "key-material" not in repr(vars(flow)) and "phrase" not in repr(vars(flow))


def test_a_login_without_root_rights_is_named_and_asks_for_another():
    assert _ssh_install_error(C300XDeviceInstallError("ssh_user_not_root")) == "ssh_user_not_root"


@pytest.mark.parametrize("reason", ["ssh_unreachable", "ssh_password_login_disabled"])
def test_the_repair_names_why_ssh_failed(reason):
    assert _ssh_install_error(C300XDeviceInstallError(reason)) == reason
