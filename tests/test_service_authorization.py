"""Real HA dispatch must preserve callers and deny unauthorized device commands."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import Unauthorized, UnknownUser
from homeassistant.helpers.service import async_register_admin_service

from custom_components.bticino_c300x import service_authorization
from custom_components.bticino_c300x.const import DOMAIN
from custom_components.bticino_c300x.services import (
    _C300XServiceHandlers,
    _register_base_services,
)


def setup_hass(tmp_path, monkeypatch, *, allowed=(), admin=False):
    hass = HomeAssistant(str(tmp_path))
    user = SimpleNamespace(
        is_admin=admin,
        permissions=SimpleNamespace(
            check_entity=lambda entity_id, _policy: entity_id in allowed,
        ),
    )
    hass.auth = SimpleNamespace(async_get_user=AsyncMock(return_value=user))
    api = SimpleNamespace(async_unlock_door=AsyncMock(), async_reboot=AsyncMock())
    entry = SimpleNamespace(
        entry_id="test",
        data={"maintenance_token": "test"},
        options={},
        runtime_data=SimpleNamespace(
            api=api,
            capabilities={
                "maintenance": {"supported": True, "reboot": True},
            },
        ),
    )
    hass.config_entries = SimpleNamespace(async_entries=lambda _domain: [entry])
    registry = SimpleNamespace(
        async_get_entity_id=lambda domain, _platform, unique: f"{domain}.{unique}",
        async_get=lambda _entity_id: SimpleNamespace(disabled_by=None),
    )
    monkeypatch.setattr(service_authorization.er, "async_get", lambda _hass: registry)
    _register_base_services(hass, _C300XServiceHandlers(hass))
    return hass, entry


@pytest.mark.parametrize(
    "service", ["unlock_door", "reboot", "reload_gui", "write_text_memo"]
)
def test_read_only_caller_cannot_control_device(tmp_path, monkeypatch, service):
    async def run():
        hass, entry = setup_hass(tmp_path, monkeypatch)
        data = {"text": "test"} if service == "write_text_memo" else {}
        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                DOMAIN, service, data, blocking=True, context=Context(user_id="reader")
            )
        entry.runtime_data.api.async_unlock_door.assert_not_awaited()
        entry.runtime_data.api.async_reboot.assert_not_awaited()

    asyncio.run(run())


def test_control_permission_is_for_the_selected_lock(tmp_path, monkeypatch):
    async def run():
        hass, entry = setup_hass(
            tmp_path, monkeypatch, allowed={"button.test_door_unlock"}
        )
        context = Context(user_id="controller")
        await hass.services.async_call(
            DOMAIN, "unlock_door", {}, blocking=True, context=context
        )
        for data in ({"lock_id": "other"},):
            with pytest.raises(Unauthorized):
                await hass.services.async_call(
                    DOMAIN, "unlock_door", data, blocking=True, context=context
                )
        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                DOMAIN, "reboot", {}, blocking=True, context=context
            )
        entry.runtime_data.api.async_unlock_door.assert_awaited_once_with("default")
        entry.runtime_data.api.async_reboot.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("user_id,admin", [(None, False), ("owner", True)])
def test_owner_and_trusted_automation_can_maintain(
    tmp_path, monkeypatch, user_id, admin
):
    async def run():
        hass, entry = setup_hass(tmp_path, monkeypatch, admin=admin)
        await hass.services.async_call(
            DOMAIN, "reboot", {}, blocking=True, context=Context(user_id=user_id)
        )
        entry.runtime_data.api.async_reboot.assert_awaited_once()

    asyncio.run(run())


def test_action_keeps_context_and_cannot_bypass_admin_check(tmp_path, monkeypatch):
    async def run():
        hass, entry = setup_hass(tmp_path, monkeypatch)
        target = AsyncMock()
        async_register_admin_service(hass, "test", "protected", target)
        entry.options["actions"] = {
            "protected": {"domain": "test", "service": "protected"}
        }
        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                DOMAIN,
                "run_action",
                {"action_id": "protected"},
                blocking=True,
                context=Context(user_id="reader"),
            )
        target.assert_not_awaited()
        seen = []

        async def action(call):
            seen.append(call.context)

        hass.services.async_register("test", "allowed", action)
        entry.options["actions"]["allowed"] = {"domain": "test", "service": "allowed"}
        context = Context(user_id="controller")
        await hass.services.async_call(
            DOMAIN,
            "run_action",
            {"action_id": "allowed"},
            blocking=True,
            context=context,
        )
        assert seen == [context]

    asyncio.run(run())


def test_unknown_user_cannot_fall_back_to_trusted_automation(tmp_path, monkeypatch):
    async def run():
        hass, entry = setup_hass(tmp_path, monkeypatch)
        hass.auth.async_get_user.return_value = None
        with pytest.raises(UnknownUser):
            await hass.services.async_call(
                DOMAIN, "unlock_door", {}, blocking=True, context=Context(user_id="removed")
            )
        entry.runtime_data.api.async_unlock_door.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("disabled", [True, False])
def test_missing_or_disabled_control_entity_denies_service(tmp_path, monkeypatch, disabled):
    async def run():
        hass, entry = setup_hass(tmp_path, monkeypatch, allowed={"button.test_door_unlock"})
        registry = service_authorization.er.async_get(hass)
        registry.async_get = lambda _id: SimpleNamespace(disabled_by="user") if disabled else None
        with pytest.raises(Unauthorized):
            await hass.services.async_call(
                DOMAIN, "unlock_door", {}, blocking=True, context=Context(user_id="controller")
            )
        entry.runtime_data.api.async_unlock_door.assert_not_awaited()

    asyncio.run(run())
