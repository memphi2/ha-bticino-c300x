"""Camera-authorized, entry-scoped journal invalidation without media metadata."""

from __future__ import annotations

from typing import Any, cast

from aiohttp import web
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback

from .schema_compat import vol
from .snapshot_http import authorize_snapshot_entry
from .visitor_journal import EVENT_JOURNAL_CHANGED

SUBSCRIBE_TYPE = "bticino_c300x/visitor_journal/subscribe"


@callback
def subscribe_journal(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    """Keep authorization and listener lifetime bound to this entry instance."""
    entry_id, message_id = msg["entry_id"], msg["id"]
    try:
        entry, manager, _ = authorize_snapshot_entry(hass, connection.user, entry_id, POLICY_READ)
        if (entry.state is not ConfigEntryState.LOADED
                or manager.journal is None or manager.journal.closed):
            raise web.HTTPNotFound()
    except web.HTTPException as err:
        connection.send_error(message_id, "unauthorized" if err.status == 403 else "not_found",
                              "Visitor journal unavailable")
        return

    from homeassistant.components import websocket_api

    stopped = False

    @callback
    def stop(*, from_state_change: bool = False) -> None:
        nonlocal stopped
        if stopped:
            return
        stopped = True
        cancel_events()
        # HA iterates its state listeners directly. Remove ours after that pass.
        if from_state_change:
            hass.loop.call_soon(cancel_state)
        else:
            cancel_state()

    def authorized() -> bool:
        try:
            current_entry, current_manager, _ = authorize_snapshot_entry(
                hass, connection.user, entry_id, POLICY_READ,
            )
        except web.HTTPException:
            return False
        return (current_entry is entry and current_manager is manager
                and manager.journal is not None and not manager.journal.closed)

    @callback
    def refresh(event: Any = None) -> None:
        if stopped or (event is not None and event.data.get("entry_id") != entry_id):
            return
        if not authorized():
            stop()
            return
        connection.send_message(websocket_api.event_message(message_id, {"entry_id": entry_id}))

    @callback
    def state_changed() -> None:
        if stopped or entry.state is ConfigEntryState.LOADED:
            return
        if authorized():
            connection.send_message(websocket_api.event_message(
                message_id, {"entry_id": entry_id, "closed": True},
            ))
        stop(from_state_change=True)

    cancel_events = hass.bus.async_listen(EVENT_JOURNAL_CHANGED, refresh)
    cancel_state = entry.async_on_state_change(state_changed)
    connection.subscriptions[message_id] = stop
    connection.send_result(message_id)
    # Also runs after HA's client re-subscribes following a connection outage.
    refresh()


def async_register_visitor_journal_ws(hass: Any) -> None:
    """Register the command once alongside the media views."""
    from homeassistant.components import websocket_api

    exports = cast(Any, websocket_api)
    command = exports.websocket_command({
        vol.Required("type"): SUBSCRIBE_TYPE,
        vol.Required("entry_id"): str,
    })(subscribe_journal)
    websocket_api.async_register_command(hass, command)
