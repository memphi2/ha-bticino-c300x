"""Real HA legacy notify service lifecycle and bounded native delivery."""

import asyncio
import json
import re
from contextlib import asynccontextmanager
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant import config_entries, loader
from homeassistant.components.http import HomeAssistantHTTP
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.bticino_c300x import runtime_manager
from custom_components.bticino_c300x.data import C300XRuntimeResources
from custom_components.bticino_c300x.display_notifications import (
    async_notification_action,
    notification_payload,
)
from custom_components.bticino_c300x.notify import (
    C300XNotificationService,
    async_setup_notify,
    async_unload_notify,
)


def entry_for(key="first", *, enabled=True, capability=True):
    callbacks = []
    return SimpleNamespace(
        entry_id=key, data={}, options={"device_ui_enabled": enabled},
        async_on_unload=callbacks.append, unload_callbacks=callbacks,
        runtime_data=SimpleNamespace(
            capabilities={"display_alerts": capability},
            api=SimpleNamespace(async_send_display_alert=AsyncMock()),
            display_notifications=None, resources=C300XRuntimeResources(),
        ),
    )


@asynccontextmanager
async def notify_context(tmp_path, monkeypatch, **options):
    hass = HomeAssistant(str(tmp_path))
    hass.config.skip_pip = True
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    hass.http = HomeAssistantHTTP(hass, None, None, None, ["127.0.0.1"], 0, [], "modern")
    # UI/HTTP are outside this service test; notify and its registry are real HA.
    hass.config.components.update({"http", "websocket_api", "frontend"})
    monkeypatch.setattr(runtime_manager, "_async_schedule_display_bridge_notify", lambda *a, **kw: None)
    entry = entry_for(**options)
    try:
        await async_setup_notify(hass, entry)
        yield hass, entry
    finally:
        for callback in entry.unload_callbacks:
            callback()
        entry.runtime_data.resources.close()
        await hass.async_block_till_done()
        await hass.async_stop()


async def send(hass, entry, **kwargs):
    await hass.services.async_call(
        "notify", f"bticino_c300x_{entry.entry_id}",
        {"message": "Test message", **kwargs}, blocking=True,
    )


@pytest.mark.parametrize("severity,sound,priority", [("info", 0, "normal"), ("warning", 30, "important"), ("error", 30, "urgent")])
def test_standard_notify_payload_replacement_and_ack(tmp_path, monkeypatch, severity, sound, priority):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, entry):
            await send(hass, entry, data={"severity": severity, "notification_id": "notice"})
            api = entry.runtime_data.api.async_send_display_alert
            first = api.call_args.args[0]
            assert first == {
                "id": first["id"], "notification_id": "notice", "revision": first["revision"],
                "severity": severity, "title": "Home Assistant", "message": "Test message",
                "wake_duration": 30, "sound_duration": sound, "expires_in": 3600,
            }
            assert re.fullmatch("[0-9a-f]{32}", first["id"])
            assert re.fullmatch("[0-9a-f]{32}", first["revision"])
            assert notification_payload(entry)[0]["priority"] == priority
            assert notification_payload(entry)[0]["revision"] == first["revision"]
            await send(hass, entry, title="Replacement", data={"notification_id": "notice", "wake_duration": 0, "sound_duration": 0, "expires_in": 1})
            current = api.call_args.args[0]
            assert current["revision"] != first["revision"]
            assert current["id"] != first["id"]
            assert current["wake_duration"] == current["sound_duration"] == 0
            assert current["expires_in"] == 1
            assert len(notification_payload(entry)) == 1
            with pytest.raises(ValueError, match="stale_notification"):
                await async_notification_action(hass, entry, "notice", json.dumps({"revision": first["revision"], "action_id": None}))
            assert await async_notification_action(hass, entry, "notice", json.dumps({"revision": current["revision"], "action_id": None})) == {"ok": True}
            assert notification_payload(entry) == []
            assert api.await_count == 2
    asyncio.run(run())


@pytest.mark.parametrize("bad", [
    {"severity": "urgent"}, {"severity": True}, {"severity": []},
    {"wake_duration": -1}, {"wake_duration": 301}, {"wake_duration": True},
    {"wake_duration": "30"}, {"wake_duration": 1.5}, {"wake_duration": None},
    {"sound_duration": -1}, {"sound_duration": 301}, {"sound_duration": False},
    {"sound_duration": "30"}, {"sound_duration": 1.0},
    {"expires_in": 0}, {"expires_in": 604801}, {"expires_in": True}, {"expires_in": "30"},
    {"notification_id": "Upper"}, {"notification_id": "x" * 65}, {"notification_id": "../a"},
    {"url": "https://example.com"}, {"audio_file": "/tmp/beep.wav"},
    {"command": "beep"}, {"actions": []}, {"title": "not a data field"},
])
def test_invalid_data_has_no_storage_or_transport_effect(tmp_path, monkeypatch, bad):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, entry):
            with pytest.raises(ServiceValidationError):
                await send(hass, entry, data=bad)
            assert entry.runtime_data.display_notifications is None
            entry.runtime_data.api.async_send_display_alert.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("bad", [{"title": ""}, {"title": " "}, {"title": "x" * 81}, {"message": ""}, {"message": "x" * 501}, {"target": ["another"]}])
def test_invalid_standard_fields(tmp_path, monkeypatch, bad):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, entry):
            with pytest.raises(ServiceValidationError):
                await send(hass, entry, **bad)
            assert entry.runtime_data.display_notifications is None
            entry.runtime_data.api.async_send_display_alert.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("capability", [False, None, 1, "true", {"supported": True}])
def test_available_service_requires_boolean_capability_before_storage(tmp_path, monkeypatch, capability):
    async def run():
        async with notify_context(tmp_path, monkeypatch, capability=capability) as (hass, entry):
            assert hass.services.has_service("notify", "bticino_c300x_first")
            with pytest.raises(ServiceValidationError, match="require an update"):
                await send(hass, entry)
            assert entry.runtime_data.display_notifications is None
            entry.runtime_data.api.async_send_display_alert.assert_not_awaited()
            entry.runtime_data.capabilities["display_alerts"] = True
            await send(hass, entry)
            entry.runtime_data.api.async_send_display_alert.assert_awaited_once()
    asyncio.run(run())


def test_service_per_entry_unload_reload_and_disabled(tmp_path, monkeypatch):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, first):
            second, disabled = entry_for("second"), entry_for("disabled", enabled=False)
            await async_setup_notify(hass, second)
            await async_setup_notify(hass, disabled)
            await async_setup_notify(hass, first)
            assert len(first.unload_callbacks) == 1
            assert not hass.services.has_service("notify", "bticino_c300x_disabled")
            for callback in first.unload_callbacks:
                callback()
            assert not hass.services.has_service("notify", "bticino_c300x_first")
            assert hass.services.has_service("notify", "bticino_c300x_second")
            await async_setup_notify(hass, first)
            await send(hass, first)
            await send(hass, second)
            assert notification_payload(first)[0]["id"] != notification_payload(second)[0]["id"]
            async_unload_notify(hass, second)
            second.runtime_data.resources.close()
            async_unload_notify(hass, first)
            assert "bticino_c300x_notify_services" not in hass.data
    asyncio.run(run())


@pytest.mark.parametrize("failure", [RuntimeError("failed"), asyncio.CancelledError()])
def test_partial_registration_is_rolled_back(tmp_path, monkeypatch, failure):
    original = C300XNotificationService.async_register_services

    async def fail(self):
        await original(self)
        raise failure

    async def run():
        async with notify_context(tmp_path, monkeypatch, enabled=False) as (hass, entry):
            entry.options["device_ui_enabled"] = True
            monkeypatch.setattr(C300XNotificationService, "async_register_services", fail)
            with pytest.raises(type(failure)):
                await async_setup_notify(hass, entry)
            assert not hass.services.has_service("notify", "bticino_c300x_first")
            assert "bticino_c300x_notify_services" not in hass.data
            assert not entry.unload_callbacks
    asyncio.run(run())


def test_failed_delivery_keeps_notice_without_retry(tmp_path, monkeypatch):
    from custom_components.bticino_c300x.api_errors import C300XAgentApiConnectionError

    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, entry):
            api = entry.runtime_data.api.async_send_display_alert
            api.side_effect = C300XAgentApiConnectionError("display_alerts_gui_unavailable")
            with pytest.raises(HomeAssistantError, match="wake and sound are not confirmed"):
                await send(hass, entry)
            api.assert_awaited_once()
            assert len(notification_payload(entry)) == 1
    asyncio.run(run())


def test_explicit_maximum_bounds_and_default_ids(tmp_path, monkeypatch):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, entry):
            await send(hass, entry, title="t" * 80, message="m" * 500, data={
                "notification_id": "n" * 64, "wake_duration": 300,
                "sound_duration": 300, "expires_in": 604800,
            })
            payload = entry.runtime_data.api.async_send_display_alert.call_args.args[0]
            assert payload["title"] == "t" * 80
            assert payload["message"] == "m" * 500
            assert payload["notification_id"] == "n" * 64
            assert payload["wake_duration"] == payload["sound_duration"] == 300
            assert payload["expires_in"] == 604800
            await send(hass, entry)
            generated = entry.runtime_data.api.async_send_display_alert.call_args.args[0]
            assert re.fullmatch("[a-f0-9]{32}", generated["notification_id"])
            assert generated["notification_id"] != generated["id"]
    asyncio.run(run())


def test_unload_cancels_pending_delivery(tmp_path, monkeypatch):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, entry):
            started, stopped = asyncio.Event(), asyncio.Event()

            async def wait_for_native(payload):
                started.set()
                try:
                    await asyncio.Future()
                finally:
                    stopped.set()

            api = entry.runtime_data.api.async_send_display_alert
            api.side_effect = wait_for_native
            task = asyncio.create_task(send(hass, entry))
            await asyncio.wait_for(started.wait(), 1)
            async_unload_notify(hass, entry)
            with pytest.raises(asyncio.CancelledError):
                await task
            assert stopped.is_set()
            api.assert_awaited_once()
            assert not hass.services.has_service("notify", "bticino_c300x_first")
    asyncio.run(run())


def test_integration_setup_and_unload_wiring(tmp_path, monkeypatch):
    import custom_components.bticino_c300x as integration
    from custom_components.bticino_c300x import memory_diagnostics

    async def run():
        async with notify_context(tmp_path, monkeypatch, enabled=False) as (hass, entry):
            entry.options["device_ui_enabled"] = True
            manager = SimpleNamespace(async_prepare=AsyncMock(return_value=True), async_unload=AsyncMock(return_value=False))
            monkeypatch.setattr(integration, "C300XRuntimeManager", lambda *a: manager)
            monkeypatch.setattr(memory_diagnostics, "async_start_memory_diagnostics", lambda *a: None)
            assert await integration.async_setup_entry(hass, entry)
            await send(hass, entry)
            assert await integration.async_unload_entry(hass, entry) is False
            assert hass.services.has_service("notify", "bticino_c300x_first")
            manager.async_unload.return_value = True
            assert await integration.async_unload_entry(hass, entry)
            assert not hass.services.has_service("notify", "bticino_c300x_first")
    asyncio.run(run())


@pytest.mark.parametrize("failure", [RuntimeError("setup failed"), asyncio.CancelledError()])
def test_integration_setup_failure_leaves_no_notify_service(tmp_path, monkeypatch, failure):
    import custom_components.bticino_c300x as integration
    from custom_components.bticino_c300x import memory_diagnostics

    original = C300XNotificationService.async_register_services

    async def fail(self):
        await original(self)
        raise failure

    async def run():
        async with notify_context(tmp_path, monkeypatch, enabled=False) as (hass, entry):
            entry.options["device_ui_enabled"] = True
            entry.runtime_data.connection_state = SimpleNamespace(expire_unavailable=None)
            manager = SimpleNamespace(async_prepare=AsyncMock(return_value=True), async_unload=AsyncMock(return_value=False))
            monkeypatch.setattr(integration, "C300XRuntimeManager", lambda *a: manager)
            monkeypatch.setattr(memory_diagnostics, "async_start_memory_diagnostics", lambda *a: None)
            monkeypatch.setattr(C300XNotificationService, "async_register_services", fail)
            with pytest.raises(type(failure)):
                await integration.async_setup_entry(hass, entry)
            manager.async_unload.assert_awaited_once()
            assert not hass.services.has_service("notify", "bticino_c300x_first")
            assert "bticino_c300x_notify_services" not in hass.data
    asyncio.run(run())


def test_real_config_entry_unload_callbacks(tmp_path, monkeypatch):
    async def run():
        async with notify_context(tmp_path, monkeypatch, enabled=False) as (hass, fixture):
            entry = config_entries.ConfigEntry(
                version=1, minor_version=3, domain="bticino_c300x", title="Door",
                source="user", unique_id="notify-test", discovery_keys=MappingProxyType({}),
                subentries_data=None, options={"device_ui_enabled": True}, data={},
            )
            entry.runtime_data = fixture.runtime_data
            name = f"bticino_c300x_{entry.entry_id.lower()}"
            for _ in range(3):
                await async_setup_notify(hass, entry)
                assert hass.services.has_service("notify", name)
                await hass.services.async_call("notify", name, {"message": "Test"}, blocking=True)
                await entry._async_process_on_unload(hass)
                assert not hass.services.has_service("notify", name)
                assert "bticino_c300x_notify_services" not in hass.data
            entry.runtime_data.api.async_send_display_alert.assert_awaited()
            assert entry.runtime_data.api.async_send_display_alert.await_count == 3
    asyncio.run(run())
