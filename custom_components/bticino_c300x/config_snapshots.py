"""Device-wide stream image preferences, independent of card instances."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

CONF_STREAM_SNAPSHOTS = "stream_snapshots"
CONF_SNAPSHOT_DELAY = "snapshot_delay_seconds"
CONF_SNAPSHOT_RETENTION = "snapshot_retention_days"
CONF_SNAPSHOT_WIDTH = "snapshot_width"
CONF_SNAPSHOT_HEIGHT = "snapshot_height"
CONF_SNAPSHOT_TIMESTAMP = "snapshot_timestamp"
# Snapshots read the 800x480 display framebuffer, not the encoded video stream.
# The default preserves its pixels and 5:3 aspect ratio. Explicit sizes are
# resampled by the agent; Home Assistant does not resize them again.
SNAPSHOT_DEFAULTS = {
    CONF_SNAPSHOT_DELAY: 3,
    CONF_SNAPSHOT_RETENTION: 14,
    CONF_SNAPSHOT_WIDTH: 800,
    CONF_SNAPSHOT_HEIGHT: 480,
    CONF_SNAPSHOT_TIMESTAMP: True,
}
SNAPSHOT_NUMBER_RANGES = {
    CONF_SNAPSHOT_DELAY: (1, 300),
    CONF_SNAPSHOT_RETENTION: (1, 365),
    CONF_SNAPSHOT_WIDTH: (64, 800),
    CONF_SNAPSHOT_HEIGHT: (64, 480),
}


@dataclass(frozen=True)
class SnapshotOptions:
    """Validated values used by storage and the frontend."""

    delay_seconds: int = 3
    retention_days: int = 14
    size: tuple[int, int] = (800, 480)
    # Write the capture date and time into the stored image.
    timestamp: bool = True


def snapshot_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """Validate all preferences, including callers bypassing the form schema."""

    result = {key: values.get(key, default) for key, default in SNAPSHOT_DEFAULTS.items()}
    for key, (minimum, maximum) in SNAPSHOT_NUMBER_RANGES.items():
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(key)
        if not minimum <= value <= maximum or value != int(value):
            raise ValueError(key)
        result[key] = int(value)
    if not isinstance(result[CONF_SNAPSHOT_TIMESTAMP], bool):
        raise ValueError(CONF_SNAPSHOT_TIMESTAMP)
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
        size=(values[CONF_SNAPSHOT_WIDTH], values[CONF_SNAPSHOT_HEIGHT]),
        timestamp=values[CONF_SNAPSHOT_TIMESTAMP],
    )
