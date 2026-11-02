"""Isolated real-HA probes: no suite-wide module stubs or live credentials."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from harness import RuntimeLab  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.bticino_c300x import events  # noqa: E402


async def lifecycle(root: Path):
    async with RuntimeLab(root) as lab:
        entry = await lab.add_entry()
        assert lab.agent.subscriptions
        muted = lab.entity("ringer_mute", "switch")
        assert (await lab.push("ringer.unmuted", {}))[0] == 200
        assert lab.hass.states.get(muted).state == "off"
        status, _ = await lab.push("ringer.muted", {}, token="invalid")
        assert status == 401
        assert lab.hass.states.get(muted).state == "off"
        status, _ = await lab.push("ringer.muted", {})
        assert status == 200
        assert lab.hass.states.get(muted).state == "on"
        renamed = "switch.renamed_door_mute"
        er.async_get(lab.hass).async_update_entity(muted, new_entity_id=renamed)
        await lab.settle()
        assert await lab.hass.config_entries.async_reload(entry.entry_id)
        await lab.settle()
        assert lab.entity("ringer_mute", "switch") == renamed
        await lab.hass.services.async_call(
            "switch", "turn_off", {"entity_id": renamed}, blocking=True
        )
        assert lab.hass.states.get(renamed).state == "off"
        assert lab.agent.requests["POST", "/api/v1/ringer"] == 1

        lab.agent.fail_list = True
        events.async_request_agent_event_registration(lab.hass, entry)
        await lab.wait_for(
            lambda: (
                entry.runtime_data.connection_state.event_subscription_last_error
                is not None
            )
        )
        lab.agent.fail_list = False
        await lab.wait_for(
            lambda: (
                entry.runtime_data.connection_state.event_subscription_last_error
                is None
            )
        )

        lab.agent.list_started.clear()
        lab.agent.hold_list = asyncio.Event()
        events.async_request_agent_event_registration(lab.hass, entry)
        await asyncio.wait_for(lab.agent.list_started.wait(), 5)
        assert await lab.hass.config_entries.async_unload(entry.entry_id)
        lab.agent.hold_list.set()
        await lab.settle()
        assert not lab.agent.unexpected, lab.agent.unexpected
        assert "synthetic-events" not in lab.hass.data["webhook"]
        requests = lab.agent.requests.copy()
        await asyncio.sleep(0.15)
        assert lab.agent.requests == requests, "Agent requests continued after unload"
        print("Real HA lifecycle probe passed")  # noqa: T201


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="c300x-runtime-") as directory:
        asyncio.run(lifecycle(Path(directory) / "ha"))
