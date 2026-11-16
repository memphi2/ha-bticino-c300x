"""Top live consumers from HA Energy's explicitly configured power sensors."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from heapq import nsmallest
from typing import Any

from .dashboard_labels import ENERGY_LABELS_BY_LANGUAGE, decimal_text
from .validation_patterns import HA_ENTITY_ID_RE

# Readable members of HA frontend's default --color-N graph palette. Browser
# theme overrides / index-assigned graph colors are not exposed by Energy data.
_COLORS = (
    "#f4bd4a", "#ff725c", "#6cc5b0", "#a463f2", "#ff8ab7", "#97bbf5",
    "#6989f4", "#ffd444", "#ff957c", "#8fe9d3", "#62cc71", "#ffadda",
    "#c884ff", "#badeff", "#8caed6", "#f2b94f", "#eff26e", "#cbe8ff",
    "#fecddf", "#c27eb6", "#8cd2ce", "#c4b8d9", "#f883b0", "#27d0df",
)


@dataclass(frozen=True, slots=True)
class EnergyConsumer:
    """A direct stat_rate mapping, never a guessed companion sensor."""

    entity_id: str
    name: str = ""


def consumer_sources(preferences: Any) -> tuple[EnergyConsumer, ...]:
    """Read the DeviceConsumption contract shared by HA 2026.10 and 2026.11."""
    devices = preferences.get("device_consumption") if isinstance(preferences, dict) else None
    result: dict[str, EnergyConsumer] = {}
    for device in devices if isinstance(devices, list) else ():
        if not isinstance(device, dict):
            continue
        entity_id = device.get("stat_rate")
        if (not isinstance(entity_id, str) or not entity_id.startswith("sensor.")
                or not HA_ENTITY_ID_RE.fullmatch(entity_id) or entity_id in result):
            continue
        name = device.get("name")
        result[entity_id] = EnergyConsumer(entity_id, name.strip()[:80] if isinstance(name, str) else "")
    return tuple(result.values())


def consumer_power_watts(state: Any) -> float | None:
    """Unknown units and negative consumption are not measured zero watts."""
    from .dashboard_energy import power_watts

    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, Mapping) or not attributes.get("unit_of_measurement"):
        return None
    value = power_watts(state)
    return value if value is not None and value >= 0 else None


def consumer_color(entity_id: str) -> str:
    """Keep a sensor's color through reordering, ranking changes and restarts."""
    return _COLORS[int(hashlib.sha256(entity_id.encode()).hexdigest()[:8], 16) % len(_COLORS)]


def consumers_payload(
    sources: tuple[EnergyConsumer, ...], states: Mapping[str, Any], language: str,
) -> dict[str, Any]:
    """Rank measured, nonnegative live watts; omit unavailable and unmapped devices."""
    labels = ENERGY_LABELS_BY_LANGUAGE.get(language, ENERGY_LABELS_BY_LANGUAGE["en"])
    items: list[dict[str, Any]] = []
    measured: list[tuple[EnergyConsumer, float, Any]] = []
    incomplete = False
    for source in sources:
        state = states.get(source.entity_id)
        watts = consumer_power_watts(state)
        if watts is None:
            incomplete = True
            continue
        measured.append((source, watts, state))
    for source, watts, state in nsmallest(10, measured, key=lambda item: (-item[1], item[0].entity_id)):
        name = source.name or (getattr(state, "attributes", {}) or {}).get("friendly_name")
        label = " ".join(name.split())[:80] if isinstance(name, str) and name.strip() else source.entity_id
        value = str(watts).removesuffix(".0") if watts else "0"
        value = decimal_text(value, language)
        items.append({"entity_id": source.entity_id, "label": label, "watts": watts,
                      "value": f"{value} W", "color": consumer_color(source.entity_id)})
    return {"items": items, "unit": "W", "empty_text": labels["consumers_empty"],
            "status": labels["consumers_incomplete"] if incomplete else ""}
