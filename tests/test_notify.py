"""Real HA legacy notify service lifecycle and bounded native delivery."""

import asyncio
import json
import re
from contextlib import asynccontextmanager
from hashlib import sha256
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant import config_entries, loader
from homeassistant.components import notify as ha_notify
from homeassistant.components.http import HomeAssistantHTTP
from homeassistant.components.notify.legacy import NOTIFY_SERVICE_SCHEMA
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
    UnknownUser,
)
from homeassistant.helpers.service import async_get_all_descriptions

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


def entry_for(key="first", *, title="Front door", enabled=True, capability=True):
    callbacks = []
    listeners = []

    def add_update_listener(listener):
        listeners.append(listener)
        return lambda: listeners.remove(listener)

    return SimpleNamespace(
        entry_id=key, title=title, data={}, options={"device_ui_enabled": enabled},
        async_on_unload=callbacks.append, unload_callbacks=callbacks,
        add_update_listener=add_update_listener, update_listeners=listeners,
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
    # Notify metadata needs its real feature enum, not optional AI dependencies.
    monkeypatch.setattr("homeassistant.helpers.service._base_components", lambda: {"notify": ha_notify})
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
        "notify", service_name(hass, entry),
        {"message": "Test message", **kwargs}, blocking=True,
    )


def service_name(hass, entry):
    return hass.data["bticino_c300x_notify_services"][entry.entry_id].name


@pytest.mark.parametrize("title,expected", [
    ("BTicino C300X", "bticino_c300x"),
    ("", "bticino_c300x"),
    ("   ", "bticino_c300x"),
    ("Front door", "bticino_c300x_front_door"),
])
def test_readable_action_id_without_legacy_alias(tmp_path, monkeypatch, title, expected):
    async def run():
        async with notify_context(tmp_path, monkeypatch, title=title) as (hass, entry):
            assert service_name(hass, entry) == expected
            assert not hass.services.has_service("notify", "bticino_c300x_first")
            await send(hass, entry)
            entry.runtime_data.api.async_send_display_alert.assert_awaited_once()
    asyncio.run(run())


def test_name_reservations_survive_unload_and_reverse_startup_order(tmp_path, monkeypatch):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, first):
            first_name = service_name(hass, first)
            async_unload_notify(hass, first)
            second = entry_for("second", title=first.title)
            try:
                await async_setup_notify(hass, second)
                second_name = service_name(hass, second)
                assert first_name != second_name
                assert not hass.services.has_service("notify", first_name)
                await async_setup_notify(hass, first)
                assert service_name(hass, first) == first_name
            finally:
                async_unload_notify(hass, second)
                second.runtime_data.resources.close()
        # New HA instance reads the on-disk reservations, in reversed setup order.
        async with notify_context(tmp_path, monkeypatch, key="second") as (hass, second):
            first = entry_for("first", title="Renamed door")
            try:
                assert service_name(hass, second) == second_name
                assert not hass.services.has_service("notify", first_name)
                await async_setup_notify(hass, first)
                assert service_name(hass, first) == first_name
                for entry in (first, second):
                    await send(hass, entry)
                    entry.runtime_data.api.async_send_display_alert.assert_awaited_once()
            finally:
                async_unload_notify(hass, first)
                first.runtime_data.resources.close()
    asyncio.run(run())


def test_concurrent_entry_setups_reserve_distinct_names(tmp_path, monkeypatch):
    async def run():
        async with notify_context(tmp_path, monkeypatch, enabled=False) as (hass, first):
            first.options["device_ui_enabled"] = True
            second = entry_for("second")
            try:
                await asyncio.gather(
                    async_setup_notify(hass, first), async_setup_notify(hass, second),
                    async_setup_notify(hass, first),
                )
                assert service_name(hass, first) != service_name(hass, second)
                assert len(first.unload_callbacks) == len(second.unload_callbacks) == 1
                for entry in (first, second):
                    await send(hass, entry)
                    entry.runtime_data.api.async_send_display_alert.assert_awaited_once()
            finally:
                async_unload_notify(hass, second)
                second.runtime_data.resources.close()
    asyncio.run(run())


@pytest.mark.parametrize("when", ["before_setup", "during_setup", "before_unload"])
def test_name_collision_never_overwrites_or_removes_unrelated_service(tmp_path, monkeypatch, when):
    async def run():
        async with notify_context(tmp_path, monkeypatch, enabled=False) as (hass, entry):
            entry.options["device_ui_enabled"] = True
            name = "bticino_c300x_front_door"
            other = AsyncMock()
            original = C300XNotificationService.async_setup

            async def setup(self, *args):
                await original(self, *args)
                hass.services.async_register("notify", name, other)

            if when == "before_setup":
                hass.services.async_register("notify", name, other)
            elif when == "during_setup":
                monkeypatch.setattr(C300XNotificationService, "async_setup", setup)
            if when == "before_unload":
                await async_setup_notify(hass, entry)
                hass.services.async_register("notify", name, other)
            else:
                with pytest.raises(ServiceValidationError, match="already exists"):
                    await async_setup_notify(hass, entry)
            async_unload_notify(hass, entry)
            await hass.services.async_call("notify", name, {"message": "Other"}, blocking=True)
            other.assert_awaited_once()
            entry.runtime_data.api.async_send_display_alert.assert_not_awaited()
            hass.services.async_remove("notify", name)
    asyncio.run(run())


@pytest.mark.parametrize("failure", [OSError("disk full"), asyncio.CancelledError()])
def test_name_save_failure_registers_nothing_and_retries_reservation(tmp_path, monkeypatch, failure):
    from custom_components.bticino_c300x.notify_names import notify_names

    async def run():
        async with notify_context(tmp_path, monkeypatch, enabled=False) as (hass, entry):
            entry.options["device_ui_enabled"] = True
            names = notify_names(hass)
            with monkeypatch.context() as patch:
                patch.setattr(names._store, "async_save", AsyncMock(side_effect=failure))
                with pytest.raises(type(failure)):
                    await async_setup_notify(hass, entry)
            assert not hass.services.has_service("notify", "bticino_c300x_front_door")
            assert not entry.unload_callbacks
            second = entry_for("second")
            try:
                await async_setup_notify(hass, second)
                assert service_name(hass, second) != "bticino_c300x_front_door"
                await async_setup_notify(hass, entry)
                assert service_name(hass, entry) == "bticino_c300x_front_door"
            finally:
                async_unload_notify(hass, second)
                second.runtime_data.resources.close()
    asyncio.run(run())


@pytest.mark.parametrize("stored", [
    [], "bad", {"first": None}, {"first": "other_action"},
    {"first": "bticino_c300x_Bad"}, {"first": "bticino_c300x_bad/name"},
    {"first": "bticino_c300x", "second": "bticino_c300x"},
])
def test_malformed_name_store_fails_without_registration(tmp_path, monkeypatch, stored):
    from custom_components.bticino_c300x.notify_names import notify_names

    async def run():
        async with notify_context(tmp_path, monkeypatch, enabled=False) as (hass, entry):
            entry.options["device_ui_enabled"] = True
            names = notify_names(hass)
            await names._store.async_save(stored)
            with pytest.raises(ServiceValidationError, match="Invalid C300X"):
                await async_setup_notify(hass, entry)
            assert "bticino_c300x_notify_services" not in hass.data
            assert not entry.unload_callbacks
            assert not entry.update_listeners
    asyncio.run(run())


def test_foreign_default_service_does_not_create_reservation(tmp_path, monkeypatch):
    from custom_components.bticino_c300x.notify_names import notify_names

    async def run():
        async with notify_context(tmp_path, monkeypatch, enabled=False, title="BTicino C300X") as (hass, entry):
            entry.options["device_ui_enabled"] = True
            other = AsyncMock()
            hass.services.async_register("notify", "bticino_c300x", other)
            with pytest.raises(ServiceValidationError, match="already exists"):
                await async_setup_notify(hass, entry)
            assert await notify_names(hass)._store.async_load() is None
            await hass.services.async_call("notify", "bticino_c300x", {}, blocking=True)
            other.assert_awaited_once()
            hass.services.async_remove("notify", "bticino_c300x")
            await async_setup_notify(hass, entry)
            assert service_name(hass, entry) == "bticino_c300x"
    asyncio.run(run())


def test_permanent_removal_frees_only_deleted_entry_name(tmp_path, monkeypatch):
    from custom_components.bticino_c300x import async_remove_entry

    async def run():
        async with notify_context(tmp_path, monkeypatch, title="BTicino C300X") as (hass, first):
            first.runtime_data.connection_state = SimpleNamespace(expire_unavailable=lambda: None)
            second = entry_for("second")
            try:
                await async_setup_notify(hass, second)
                async_unload_notify(hass, first)
                await async_remove_entry(hass, first)
                await async_remove_entry(hass, first)
                assert service_name(hass, second) == "bticino_c300x_front_door"
                await send(hass, second)
            finally:
                async_unload_notify(hass, second)
                second.runtime_data.resources.close()
        async with notify_context(tmp_path, monkeypatch, key="replacement", title="BTicino C300X") as (hass, entry):
            assert service_name(hass, entry) == "bticino_c300x"
            await send(hass, entry)
    asyncio.run(run())


def test_live_title_edit_refreshes_label_without_renaming_action(tmp_path, monkeypatch):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, entry):
            name = service_name(hass, entry)
            assert len(entry.update_listeners) == 1
            listener = entry.update_listeners[0]
            entry.title = "Renamed entrance"
            await listener(hass, entry)
            metadata = (await async_get_all_descriptions(hass))["notify"][name]
            assert metadata["name"] == "Send a display notification to Renamed entrance"
            assert service_name(hass, entry) == "bticino_c300x_front_door"
            assert not hass.services.has_service("notify", "bticino_c300x_renamed_entrance")
            async_unload_notify(hass, entry)
            assert not entry.update_listeners
            await listener(hass, entry)
            assert not hass.services.has_service("notify", name)
    asyncio.run(run())


@pytest.mark.parametrize("title,display_title", [
    ("Front door", "Front door"),
    ("  Renamed entrance  ", "Renamed entrance"),
    ("", "BTicino C300X"),
    ("  ", "BTicino C300X"),
    ('<img src=x onerror="alert(1)"> & Door', '<img src=x onerror="alert(1)"> & Door'),
])
def test_notify_metadata_uses_plain_entry_title_and_preserves_schema(
    tmp_path, monkeypatch, title, display_title,
):
    async def run():
        async with notify_context(tmp_path, monkeypatch, title=title) as (hass, entry):
            name = service_name(hass, entry)
            service = hass.data["bticino_c300x_notify_services"][entry.entry_id]
            metadata = (await async_get_all_descriptions(hass))["notify"][name]
            assert metadata["name"] == f"Send a display notification to {display_title}"
            assert name not in metadata["name"] + metadata["description"]
            assert "BTicino C300X display" in metadata["description"]
            assert "30 seconds" in metadata["description"]
            assert "<img" not in metadata["description"]
            assert "target" not in metadata
            fields = metadata["fields"]
            assert set(fields) == {"message", "title", "data"}
            original = service.services_dict["notify"]["fields"]
            assert "target" in original
            for field in ("message", "title"):
                assert fields[field] == original[field]
                assert fields[field] is not original[field]
            assert fields["data"]["selector"] == original["data"]["selector"]
            assert fields["data"]["example"] != original["data"]["example"]
            hints = fields["data"]["description"]
            for hint in ("severity", "info (default)", "warning", "error", "wake_duration",
                         "sound_duration", "0 to 300", "default to 30", "0 disables",
                         "expires_in", "604800", "3600", "notification_id"):
                assert hint in hints
            assert hass.services.async_services()["notify"][name].schema is NOTIFY_SERVICE_SCHEMA
            assert service.targets is None
            assert service.registered_targets == {}
            await send(hass, entry, data=fields["data"]["example"])
            entry.runtime_data.api.async_send_display_alert.assert_awaited_once()
    asyncio.run(run())


def test_notify_metadata_duplicate_titles_rename_and_reload_keep_service_ids(tmp_path, monkeypatch):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, first):
            second = entry_for("second", title=first.title)
            try:
                await async_setup_notify(hass, second)
                descriptions = (await async_get_all_descriptions(hass))["notify"]
                first_name, second_name = service_name(hass, first), service_name(hass, second)
                assert first_name == "bticino_c300x_front_door"
                assert second_name == f"bticino_c300x_front_door_{sha256(b'second').hexdigest()[:8]}"
                assert descriptions[first_name] == descriptions[second_name]
                first.title = "Garden entrance"
                async_unload_notify(hass, first)
                descriptions = (await async_get_all_descriptions(hass))["notify"]
                assert first_name not in descriptions
                assert second_name in descriptions
                await async_setup_notify(hass, first)
                await async_setup_notify(hass, first)
                descriptions = (await async_get_all_descriptions(hass))["notify"]
                assert descriptions[first_name]["name"] == "Send a display notification to Garden entrance"
                assert descriptions[second_name]["name"] == "Send a display notification to Front door"
                assert {name for name in descriptions if name.startswith("bticino_c300x_")} == {first_name, second_name}
                await send(hass, first)
                await send(hass, second)
                for entry in (first, second):
                    entry.runtime_data.api.async_send_display_alert.assert_awaited_once()
            finally:
                async_unload_notify(hass, second)
                second.runtime_data.resources.close()
    asyncio.run(run())


def test_notify_metadata_failure_rolls_back_registration(tmp_path, monkeypatch):
    from custom_components.bticino_c300x import notify

    def fail(*args):
        raise RuntimeError("metadata failed")

    async def run():
        async with notify_context(tmp_path, monkeypatch, enabled=False) as (hass, entry):
            entry.options["device_ui_enabled"] = True
            with monkeypatch.context() as patch:
                patch.setattr(notify, "async_set_service_schema", fail)
                with pytest.raises(RuntimeError, match="metadata failed"):
                    await async_setup_notify(hass, entry)
            assert not hass.services.has_service("notify", "bticino_c300x_front_door")
            assert "bticino_c300x_notify_services" not in hass.data
            assert not entry.unload_callbacks
            await async_setup_notify(hass, entry)
            metadata = (await async_get_all_descriptions(hass))["notify"]["bticino_c300x_front_door"]
            assert metadata["name"] == "Send a display notification to Front door"
    asyncio.run(run())


@pytest.mark.parametrize("caller", ["reader", "controller", "unknown"])
def test_notify_rejects_unprivileged_callers_before_storage_or_delivery(
    tmp_path, monkeypatch, caller,
):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, entry):
            user = None if caller == "unknown" else SimpleNamespace(
                is_admin=False,
                permissions=SimpleNamespace(check_entity=lambda *_: caller == "controller"),
            )
            hass.auth = SimpleNamespace(async_get_user=AsyncMock(return_value=user))
            with pytest.raises(UnknownUser if caller == "unknown" else Unauthorized):
                await hass.services.async_call(
                    "notify", service_name(hass, entry),
                    {"message": "Test", "data": {
                        "severity": "error", "sound_duration": 300, "wake_duration": 300,
                    }},
                    blocking=True, context=Context(user_id=caller),
                )
            hass.auth.async_get_user.assert_awaited_once_with(caller)
            assert entry.runtime_data.display_notifications is None
            entry.runtime_data.api.async_send_display_alert.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("user_id", [None, "admin"])
def test_notify_preserves_admin_and_context_free_automation_access(
    tmp_path, monkeypatch, user_id,
):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, entry):
            hass.auth = SimpleNamespace(
                async_get_user=AsyncMock(return_value=SimpleNamespace(is_admin=True)),
            )
            await hass.services.async_call(
                "notify", service_name(hass, entry),
                {"message": "Test", "data": {"severity": "warning"}},
                blocking=True, context=Context(user_id=user_id),
            )
            entry.runtime_data.api.async_send_display_alert.assert_awaited_once()
            assert len(notification_payload(entry)) == 1
            if user_id is None:
                hass.auth.async_get_user.assert_not_awaited()
            else:
                hass.auth.async_get_user.assert_awaited_once_with(user_id)
    asyncio.run(run())


@pytest.mark.parametrize("severity,sound,priority", [("info", 30, "normal"), ("warning", 30, "important"), ("error", 30, "urgent")])
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
            assert hass.services.has_service("notify", "bticino_c300x_front_door")
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
            second = entry_for("second", title="Back door")
            disabled = entry_for("disabled", title="Disabled", enabled=False)
            await async_setup_notify(hass, second)
            await async_setup_notify(hass, disabled)
            await async_setup_notify(hass, first)
            assert len(first.unload_callbacks) == 1
            assert not hass.services.has_service("notify", "bticino_c300x_disabled")
            for callback in first.unload_callbacks:
                callback()
            assert not hass.services.has_service("notify", "bticino_c300x_front_door")
            assert hass.services.has_service("notify", "bticino_c300x_back_door")
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
            assert not hass.services.has_service("notify", "bticino_c300x_front_door")
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
            assert not hass.services.has_service("notify", "bticino_c300x_front_door")
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
            assert hass.services.has_service("notify", "bticino_c300x_front_door")
            manager.async_unload.return_value = True
            assert await integration.async_unload_entry(hass, entry)
            assert not hass.services.has_service("notify", "bticino_c300x_front_door")
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
            assert not hass.services.has_service("notify", "bticino_c300x_front_door")
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
            name = "bticino_c300x_door"
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


@asynccontextmanager
async def speech_context(
    tmp_path, monkeypatch, *, announcements=True, speaker="media_player.front_door_speaker",
    speaker_state="idle",
):
    """Notify with a speaker entity, a text-to-speech stand-in and a recording player."""

    from custom_components.bticino_c300x import notify_speech
    from tests.test_config_flow_speech import use_tts_stand_in

    spoken = []

    def generate(hass, message, engine=None, language=None):
        if engine == "tts.missing":
            raise HomeAssistantError("Invalid TTS provider selected")
        return f"media-source://tts/{engine or 'default'}?message={message}&language={language}"

    use_tts_stand_in(monkeypatch, generate)
    monkeypatch.setattr(notify_speech.er, "async_get", lambda _hass: SimpleNamespace(
        async_get_entity_id=lambda domain, platform, unique_id: speaker))
    async with notify_context(tmp_path, monkeypatch) as (hass, entry):
        entry.runtime_data.capabilities["announcements"] = {"supported": announcements}
        if speaker is not None:
            hass.states.async_set(speaker, speaker_state)

        async def play(call):
            spoken.append(dict(call.data))

        hass.services.async_register("media_player", "play_media", play)
        yield hass, entry, spoken


def test_default_mode_shows_the_message_and_speaks_nothing(tmp_path, monkeypatch):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            await send(hass, entry)
            assert entry.runtime_data.api.async_send_display_alert.await_count == 1
            assert spoken == []
    asyncio.run(run())


def test_speech_mode_only_speaks_the_message(tmp_path, monkeypatch):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            await send(hass, entry, title="Not spoken",
                       data={"mode": "speech", "tts_engine": "tts.piper", "language": "de"})
            assert spoken == [{
                "entity_id": "media_player.front_door_speaker",
                # As the engine names the language.
                "media_content_id": "media-source://tts/tts.piper?message=Test message&language=de_DE",
                "media_content_type": "music", "announce": True,
            }]
            entry.runtime_data.api.async_send_display_alert.assert_not_awaited()
            assert notification_payload(entry) == []
    asyncio.run(run())


def test_both_mode_shows_the_message_without_tone_and_speaks_it(tmp_path, monkeypatch):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            await send(hass, entry, data={"mode": "both"})
            alert = entry.runtime_data.api.async_send_display_alert.call_args.args[0]
            assert (alert["message"], alert["sound_duration"], alert["wake_duration"]) == ("Test message", 0, 30)
            assert [item["media_content_id"] for item in spoken] == [
                "media-source://tts/default?message=Test message&language=None"]
            # The tone would hold the speaker the speech needs.
            with pytest.raises(ServiceValidationError, match="leave out sound_duration"):
                await send(hass, entry, data={"mode": "both", "sound_duration": 5})
            assert entry.runtime_data.api.async_send_display_alert.await_count == 1
            await send(hass, entry, data={"mode": "both", "sound_duration": 0})
            assert entry.runtime_data.api.async_send_display_alert.call_args.args[0]["sound_duration"] == 0
    asyncio.run(run())


@pytest.mark.parametrize("options", [
    {"announcements": False}, {"speaker": None}, {"speaker_state": "unavailable"},
], ids=["old agent", "no speaker entity", "speaker unavailable"])
@pytest.mark.parametrize("mode", ["speech", "both"])
def test_nothing_is_shown_when_the_message_cannot_be_spoken(tmp_path, monkeypatch, options, mode):
    async def run():
        async with speech_context(tmp_path, monkeypatch, **options) as (hass, entry, spoken):
            with pytest.raises(ServiceValidationError, match="agent|speaker"):
                await send(hass, entry, data={"mode": mode})
            entry.runtime_data.api.async_send_display_alert.assert_not_awaited()
            assert notification_payload(entry) == [] and spoken == []
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["speech", "both"])
def test_missing_text_to_speech_engine_is_named_and_nothing_is_shown(tmp_path, monkeypatch, mode):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            with pytest.raises(ServiceValidationError, match="text-to-speech engine"):
                await send(hass, entry, data={"mode": mode, "tts_engine": "tts.missing"})
            entry.runtime_data.api.async_send_display_alert.assert_not_awaited()
            assert notification_payload(entry) == [] and spoken == []
    asyncio.run(run())


def test_both_mode_still_speaks_when_the_display_did_not_confirm(tmp_path, monkeypatch):
    from custom_components.bticino_c300x.api_errors import C300XAgentApiError

    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            entry.runtime_data.api.async_send_display_alert.side_effect = C300XAgentApiError("lost")
            with pytest.raises(HomeAssistantError, match="not confirmed"):
                await send(hass, entry, data={"mode": "both"})
            assert len(spoken) == 1
    asyncio.run(run())


def test_a_named_engine_does_not_take_the_language_saved_for_another(tmp_path, monkeypatch):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            entry.options = {**entry.options, "tts_engine": "tts.piper", "tts_language": "de_DE"}
            await send(hass, entry, data={"mode": "speech", "tts_engine": "tts.cloud"})
            assert [item["media_content_id"] for item in spoken] == [
                "media-source://tts/tts.cloud?message=Test message&language=None"]
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["speech", "both"])
def test_a_language_the_engine_cannot_speak_is_named_and_nothing_is_shown(tmp_path, monkeypatch, mode):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            with pytest.raises(ServiceValidationError, match="cannot speak the language 'fr'"):
                await send(hass, entry, data={"mode": mode, "tts_engine": "tts.piper", "language": "fr"})
            entry.runtime_data.api.async_send_display_alert.assert_not_awaited()
            assert notification_payload(entry) == [] and spoken == []
    asyncio.run(run())


@pytest.mark.parametrize("bad", [
    {"mode": "loud"}, {"mode": True}, {"mode": "speech", "tts_engine": ""},
    {"mode": "speech", "language": 5}, {"mode": "speech", "volume": 50},
])
def test_invalid_speech_data_has_no_effect(tmp_path, monkeypatch, bad):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            with pytest.raises(ServiceValidationError, match="Invalid C300X display notification"):
                await send(hass, entry, data=bad)
            entry.runtime_data.api.async_send_display_alert.assert_not_awaited()
            assert notification_payload(entry) == [] and spoken == []
    asyncio.run(run())


def test_spoken_notification_uses_the_engine_and_language_of_the_settings(tmp_path, monkeypatch):
    async def run():
        async with speech_context(tmp_path, monkeypatch) as (hass, entry, spoken):
            entry.options = {**entry.options, "tts_engine": "tts.piper", "tts_language": "de"}
            await send(hass, entry, data={"mode": "speech"})
            # What the call names comes before the settings.
            await send(hass, entry, data={"mode": "speech", "tts_engine": "tts.cloud", "language": "en"})
            assert [item["media_content_id"] for item in spoken] == [
                "media-source://tts/tts.piper?message=Test message&language=de_DE",
                "media-source://tts/tts.cloud?message=Test message&language=en-US",
            ]
    asyncio.run(run())

