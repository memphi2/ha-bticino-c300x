"""A Classe 100X is set up only after the user asked for its experimental support."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import CONF_NAME

from custom_components.bticino_c300x import config_flow, config_flow_auth
from custom_components.bticino_c300x.config_flow import BticinoC300XConfigFlow
from custom_components.bticino_c300x.config_flow_c100x import CONF_C100X_EXPERIMENTAL
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
)
from custom_components.bticino_c300x.device_installer import C300XDeviceInstallError

COMPONENT = Path(config_flow.__file__).parent
CONNECTION = {CONF_NAME: "Door", CONF_AGENT_HOST: "station.invalid", CONF_AGENT_PORT: 8091}
C100X_REFUSAL = C300XDeviceInstallError("c100x_confirmation_required")


def _auth_flow(monkeypatch, setup):
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {}
    flow._setup_connection = dict(CONNECTION)
    validate = AsyncMock(return_value=(setup, {}))
    monkeypatch.setattr(config_flow_auth, "async_validate_connection", validate)
    flow.async_step_user_features = AsyncMock(return_value={"step_id": "user_features"})
    return flow, validate


@pytest.mark.parametrize("setup", [
    {"device_id": "station", "model": "C300X"},
    {"device_id": "station", "model": "C300X", "display_kind": "qt4_ondisk"},
    {"device_id": "station", "model": "C300X", "display_kind": "qt5_rcc"},
    # An agent that names no model is a C300X, as before.
    {"device_id": "station"},
])
def test_a_c300x_with_a_running_agent_is_set_up_without_the_question(monkeypatch, setup):
    flow, validate = _auth_flow(monkeypatch, setup)
    result = asyncio.run(flow.async_step_agent_auth({CONF_AGENT_TOKEN: "valid"}))
    assert result == {"step_id": "user_features"}
    assert validate.await_count == 1
    assert flow._c100x_confirmed is False and flow._c100x_resume is None


@pytest.mark.parametrize("setup", [
    {"device_id": "station", "model": "C100X"},
    {"device_id": "station", "model": "C100X", "display_kind": "qt5_ondisk"},
    {"device_id": "station", "model": "C300X", "display_kind": "qt5_ondisk", "model_check": "mismatch"},
])
def test_a_c100x_with_a_running_agent_waits_for_the_confirmation(monkeypatch, setup):
    flow, validate = _auth_flow(monkeypatch, setup)

    async def exercise():
        result = await flow.async_step_agent_auth({CONF_AGENT_TOKEN: "valid"})
        assert result["step_id"] == "c100x_experimental" and result["errors"] == {}
        # The box is empty by default; nothing was taken over from the station.
        assert result["data_schema"]({}) == {CONF_C100X_EXPERIMENTAL: False}
        assert flow._setup_agent_info == {}
        flow.async_step_user_features.assert_not_awaited()
        # Left empty: the question stays, with its error.
        result = await flow.async_step_c100x_experimental({CONF_C100X_EXPERIMENTAL: False})
        assert result["step_id"] == "c100x_experimental"
        assert result["errors"] == {"base": "c100x_confirmation_required"}
        flow.async_step_user_features.assert_not_awaited()
        # Confirmed: the keys entered before are checked again, then setup goes on.
        result = await flow.async_step_c100x_experimental({CONF_C100X_EXPERIMENTAL: True})
        assert result == {"step_id": "user_features"}
        assert validate.await_count == 2
        assert validate.await_args.args[1][CONF_AGENT_TOKEN] == "valid"
        assert flow._setup_agent_info["model"] == setup["model"]
        # Asked once per setup.
        assert (await flow.async_step_agent_auth({CONF_AGENT_TOKEN: "valid"})) == {"step_id": "user_features"}

    asyncio.run(exercise())


def _bootstrap_flow(monkeypatch, installer):
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {"source": "user"}
    flow._setup_connection = dict(CONNECTION)
    flow._async_abort_if_manual_setup_duplicate = AsyncMock()
    flow._async_adopt_agent_unique_id = AsyncMock()
    flow.async_step_user_features = AsyncMock(return_value={"step_id": "user_features"})
    monkeypatch.setattr(config_flow, "async_ensure_installer_dependencies", AsyncMock())
    monkeypatch.setattr(config_flow, "async_install_device_agent", installer)
    monkeypatch.setattr(config_flow, "_async_probe_agent", AsyncMock(return_value="reachable"))
    monkeypatch.setattr(config_flow, "async_migrate_legacy_mqtt_for_connection", AsyncMock())
    return flow


def test_a_c300x_is_installed_without_the_question(monkeypatch):
    installer = AsyncMock()
    flow = _bootstrap_flow(monkeypatch, installer)
    result = asyncio.run(flow.async_step_agent_missing({"bootstrap_install_agent": True}))
    assert result == {"step_id": "user_features"}
    assert installer.await_count == 1
    # The installer is never told to accept a C100X unless the user said so.
    assert installer.call_args.args[0].c100x_confirmed is False


@pytest.mark.parametrize("typed", [None, {CONF_BOOTSTRAP_SSH_USERNAME: "admin", CONF_BOOTSTRAP_SSH_PASSWORD: "typed"}])
def test_the_installer_stops_at_a_c100x_until_the_user_confirmed(monkeypatch, typed):
    from custom_components.bticino_c300x.factory_login import factory_ssh_login

    installer = AsyncMock(side_effect=C100X_REFUSAL)
    flow = _bootstrap_flow(monkeypatch, installer)

    async def exercise():
        if typed is None:
            result = await flow.async_step_agent_missing({"bootstrap_install_agent": True})
        else:
            flow._factory_login_tried = True
            result = await flow.async_step_bootstrap_install(typed)
        assert result["step_id"] == "c100x_experimental" and result["errors"] == {}
        assert installer.call_args.args[0].c100x_confirmed is False
        flow.async_step_user_features.assert_not_awaited()
        result = await flow.async_step_c100x_experimental({})
        assert result["errors"] == {"base": "c100x_confirmation_required"}
        assert installer.await_count == 1
        installer.side_effect = None
        result = await flow.async_step_c100x_experimental({CONF_C100X_EXPERIMENTAL: True})
        assert result == {"step_id": "user_features"}
        assert installer.await_count == 2
        request = installer.call_args.args[0]
        assert request.c100x_confirmed is True
        # The same login as before the question.
        expected = factory_ssh_login() if typed is None else ("admin", "typed")
        assert (request.ssh_username, request.ssh_password) == expected
        assert request.factory_login is (typed is None)

    asyncio.run(exercise())


def test_another_install_error_is_shown_as_before(monkeypatch):
    installer = AsyncMock(side_effect=C300XDeviceInstallError("ssh_login_refused"))
    flow = _bootstrap_flow(monkeypatch, installer)
    result = asyncio.run(flow.async_step_agent_missing({"bootstrap_install_agent": True}))
    assert (result["step_id"], result["errors"]) == ("bootstrap_install", {"base": "ssh_login_refused"})


def test_the_question_without_a_station_returns_to_the_start(monkeypatch):
    flow = BticinoC300XConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {}
    flow.async_step_user = AsyncMock(return_value={"step_id": "user"})
    assert asyncio.run(flow.async_step_c100x_experimental({CONF_C100X_EXPERIMENTAL: True})) == {"step_id": "user"}
    assert flow._c100x_confirmed is False


def test_an_update_of_an_existing_entry_needs_no_question():
    repairs = (COMPONENT / "repairs.py").read_text(encoding="utf-8")
    assert repairs.count("c100x_confirmed=True") == 1
    flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    assert flow.count("c100x_confirmed=self._c100x_confirmed") == 1
    assert 'setdefault("model", "C100X")' not in flow


@pytest.mark.parametrize("name", ["strings.json", "translations/en.json", "translations/de.json",
                                  "translations/it.json", "translations/fr.json"])
def test_the_question_has_its_texts_in_every_language(name):
    texts = json.loads((COMPONENT / name).read_text(encoding="utf-8"))["config"]
    step = texts["step"]["c100x_experimental"]
    assert "Classe 100X" in step["title"] and "Classe 100X" in step["description"]
    assert "1.5.8" in step["description"]
    assert set(step["data"]) == {CONF_C100X_EXPERIMENTAL}
    assert "Classe 100X" in texts["error"]["c100x_confirmation_required"]
    assert "c100x_package_only" not in texts["abort"]
    assert "C100X" not in texts["error"]["device_model_incompatible"]


def test_the_opt_in_text_claims_no_device_test() -> None:
    """The C100X side is checked against the firmware files, not yet on a station."""

    confirmed = {
        "strings.json": "checked without a device so far, not yet confirmed on a Classe 100X",
        "translations/en.json": "checked without a device so far, not yet confirmed on a Classe 100X",
        "translations/de.json": "bisher nur ohne Gerät geprüft, noch nicht auf einer Classe 100X bestätigt",
        "translations/fr.json": "vérifiée jusqu'ici que sans appareil, pas encore confirmée sur un Classe 100X",
        "translations/it.json": "finora verificato solo senza dispositivo, non ancora confermato su un Classe 100X",
    }
    for name, wording in confirmed.items():
        document = json.loads((COMPONENT / name).read_text(encoding="utf-8"))
        text = document["config"]["step"]["c100x_experimental"]["description"]
        assert wording in text, name
        for claim in ("tested", "getestet", "testée", "provato"):
            assert claim not in text, (name, claim)
