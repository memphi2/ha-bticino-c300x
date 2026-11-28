"""A delayed stop belongs to one entry lifetime, never its replacement."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.bticino_c300x.data import C300XRuntimeResources
from custom_components.bticino_c300x.use_cases.doorbell_video import (
    DoorbellVideoUseCase,
)
from custom_components.bticino_c300x.use_cases.home_call import HomeCallUseCase
from custom_components.bticino_c300x.use_cases.ring_call import RingCallUseCase


@pytest.mark.parametrize("kind,wait_at", [
    ("doorbell", "prepare"), ("home_call", "prepare"),
    ("ring", "prepare"), ("doorbell", "status"),
])
@pytest.mark.parametrize("invalidate", ["replace", "close", "remove"])
def test_delayed_stop_never_escapes_runtime(kind, invalidate, wait_at):
    async def run():
        entered, finish = asyncio.Event(), asyncio.Event()

        async def wait():
            entered.set()
            await finish.wait()
            return {"bridge": {"media_owner": "on_demand"}}

        def runtime():
            return SimpleNamespace(
                capabilities={key: {"supported": True} for key in
                              ("doorbell_video", "doorbell_call", "home_call")},
                api=SimpleNamespace(
                    async_doorbell_video_status=AsyncMock(return_value={}),
                    async_stop_doorbell_video=AsyncMock(),
                    async_stop_home_call=AsyncMock(),
                    async_call_action_target=AsyncMock(return_value="0badc0de-2"),
                    async_hangup_doorbell_call=AsyncMock(),
                ),
                resources=C300XRuntimeResources(),
            )

        old, replacement = runtime(), runtime()
        prepare = AsyncMock(side_effect=wait if wait_at == "prepare" else None)
        old.resources.prepare_doorbell_video_stop = prepare
        old.resources.prepare_home_call_stop = prepare
        if wait_at == "status":
            old.api.async_doorbell_video_status.side_effect = wait
        entry = SimpleNamespace(runtime_data=old, data={"video_enabled": True}, options={})
        use_case, action = {
            "doorbell": (DoorbellVideoUseCase, "stop"),
            "home_call": (HomeCallUseCase, "stop"),
            "ring": (RingCallUseCase, "hangup"),
        }[kind]
        task = asyncio.create_task(getattr(use_case(entry), action)())
        await asyncio.wait_for(entered.wait(), 1)
        if invalidate == "replace":
            entry.runtime_data = replacement
        elif invalidate == "close":
            old.resources.close()
        else:
            del entry.runtime_data
        finish.set()
        with pytest.raises(HomeAssistantError):
            await task
        for current in (old, replacement):
            current.api.async_stop_doorbell_video.assert_not_awaited()
            current.api.async_stop_home_call.assert_not_awaited()
            current.api.async_hangup_doorbell_call.assert_not_awaited()
            assert current.resources.media_stop_counts == {}
        if wait_at == "status":
            prepare.assert_not_awaited()

    asyncio.run(run())
