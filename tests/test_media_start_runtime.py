"""Media setup must not use replacement runtimes after status/gain awaits."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.bticino_c300x.data import C300XRuntimeResources
from custom_components.bticino_c300x.doorstation_audio import (
    async_ensure_doorstation_audio_gain,
)
from custom_components.bticino_c300x.use_cases.doorbell_video import (
    DoorbellVideoUseCase,
)
from custom_components.bticino_c300x.use_cases.ring_call import RingCallUseCase


@pytest.mark.parametrize("action,wait_at", [
    ("activate", "status"), ("activate", "gain"),
    ("answer", "status"), ("answer", "gain"), ("gain", "status"),
])
@pytest.mark.parametrize("invalidate", ["replace", "close", "remove"])
def test_media_setup_stays_on_its_original_runtime(action, wait_at, invalidate):
    async def run():
        entered, finish = asyncio.Event(), asyncio.Event()

        async def wait(*args):
            entered.set()
            await finish.wait()
            return {"bridge": {"doorstation_audio_gain_db": 0}}

        def runtime():
            return SimpleNamespace(
                capabilities={key: {"supported": True} for key in
                              ("doorbell_video", "doorbell_call")},
                api=SimpleNamespace(
                    async_doorbell_video_status=AsyncMock(return_value={}),
                    async_set_doorstation_audio_gain_db=AsyncMock(),
                    async_activate_doorbell_video=AsyncMock(),
                    async_answer_doorbell_call=AsyncMock(),
                ), resources=C300XRuntimeResources(),
            )

        old, replacement = runtime(), runtime()
        method = (old.api.async_doorbell_video_status if wait_at == "status"
                  else old.api.async_set_doorstation_audio_gain_db)
        method.side_effect = wait
        entry = SimpleNamespace(runtime_data=old, data={"video_enabled": True},
                                options={"doorstation_audio_gain_db": 6})
        operation = {"activate": DoorbellVideoUseCase(entry).activate,
                     "answer": RingCallUseCase(entry).answer,
                     "gain": lambda: async_ensure_doorstation_audio_gain(entry)}[action]
        task = asyncio.create_task(operation())
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
            current.api.async_activate_doorbell_video.assert_not_awaited()
            current.api.async_answer_doorbell_call.assert_not_awaited()
        replacement.api.async_doorbell_video_status.assert_not_awaited()
        replacement.api.async_set_doorstation_audio_gain_db.assert_not_awaited()
        assert old.api.async_set_doorstation_audio_gain_db.await_count == (wait_at == "gain")

    asyncio.run(run())
