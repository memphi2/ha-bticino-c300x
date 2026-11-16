"""Late diagnostic reads cannot publish into another config-entry lifetime."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.bticino_c300x import agent_diagnostics, repair_issues
from custom_components.bticino_c300x.data import (
    BticinoC300XRuntimeData,
    C300XConnectionState,
    C300XEventState,
)


def runtime(api):
    return BticinoC300XRuntimeData(
        api=api, capabilities={"diagnostics": {"supported": True}},
        event_state=C300XEventState(), connection_state=C300XConnectionState(),
        agent_info={}, loaded_platforms=(),
    )


@pytest.mark.parametrize("transition", [
    "unchanged", "offline", "closed", "replaced", "reloaded", "removed", "cancelled",
])
def test_diagnostic_response_keeps_its_runtime_owner(monkeypatch, transition):
    send = Mock()
    repairs = Mock()
    monkeypatch.setattr(agent_diagnostics, "async_dispatcher_send", send)
    monkeypatch.setattr(repair_issues, "async_sync_entry_repair_issues", repairs)

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        payload = {"agent_uptime_seconds": 999, "last_write_reason": "old runtime"}

        async def read():
            entered.set()
            await release.wait()
            return payload

        old = runtime(SimpleNamespace(async_diagnostics=read))
        replacement = runtime(SimpleNamespace(async_diagnostics=AsyncMock()))
        entry = SimpleNamespace(entry_id="review", runtime_data=old)
        hass = SimpleNamespace()
        if transition == "offline":
            old.connection_state.mark_unavailable()
        task = asyncio.create_task(agent_diagnostics.async_refresh_agent_diagnostics(hass, entry))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            if transition in {"closed", "reloaded", "removed"}:
                old.resources.close()
            if transition in {"replaced", "reloaded"}:
                entry.runtime_data = replacement
            elif transition == "removed":
                del entry.runtime_data
            elif transition == "cancelled":
                task.cancel()
            release.set()
            if transition == "cancelled":
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                result = await asyncio.wait_for(task, 1)
                assert result == (payload if transition in {"unchanged", "offline"} else None)
            if transition in {"unchanged", "offline"}:
                assert old.diagnostics.agent_diagnostics == payload
                assert old.diagnostics.agent_uptime_seconds == 999
                send.assert_called_once()
                repairs.assert_called_once_with(hass, entry)
            else:
                assert old.diagnostics.agent_diagnostics == {}
                assert old.diagnostics.agent_diagnostics_updated_at is None
                send.assert_not_called()
                repairs.assert_not_called()
            assert replacement.diagnostics.agent_diagnostics == {}
            assert replacement.diagnostics.agent_diagnostics_updated_at is None
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_closed_runtime_does_not_start_diagnostics_read():
    api = SimpleNamespace(async_diagnostics=AsyncMock())
    current = runtime(api)
    current.resources.close()
    entry = SimpleNamespace(entry_id="review", runtime_data=current)
    assert asyncio.run(agent_diagnostics.async_refresh_agent_diagnostics(None, entry)) is None
    api.async_diagnostics.assert_not_called()
