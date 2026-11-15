"""Current power through a common junction, never per-source load attribution."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, TypedDict

from .dashboard_controls import finite_number
from .dashboard_energy import (
    COLOR_BATTERY,
    COLOR_EXPORT,
    COLOR_GRID,
    COLOR_HOME,
    COLOR_SOLAR,
    EnergySources,
    format_power,
    source_power_watts,
)
from .dashboard_labels import ENERGY_LABELS_BY_LANGUAGE


class _Node(TypedDict):
    id: str
    label: str
    value: str
    watts: float | None
    color: str
    start: float
    size: float


def power_distribution_payload(
    sources: EnergySources, power: dict[str, float | None], language: str,
) -> dict[str, Any]:
    """Return power nodes; only known, conserved balances get bands.

    Both sides use the same input total in watts. Unconfigured power is zero;
    configured unknown readings stay unknown on both sides and suppress Home.
    ``status`` is a localized incomplete notice, empty for a complete balance.
    """

    labels = ENERGY_LABELS_BY_LANGUAGE.get(language, ENERGY_LABELS_BY_LANGUAGE["en"])
    readings = {entity: finite_number(value) for entity, value in power.items()}
    # Reject even one negative solar reading, not just a negative group sum.
    for entity in sources.solar_power:
        if (value := readings.get(entity)) is not None and value < 0:
            readings[entity] = None
    values = source_power_watts(sources, readings)
    values.pop("home")
    known = [value for value in values.values() if value is not None]
    supplied = sum(max(0.0, value) for value in known)
    removed = sum(max(0.0, -value) for value in known)
    complete = (
        bool(values) and len(known) == len(values)
        and math.isfinite(supplied) and math.isfinite(removed)
        and supplied >= removed
    )

    def node(key: str, watts: float | None, color: str) -> _Node:
        return {
            "id": key, "label": labels[key], "color": color,
            "value": "--" if watts is None else format_power(watts, language),
            "watts": watts, "start": 0.0, "size": 0.0,
        }

    left: list[_Node] = []
    right = [node("home", supplied - removed if complete else None, COLOR_HOME)]
    for key, sink, color in (
        ("grid", "export", COLOR_GRID),
        ("solar", "", COLOR_SOLAR),
        ("battery", "charge", COLOR_BATTERY),
    ):
        if key not in values:
            continue
        watts = values[key]
        left.append(node(key, None if watts is None else max(0.0, watts), color))
        if sink:
            right.append(node(sink, None if watts is None else max(0.0, -watts),
                              COLOR_EXPORT if sink == "export" else color))

    if complete and supplied > 0:
        for side in (left, right):
            position = 0.0
            for item in side:
                item["start"] = position
                item["size"] = min(1.0 - position, (item["watts"] or 0.0) / supplied)
                position += item["size"]

    payload: dict[str, Any] = {
        "left": left, "right": right, "complete": complete,
        "empty_text": labels["distribution_empty"],
        "status": "" if complete else labels["distribution_incomplete"],
        "unit": "W",
    }
    payload["revision"] = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()[:16]
    return payload
