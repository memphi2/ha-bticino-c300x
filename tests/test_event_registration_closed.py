"""Discovery cannot restart registration after runtime resources were closed."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_events import _FakeEntry, _FakeHass

from custom_components.bticino_c300x import events
from custom_components.bticino_c300x.data import (
    BticinoC300XRuntimeData,
    C300XConnectionState,
    C300XEventState,
)


@pytest.mark.parametrize("offline_setup", [False, True])
def test_closed_runtime_rejects_rediscovery_before_side_effects(monkeypatch, offline_setup):
    hass, entry = _FakeHass(), _FakeEntry()
    reload = Mock()
    hass.config_entries = SimpleNamespace(async_schedule_reload=reload)
    entry.runtime_data = BticinoC300XRuntimeData(
        api=Mock(), capabilities={}, event_state=C300XEventState(),
        connection_state=C300XConnectionState(), loaded_platforms=(),
        agent_info={"offline_error": "offline"} if offline_setup else {},
        system_metrics={"cpu_percent": 17},
    )
    entry.runtime_data.resources.close()
    worker = Mock()
    invalidate = Mock()
    monkeypatch.setattr(events, "_AgentEventRegistration", worker)
    monkeypatch.setattr(events, "invalidate_system_metrics", invalidate)

    async def run():
        assert not events.async_request_agent_event_registration(hass, entry)
        await asyncio.sleep(0)

    asyncio.run(run())
    worker.assert_not_called()
    invalidate.assert_not_called()
    reload.assert_not_called()
    assert hass.async_tasks == []
    assert hass.bus.listeners == {}
    assert entry.runtime_data.resources.unregister_event_registration is None
    assert entry.runtime_data.system_metrics == {"cpu_percent": 17}
