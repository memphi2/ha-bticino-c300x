"""Display commands must not cross the runtime boundary while reading a body."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.bticino_c300x import webhook
from custom_components.bticino_c300x.const import (
    CONF_ACTIONS,
    CONF_SHARED_SECRET,
    HEADER_SHARED_SECRET,
)
from custom_components.bticino_c300x.data import (
    C300XConnectionState,
    C300XRuntimeResources,
)


@pytest.mark.parametrize("transition", [
    "unchanged", "offline", "startup", "setup_completed", "already_closed",
    "closed", "replaced", "reloaded", "removed",
])
def test_display_action_body_is_bound_to_its_runtime(transition):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        old = SimpleNamespace(
            resources=C300XRuntimeResources(), connection_state=C300XConnectionState(),
        )
        entry = SimpleNamespace(
            entry_id="review", data={CONF_SHARED_SECRET: "secret"},
            options={CONF_ACTIONS: {
                "entry_light": {"domain": "light", "service": "toggle",
                                "data": {"entity_id": "light.entry"}},
            }}, runtime_data=old,
        )
        if transition in {"startup", "setup_completed"}:
            del entry.runtime_data
        elif transition == "offline":
            old.connection_state.mark_unavailable()
        elif transition == "already_closed":
            old.resources.close()
        hass = SimpleNamespace(
            services=SimpleNamespace(async_call=AsyncMock()),
            bus=SimpleNamespace(async_fire=Mock()),
        )

        async def body():
            entered.set()
            await release.wait()
            return {"type": "action", "action_id": "entry_light"}

        request = SimpleNamespace(headers={HEADER_SHARED_SECRET: "secret"}, json=body)
        task = asyncio.create_task(webhook._async_handle_webhook(hass, entry, request))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            if transition in {"closed", "reloaded", "removed"}:
                old.resources.close()
            if transition in {"replaced", "reloaded", "setup_completed"}:
                entry.runtime_data = SimpleNamespace(resources=C300XRuntimeResources())
            elif transition == "removed":
                del entry.runtime_data
            release.set()
            response = await asyncio.wait_for(task, 1)
            if transition in {"unchanged", "offline", "startup"}:
                assert response.status == 200
                hass.services.async_call.assert_awaited_once()
                assert hass.services.async_call.call_args.args == (
                    "light", "toggle", {"entity_id": "light.entry"},
                )
                hass.bus.async_fire.assert_called_once()
            else:
                assert response.status == 503
                assert json.loads(response.text) == {"ok": False, "error": "entry_unloaded"}
                hass.services.async_call.assert_not_called()
                hass.bus.async_fire.assert_not_called()
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
