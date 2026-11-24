"""Transient notification lifetime, input bounds and action authorization."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.bticino_c300x import runtime_manager
from custom_components.bticino_c300x.data import C300XRuntimeResources
from custom_components.bticino_c300x.display_notifications import (
    MAX_NOTIFICATIONS,
    SHOW_SCHEMA,
    DisplayNotifications,
    async_notification_action,
    notification_payload,
    notifications_for_entry,
    show_notification,
)
from custom_components.bticino_c300x.executor import async_execute_dashboard_action
from custom_components.bticino_c300x.schema_compat import vol


class Loop:
    now = 100.0

    def time(self):
        return self.now

    def call_at(self, deadline, fn):
        handle = SimpleNamespace(deadline=deadline, fn=fn, cancelled=False)
        handle.cancel = lambda: setattr(handle, "cancelled", True)
        return handle


def data(key="notice", **kwargs):
    return SHOW_SCHEMA(
        {"notification_id": key, "title": "Notice", "message": "Text", **kwargs}
    )


def test_expiry_replacement_bound_and_cleanup():
    loop, changes = Loop(), []
    store = DisplayNotifications(loop, lambda: changes.append(1))
    store.show(data(expires_in=10))
    old_timer = store._expiry
    store.show(data(title="New", expires_in=20))
    assert old_timer.cancelled
    assert len(store.payload()) == 1
    assert store._items["notice"]["sequence"] == 2
    for index in range(MAX_NOTIFICATIONS):
        store.show(data(str(index)))
    assert len(store.payload()) == MAX_NOTIFICATIONS
    assert not any(item["id"] == "notice" for item in store.payload())
    store.show(data("urgent", priority="urgent", expires_in=2))
    assert store.payload()[0]["id"] == "urgent"
    loop.now += 3
    store._expiry.fn()
    assert not any(item["id"] == "urgent" for item in store.payload())
    assert store._expiry.deadline > loop.now
    store.dismiss("0")
    before = len(changes)
    store.dismiss("nonexistent")
    assert len(changes) == before
    timer = store._expiry
    store.close()
    assert timer.cancelled
    assert store.payload() == []
    with pytest.raises(ValueError):
        store.show(data())


def test_low_priority_cannot_evict_high_priority():
    store = DisplayNotifications(Loop(), lambda: None)
    for index in range(MAX_NOTIFICATIONS):
        store.show(data(str(index), priority="urgent"))
    with pytest.raises(ValueError, match="queue_full"):
        store.show(data())


def test_unread_events_follow_store_without_listeners_or_read_feedback():
    async def run():
        events, jobs = [], []
        api = SimpleNamespace(async_notify_display_bridge_event=AsyncMock(
            side_effect=lambda topic, *, unread: events.append((topic, unread)),
        ))
        hass = SimpleNamespace(loop=Loop(), add_job=lambda *args: jobs.append(args))
        entry = SimpleNamespace(
            entry_id="front", data={}, options={"device_ui_enabled": True},
            runtime_data=SimpleNamespace(api=api, capabilities={}, resources=C300XRuntimeResources()),
        )

        async def deliver():
            (job, *args), = jobs
            jobs.clear()
            await job(*args)
            assert not jobs

        await runtime_manager._async_notify_display_configuration(entry, api)
        store = notifications_for_entry(hass, entry)
        store.show(data("a"))
        store.show(data("b", expires_in=3))
        await deliver()
        store.dismiss("a")
        await deliver()
        hass.loop.now += 3
        assert not store.has_unread() and not jobs
        store._expiry.fn()
        await deliver()
        store.show(data("c"))
        await deliver()
        store.dismiss("c")
        await deliver()
        assert events == [
            ("display_bridge.state", False), ("notifications", True),
            ("notifications", True), ("notifications", False),
            ("notifications", True), ("notifications", False),
        ]
        store.close()

    asyncio.run(run())


def test_only_led_notices_count_as_unread_and_replacement_updates_it():
    loop, changes = Loop(), []
    store = DisplayNotifications(loop, lambda: changes.append(1))
    store.show(data("quiet"), led=False)
    assert not store.has_unread() and changes == [1]
    assert set(store.payload()[0]) == {
        "id", "revision", "title", "message", "icon", "priority", "actions",
    }
    store.show(data("quiet"), led=True)
    assert store.has_unread()
    store.show(data("quiet"), led=False)
    assert not store.has_unread()
    # Without the keyword a notice counts, as every notice did before.
    store.show(data("lit", expires_in=5))
    assert store.has_unread()
    loop.now += 5
    assert not store.has_unread()
    store.close()


def test_reload_snapshot_follows_inflight_notification():
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        events = []

        async def post(topic, *, unread):
            if topic == "notifications":
                started.set()
                await release.wait()
            events.append((topic, unread))

        api = SimpleNamespace(async_notify_display_bridge_event=post)
        old = SimpleNamespace(api=api, capabilities={"memo_led": True}, display_bridge_notify_messages=True,
                              display_notifications=SimpleNamespace(has_unread=lambda: True))
        entry = SimpleNamespace(entry_id="front", runtime_data=old)
        sending = asyncio.create_task(
            runtime_manager._async_notify_display_bridge_alarm_if_listening(None, entry, old)
        )
        await asyncio.wait_for(started.wait(), 2)
        entry.runtime_data = SimpleNamespace(api=api)
        reloading = asyncio.create_task(runtime_manager._async_notify_display_configuration(entry, api))
        await asyncio.sleep(0)
        assert not events
        release.set()
        await asyncio.gather(sending, reloading)
        assert events == [("notifications", True), ("display_bridge.state", False)]

    asyncio.run(run())


def test_unicode_payload_is_bounded_for_native_bridge():
    from custom_components.bticino_c300x.display_notifications import (
        MAX_NOTIFICATION_BYTES,
    )

    store = DisplayNotifications(Loop(), lambda: None)
    for index in range(MAX_NOTIFICATIONS):
        store.show(data(str(index), message="\U0001f4c5" * 500))
    assert len(store.payload()) < MAX_NOTIFICATIONS
    assert len(json.dumps(store.payload())) < MAX_NOTIFICATION_BYTES


@pytest.mark.parametrize(
    "extra",
    [
        {"notification_id": "../bad"},
        {"notification_id": "x" * 65},
        {"title": ""},
        {"title": "x" * 81},
        {"message": "x" * 501},
        {"icon": "https://host/a"},
        {"priority": "critical"},
        {"expires_in": 0},
        {"expires_in": 604801},
        {"actions": [{"action_id": "x", "label": "x"}] * 3},
        {"actions": [{"service": "light.turn_on", "label": "x"}]},
    ],
)
def test_invalid_inputs_rejected(extra):
    with pytest.raises(vol.Invalid):
        data(**extra)


@pytest.fixture
def context(monkeypatch):
    calls = []
    monkeypatch.setattr(
        runtime_manager,
        "_async_schedule_display_bridge_notify",
        lambda *_, **kw: calls.append(kw),
    )
    hass = SimpleNamespace(
        loop=Loop(),
        services=SimpleNamespace(async_call=AsyncMock()),
        bus=SimpleNamespace(async_fire=lambda *_: None),
    )
    entry = SimpleNamespace(
        entry_id="entry",
        data={},
        options={
            "device_ui_enabled": True,
            "actions": {
                "porch": {
                    "domain": "light",
                    "service": "toggle",
                    "target": {"entity_id": "light.porch"},
                }
            },
        },
        runtime_data=SimpleNamespace(
            display_notifications=None, resources=C300XRuntimeResources()
        ),
    )
    return hass, entry, calls


def test_action_allowlist_replacement_replay_and_dismiss(context):
    hass, entry, calls = context
    show_notification(
        hass, entry, data(actions=[{"action_id": "porch", "label": "Porch"}])
    )
    assert calls == [{"notifications": True}]
    payload = notification_payload(entry)[0]
    option = json.dumps({"revision": payload["revision"], "action_id": "porch"})
    asyncio.run(
        async_execute_dashboard_action(
            hass, entry, "notification.notice", option=option
        )
    )
    hass.services.async_call.assert_awaited_once()
    for invalid in (
        "",
        "null",
        "[]",
        "{}",
        json.dumps({"revision": payload["revision"], "action_id": "delete"}),
        json.dumps({"revision": True, "action_id": None}),
        json.dumps({"revision": 1, "service": "delete"}),
    ):
        with pytest.raises(ValueError):
            asyncio.run(async_notification_action(hass, entry, "notice", invalid))
    show_notification(hass, entry, data(title="Replaced"))
    with pytest.raises(ValueError, match="stale"):
        asyncio.run(async_notification_action(hass, entry, "notice", option))
    option = json.dumps(
        {"revision": notification_payload(entry)[0]["revision"], "action_id": None}
    )
    asyncio.run(async_notification_action(hass, entry, "notice", option))
    assert notification_payload(entry) == []
    assert hass.services.async_call.await_count == 1
    store = notifications_for_entry(hass, entry)
    entry.runtime_data.resources.close()
    assert store.closed


def test_disabled_and_unknown_actions_fail_without_side_effects(context):
    hass, entry, calls = context
    with pytest.raises(ValueError, match="unknown_notification_action"):
        show_notification(
            hass, entry, data(actions=[{"action_id": "missing", "label": "X"}])
        )
    assert notification_payload(entry) == []
    entry.options["device_ui_enabled"] = False
    with pytest.raises(ValueError, match="display_disabled"):
        show_notification(hass, entry, data())
    assert not calls


def test_old_display_cannot_dismiss_a_new_message_after_ha_reload(context):
    hass, entry, _ = context
    show_notification(hass, entry, data())
    old_revision = notification_payload(entry)[0]["revision"]
    entry.runtime_data.resources.close()
    entry.runtime_data.display_notifications = None
    show_notification(hass, entry, data())
    with pytest.raises(ValueError, match="stale_notification"):
        asyncio.run(
            async_notification_action(
                hass,
                entry,
                "notice",
                json.dumps({"revision": old_revision, "action_id": None}),
            )
        )
    assert len(notification_payload(entry)) == 1


def test_registered_service_handlers_show_dismiss_and_reject_unknown_actions(
    context, monkeypatch
):
    from homeassistant.exceptions import ServiceValidationError

    from custom_components.bticino_c300x import services

    async def run():
        hass, entry, _ = context
        monkeypatch.setattr(services, "_entry_for_call", lambda *_: entry)
        handlers = services._C300XServiceHandlers(hass)
        await handlers.async_show_display_notification(SimpleNamespace(data=data()))
        assert len(notification_payload(entry)) == 1
        await handlers.async_dismiss_display_notification(
            SimpleNamespace(data={"notification_id": "notice"})
        )
        assert notification_payload(entry) == []
        with pytest.raises(ServiceValidationError) as err:
            await handlers.async_show_display_notification(
                SimpleNamespace(
                    data=data(actions=[{"action_id": "missing", "label": "X"}])
                )
            )
        assert err.value.translation_key == "unknown_notification_action"
        for index in range(MAX_NOTIFICATIONS):
            await handlers.async_show_display_notification(
                SimpleNamespace(data=data(str(index), priority="urgent"))
            )
        with pytest.raises(ServiceValidationError) as err:
            await handlers.async_show_display_notification(SimpleNamespace(data=data()))
        assert err.value.translation_key == "display_notification_queue_full"
        entry.runtime_data.display_notifications.close()
        with pytest.raises(ServiceValidationError) as err:
            await handlers.async_show_display_notification(SimpleNamespace(data=data()))
        assert err.value.translation_key == "display_notifications_unloaded"
        entry.options["device_ui_enabled"] = False
        with pytest.raises(ServiceValidationError) as err:
            await handlers.async_dismiss_display_notification(
                SimpleNamespace(data={"notification_id": "notice"})
            )
        assert err.value.translation_key == "display_disabled"

    asyncio.run(run())


def test_notify_display_alert_reports_a_refusal_as_a_translated_error(context):
    from homeassistant.exceptions import ServiceValidationError

    from custom_components.bticino_c300x.display_alerts import async_send_display_alert

    hass, entry, _ = context
    entry.runtime_data.capabilities = {"display_alerts": True, "memo_led": True}
    notifications_for_entry(hass, entry).close()
    with pytest.raises(ServiceValidationError) as err:
        asyncio.run(async_send_display_alert(hass, entry, "Door open"))
    assert err.value.translation_key == "display_notifications_unloaded"


def test_concurrent_action_is_single_flight(context):
    async def run():
        hass, entry, _ = context
        started, release = asyncio.Event(), asyncio.Event()

        async def command(*_, **__):
            started.set()
            await release.wait()

        hass.services.async_call.side_effect = command
        show_notification(
            hass, entry, data(actions=[{"action_id": "porch", "label": "Porch"}])
        )
        option = json.dumps(
            {
                "revision": notification_payload(entry)[0]["revision"],
                "action_id": "porch",
            }
        )
        pending = asyncio.create_task(
            async_notification_action(hass, entry, "notice", option)
        )
        try:
            await asyncio.wait_for(started.wait(), 1)
            with pytest.raises(ValueError, match="pending"):
                await async_notification_action(hass, entry, "notice", option)
        finally:
            release.set()
            await pending
        assert not entry.runtime_data.display_notifications.busy

    asyncio.run(run())
