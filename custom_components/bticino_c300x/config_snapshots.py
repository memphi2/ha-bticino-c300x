"""Device-wide stream image preferences, independent of card instances."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

CONF_STREAM_SNAPSHOTS = "stream_snapshots"
CONF_SNAPSHOT_DELAY = "snapshot_delay_seconds"
CONF_SNAPSHOT_RETENTION = "snapshot_retention_days"
SNAPSHOT_DEFAULTS = {
    CONF_SNAPSHOT_DELAY: 5,
    CONF_SNAPSHOT_RETENTION: 14,
}


@dataclass(frozen=True)
class SnapshotOptions:
    """Validated values used by storage and the frontend."""

    delay_seconds: int = 5
    retention_days: int = 14


def snapshot_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """Validate all preferences, including callers bypassing the form schema."""

    result = {key: values.get(key, default) for key, default in SNAPSHOT_DEFAULTS.items()}
    for key, maximum in ((CONF_SNAPSHOT_DELAY, 300), (CONF_SNAPSHOT_RETENTION, 365)):
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(key)
        if not 1 <= value <= maximum or value != int(value):
            raise ValueError(key)
        result[key] = int(value)
    return result


def snapshot_options(entry: Any) -> SnapshotOptions:
    """Read options before initial data, with safe defaults for invalid storage."""

    values = {**entry.data, **entry.options}
    try:
        values = snapshot_values(values)
    except ValueError:
        return SnapshotOptions()
    return SnapshotOptions(
        delay_seconds=values[CONF_SNAPSHOT_DELAY],
        retention_days=values[CONF_SNAPSHOT_RETENTION],
    )
