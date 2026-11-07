"""Notification guards must cover real HA service completion and cancellation."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.bticino_c300x.display_notifications import (
    SHOW_SCHEMA,
    DisplayNotifications,
    async_notification_action,
)


@pytest.mark.parametrize("outcome", ["success", "error", "unload"])
def test_notification_tracks_the_running_service(tmp_path, outcome):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        started, release, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = []

        async def action(call):
            calls.append(call)
            started.set()
            try:
                await release.wait()
                if outcome == "error":
                    raise HomeAssistantError("action failed")
            finally:
                stopped.set()

        hass.services.async_register("test", "held", action)
        store = DisplayNotifications(hass.loop, lambda: None)
        entry = SimpleNamespace(
            entry_id="test",
            data={},
            options={
                "device_ui_enabled": True,
                "actions": {"held": {"domain": "test", "service": "held"}},
            },
            runtime_data=SimpleNamespace(display_notifications=store),
        )
        store.show(
            SHOW_SCHEMA(
                {
                    "notification_id": "notice",
                    "title": "Notice",
                    "message": "Text",
                    "actions": [{"action_id": "held", "label": "Run"}],
                }
            )
        )
        option = json.dumps(
            {"revision": store.payload()[0]["revision"], "action_id": "held"}
        )
        pending = asyncio.create_task(
            async_notification_action(hass, entry, "notice", option)
        )
        try:
            await asyncio.wait_for(started.wait(), 1)
            assert not pending.done()
            with pytest.raises(ValueError, match="pending"):
                await async_notification_action(hass, entry, "notice", option)
            if outcome == "unload":
                store.close()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                release.set()
                if outcome == "error":
                    with pytest.raises(HomeAssistantError, match="action failed"):
                        await pending
                else:
                    assert await pending == {"ok": True}
            assert not store.busy and not store._pending
            assert len(calls) == 1
        finally:
            release.set()
            store.close()
            await asyncio.gather(pending, return_exceptions=True)
            await hass.async_block_till_done()
        assert stopped.is_set()

    asyncio.run(run())
