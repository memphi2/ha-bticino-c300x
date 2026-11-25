"""Export only the card's public entity contract from a synthetic HA runtime."""

from __future__ import annotations

import json
from pathlib import Path

from fake_agent import UNIT
from harness import RuntimeLab
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

ATTRIBUTES = {
    "friendly_name",
    "lock_id",
    "media_state",
    "media_primary_action",
    "media_reason",
    "is_streaming",
    "failed_checks",
    "status",
    "options",
    "door_entity_id",
}


async def run(root: Path):
    async with RuntimeLab(root, video=True) as lab:
        expected = []
        registry = er.async_get(lab.hass)
        for label in ("alpha", "bravo"):
            entry = await lab.add_entry(name=label)
            ids = {}
            # 3.1.0: camera and door button belong to the outdoor unit's device.
            for domain, key, unique_key in (
                ("camera", "doorbell_camera", f"unit_{UNIT}_camera"),
                ("button", "door_unlock", f"unit_{UNIT}_door"),
                ("button", "stair_light", "stair_light"),
                ("sensor", "media_readiness", "media_readiness"),
            ):
                old_id = lab.entity(unique_key, domain)
                entity_id = f"{domain}.renamed_{label}_{key}"
                registry.async_update_entity(old_id, new_entity_id=entity_id)
                ids[key] = entity_id
            await lab.settle()
            assert await lab.hass.config_entries.async_reload(entry.entry_id)
            await lab.settle()
            for entity_id in ids.values():
                assert lab.hass.states.get(entity_id) is not None, entity_id
            for key in ("door_unlock", "stair_light"):
                await lab.hass.services.async_call(
                    "button", "press", {"entity_id": ids[key]}, blocking=True
                )
            expected.append({"entry_id": entry.entry_id, **ids})

        def export():
            entities, states, devices = {}, {}, {}
            wanted = {value for item in expected for value in item.values()}
            for item in registry.entities.values():
                if item.entity_id not in wanted or item.disabled:
                    continue
                # Decode exactly the display-registry fields the HA frontend gets.
                display = json.loads(item.display_json_repr)
                entities[item.entity_id] = {
                    "platform": display["pl"],
                    "device_id": display.get("di"),
                    "translation_key": display.get("tk"),
                }
                device = dr.async_get(lab.hass).async_get(item.device_id)
                if hasattr(device, "config_entry_id"):
                    devices[device.id] = {"config_entry_id": device.config_entry_id}
                else:
                    devices[device.id] = {
                        "config_entries": sorted(device.config_entries)
                    }
                devices[device.id]["via_device_id"] = device.via_device_id
                state = lab.hass.states.get(item.entity_id)
                if state is not None:
                    states[item.entity_id] = {
                        "state": state.state,
                        "attributes": {
                            key: value
                            for key, value in state.attributes.items()
                            if key in ATTRIBUTES
                        },
                    }
            return {"entities": entities, "states": states, "devices": devices}

        enabled = export()
        disabled_id = expected[1]["stair_light"]
        registry.async_update_entity(
            disabled_id, disabled_by=er.RegistryEntryDisabler.USER
        )
        await lab.settle()
        assert await lab.hass.config_entries.async_reload(entry.entry_id)
        await lab.settle()
        disabled = export()
        assert disabled_id not in disabled["states"]
        assert lab.agent.requests["POST", f"/api/v1/outdoor-units/{UNIT}/actions/unlock"] == 2
        assert lab.agent.requests["POST", "/api/v1/stair-light/actions/activate"] == 2
        return {"enabled": enabled, "disabled": disabled, "expected": expected}
