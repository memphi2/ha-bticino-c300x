"""An awaited discovery read cannot resurrect an unloaded runtime."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.bticino_c300x.config_flow_identity import (
    async_existing_manual_discovery,
)
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
)
from custom_components.bticino_c300x.data import C300XRuntimeResources
from custom_components.bticino_c300x.discovery import discovery_matches_entry


@pytest.mark.parametrize("transition", ["open", "closed", "removed", "replaced", "entry_removed"])
def test_discovery_continuation_requires_same_live_runtime(transition):
    async def exercise():
        runtime = SimpleNamespace(resources=C300XRuntimeResources())
        entry = SimpleNamespace(
            unique_id="bticino_c300x:a.local:8091", runtime_data=runtime, options={},
            data={CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091, CONF_AGENT_TOKEN: "saved"},
        )
        entries = [entry]
        registration = Mock()
        flow = SimpleNamespace(
            hass=SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock())),
            _async_current_entries=lambda: entries,
            _async_request_event_registration=registration,
            async_abort=lambda **kwargs: {"type": "abort", **kwargs},
        )
        started, release = asyncio.Event(), asyncio.Event()

        async def read(_hass, connection, *, api_token):
            assert connection[CONF_AGENT_HOST] == "a.local" and api_token == "saved"
            started.set()
            await release.wait()
            return {"device_id": "real-device"}

        task = asyncio.create_task(async_existing_manual_discovery(
            flow, "advertised", dict(entry.data), discovery_matches_entry, read,
        ))
        await started.wait()
        if transition != "open":
            runtime.resources.close()
        if transition == "removed":
            del entry.runtime_data
        elif transition == "replaced":
            entry.runtime_data = SimpleNamespace(resources=C300XRuntimeResources())
        elif transition == "entry_removed":
            entries.clear()
        release.set()
        result = await task
        assert result["reason"] == "already_configured"
        assert registration.call_count == (1 if transition == "open" else 0)
        if transition != "open":
            assert runtime.resources.closed
            assert runtime.resources.unregister_event_registration is None

    asyncio.run(exercise())
