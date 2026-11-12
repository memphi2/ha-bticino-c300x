"""Alarm service failures must reach HA callers, not look like completed actions."""

import asyncio
from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.bticino_c300x import executor
from custom_components.bticino_c300x.const import CONF_ALARM_ENTITY_ID, DOMAIN
from custom_components.bticino_c300x.services import (
    _C300XServiceHandlers,
    _register_base_services,
)


def setup_alarm_service(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    entry = SimpleNamespace(
        entry_id="test",
        data={CONF_ALARM_ENTITY_ID: "alarm_control_panel.home"},
        options={},
        runtime_data=SimpleNamespace(),
    )
    hass.config_entries = SimpleNamespace(async_entries=lambda _domain: [entry])
    hass.states.async_set("alarm_control_panel.home", "armed_away")
    _register_base_services(hass, _C300XServiceHandlers(hass))
    return hass


@pytest.mark.parametrize(
    "reason,code,expected_error",
    [
        ("invalid_code", "test-secret", "alarm_invalid_code"),
        ("rejected", None, "alarm_command_rejected"),
        ("unconfirmed", None, "alarm_state_unconfirmed"),
        ("unconfirmed", "test-valid-code", "alarm_state_unconfirmed"),
    ],
)
def test_alarm_service_reports_rejected_or_unconfirmed_commands(
    tmp_path, monkeypatch, reason, code, expected_error
):
    async def run():
        hass = setup_alarm_service(tmp_path)
        calls = []

        async def disarm(call):
            calls.append(call)
            if reason == "invalid_code":
                raise ServiceValidationError("Invalid code: test-secret")
            if reason == "rejected":
                raise ServiceValidationError("Device rejected command: test-secret")
            # An accepted service call need not result in a changed alarm state.

        hass.services.async_register("alarm_control_panel", "alarm_disarm", disarm)
        monkeypatch.setattr(executor, "_ALARM_STATE_CHANGE_TIMEOUT_SECONDS", 0)
        data = {"command": "disarm"}
        if code is not None:
            data["code"] = code
        with pytest.raises(ServiceValidationError) as error:
            await hass.services.async_call(
                DOMAIN, "alarm_command", data, blocking=True
            )
        assert error.value.translation_key == expected_error
        assert "test-secret" not in str(error.value)
        assert len(calls) == 1
        assert hass.states.get("alarm_control_panel.home").state == "armed_away"

    asyncio.run(run())


def test_alarm_service_reports_preflight_block_without_dispatch(tmp_path, monkeypatch):
    async def run():
        hass = setup_alarm_service(tmp_path)
        calls = []

        async def arm(call):
            calls.append(call)

        hass.services.async_register("alarm_control_panel", "alarm_arm_home", arm)
        monkeypatch.setattr(
            executor,
            "_alarmo_command_preflight",
            lambda *_args, **_kwargs: {
                "ready": False,
                "blocking_sensors": [],
                "blocking_sensor_count": 1,
            },
        )
        with pytest.raises(ServiceValidationError) as error:
            await hass.services.async_call(
                DOMAIN, "alarm_command", {"command": "arm_home"}, blocking=True
            )
        assert error.value.translation_key == "alarm_not_ready"
        assert calls == []

    asyncio.run(run())


def test_alarm_service_completes_when_target_state_is_confirmed(tmp_path):
    async def run():
        hass = setup_alarm_service(tmp_path)
        calls = []

        async def disarm(call):
            calls.append(call)
            hass.states.async_set("alarm_control_panel.home", "disarmed")

        hass.services.async_register("alarm_control_panel", "alarm_disarm", disarm)
        await hass.services.async_call(
            DOMAIN, "alarm_command", {"command": "disarm"}, blocking=True
        )
        assert len(calls) == 1
        assert hass.states.get("alarm_control_panel.home").state == "disarmed"

    asyncio.run(run())
