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
    assert store.payload()[0]["revision"] == 2
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
        json.dumps({"revision": 1, "action_id": "delete"}),
    ):
        with pytest.raises(ValueError):
            asyncio.run(async_notification_action(hass, entry, "notice", invalid))
    show_notification(hass, entry, data(title="Replaced"))
    with pytest.raises(ValueError, match="stale"):
        asyncio.run(async_notification_action(hass, entry, "notice", option))
    option = json.dumps({"revision": 2, "action_id": None})
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
        option = json.dumps({"revision": 1, "action_id": "porch"})
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
