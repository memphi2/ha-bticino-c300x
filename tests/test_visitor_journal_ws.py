"""Journal subscriptions use the HTTP camera read policy on every signal."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.config_entries import ConfigEntryState
from test_stream_snapshot_http import Request, setup

from custom_components.bticino_c300x.const import DOMAIN
from custom_components.bticino_c300x.media import async_setup_media_view
from custom_components.bticino_c300x.schema_compat import vol
from custom_components.bticino_c300x.visitor_journal import EVENT_JOURNAL_CHANGED
from custom_components.bticino_c300x.visitor_journal_ws import (
    SUBSCRIBE_TYPE,
    subscribe_journal,
)


def subscription_fixture(tmp_path, monkeypatch):
    manager, registered, _ = setup(tmp_path, monkeypatch)
    manager.journal = SimpleNamespace(closed=False)
    manager.entry.state = ConfigEntryState.LOADED
    state_listeners, bus_listeners = [], []

    def on_state_change(callback):
        state_listeners.append(callback)
        return lambda: state_listeners.remove(callback)

    def listen(event_type, callback):
        assert event_type == EVENT_JOURNAL_CHANGED
        bus_listeners.append(callback)
        return lambda: bus_listeners.remove(callback)

    manager.entry.async_on_state_change = on_state_change
    manager.hass.bus = SimpleNamespace(async_listen=listen)
    manager.hass.loop = asyncio.get_running_loop()
    connection = SimpleNamespace(user=Request(manager)["hass_user"], subscriptions={},
                                 send_result=Mock(), send_error=Mock(), send_message=Mock())

    def emit(entry_id="one"):
        for callback in list(bus_listeners):
            callback(SimpleNamespace(data={"entry_id": entry_id, "visits": ["private"], "path": "secret"}))

    return manager, registered, connection, bus_listeners, state_listeners, emit


def test_non_admin_reader_gets_only_entry_scoped_refresh_and_disconnect_cleans_up(tmp_path, monkeypatch):
    async def run():
        manager, _, conn, bus, states, emit = subscription_fixture(tmp_path, monkeypatch)
        subscribe_journal(manager.hass, conn, {"id": 1, "entry_id": "one"})
        conn.send_result.assert_called_once_with(1)
        conn.send_error.assert_not_called()
        expected = {"id": 1, "type": "event", "event": {"entry_id": "one"}}
        conn.send_message.assert_called_once_with(expected)
        emit("other")
        assert conn.send_message.call_count == 1
        emit()
        assert conn.send_message.call_args.args == (expected,)
        assert conn.send_message.call_count == 2
        conn.user.permissions.check_entity.assert_called_with("camera.door", "read")
        conn.subscriptions.pop(1)()
        assert not bus and not states
        emit()
        assert conn.send_message.call_count == 2

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["permission", "disabled", "missing_camera", "other_entry", "manager_closed", "journal_closed", "no_journal", "unloading"])
def test_initial_subscription_fails_closed(tmp_path, monkeypatch, failure):
    async def run():
        manager, registered, conn, bus, states, _ = subscription_fixture(tmp_path, monkeypatch)
        entry_id = "one"
        if failure == "permission":
            conn.user.permissions.check_entity.return_value = False
        elif failure == "disabled":
            conn.user.is_admin = True
            registered.disabled_by = "user"
        elif failure == "missing_camera":
            from custom_components.bticino_c300x import snapshot_http
            monkeypatch.setattr(snapshot_http.er, "async_get", lambda _: SimpleNamespace(async_get_entity_id=lambda *args: None))
        elif failure == "other_entry":
            entry_id = "other"
        elif failure == "manager_closed":
            manager.closed = True
        elif failure == "journal_closed":
            manager.journal.closed = True
        elif failure == "no_journal":
            manager.journal = None
        else:
            manager.entry.state = ConfigEntryState.UNLOAD_IN_PROGRESS
        subscribe_journal(manager.hass, conn, {"id": 1, "entry_id": entry_id})
        conn.send_error.assert_called_once()
        conn.send_result.assert_not_called()
        conn.send_message.assert_not_called()
        assert not conn.subscriptions and not bus and not states

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["permission", "disabled", "manager_closed", "journal_closed", "manager_replaced", "user_replaced"])
def test_revocation_or_entry_replacement_stops_without_disclosing_a_signal(tmp_path, monkeypatch, failure):
    async def run():
        manager, registered, conn, bus, states, emit = subscription_fixture(tmp_path, monkeypatch)
        subscribe_journal(manager.hass, conn, {"id": 1, "entry_id": "one"})
        conn.send_message.reset_mock()
        if failure == "permission":
            conn.user.permissions.check_entity.return_value = False
        elif failure == "disabled":
            registered.disabled_by = "user"
        elif failure == "manager_closed":
            manager.closed = True
        elif failure == "journal_closed":
            manager.journal.closed = True
        elif failure == "manager_replaced":
            manager.hass.data[DOMAIN]["stream_snapshots"]["one"] = SimpleNamespace(closed=False, journal=SimpleNamespace(closed=False))
        else:
            conn.user = SimpleNamespace(is_admin=False, permissions=SimpleNamespace(check_entity=lambda *_: False))
        emit()
        conn.send_message.assert_not_called()
        assert not bus and not states
        conn.subscriptions.pop(1)()  # Disconnect after server-side cleanup is idempotent.

    asyncio.run(run())


def test_unload_cleans_all_subscriptions_and_reconnect_gets_initial_refresh(tmp_path, monkeypatch):
    async def run():
        manager, _, conn, bus, states, emit = subscription_fixture(tmp_path, monkeypatch)
        for message_id in (1, 2):
            subscribe_journal(manager.hass, conn, {"id": message_id, "entry_id": "one"})
        manager.entry.state = ConfigEntryState.UNLOAD_IN_PROGRESS
        # Match HA's direct iteration: removing a listener here would skip the next.
        for callback in states:
            callback()
        assert not bus
        await asyncio.sleep(0)
        assert not states
        assert [call.args[0]["event"] for call in conn.send_message.call_args_list] == [
            {"entry_id": "one"}, {"entry_id": "one"},
            {"entry_id": "one", "closed": True}, {"entry_id": "one", "closed": True},
        ]
        for stop in conn.subscriptions.values():
            stop()
        conn.subscriptions.clear()
        manager.entry.state = ConfigEntryState.LOADED
        conn.send_message.reset_mock()
        subscribe_journal(manager.hass, conn, {"id": 3, "entry_id": "one"})
        assert len(bus) == len(states) == 1
        conn.send_message.assert_called_once_with({"id": 3, "type": "event", "event": {"entry_id": "one"}})
        conn.subscriptions.pop(3)()
        emit()
        assert not bus and not states

    asyncio.run(run())


def test_media_registration_registers_validated_subscription_command_once():
    hass = SimpleNamespace(data={}, http=SimpleNamespace(register_view=Mock()))
    async_setup_media_view(hass)
    handler, schema = hass.data["websocket_api"][SUBSCRIBE_TYPE]
    assert handler is subscribe_journal
    assert schema({"id": 1, "type": SUBSCRIBE_TYPE, "entry_id": "one"})["entry_id"] == "one"
    with pytest.raises(vol.Invalid):
        schema({"id": 1, "type": SUBSCRIBE_TYPE})
    async_setup_media_view(hass)
    assert hass.data["websocket_api"][SUBSCRIBE_TYPE][1] is schema
