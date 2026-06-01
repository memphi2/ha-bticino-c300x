"""Config-entry option helpers for BTicino C300X."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

NON_BLANK_DATA_FALLBACK_KEYS = {
    "agent_host",
    "agent_token",
    "webhook_id",
    "shared_secret",
    "event_webhook_id",
    "event_webhook_token",
}


def entry_config_value(entry: Any, key: str, default: Any = None) -> Any:
    """Return an option override when present, otherwise setup data."""

    data = getattr(entry, "data", {})
    options = getattr(entry, "options", {})
    if isinstance(options, Mapping) and key in options:
        value = options[key]
        if value in (None, ""):
            if key in NON_BLANK_DATA_FALLBACK_KEYS and isinstance(data, Mapping):
                data_value = data.get(key)
                if data_value not in (None, ""):
                    return data_value
            return default
        if isinstance(value, str) and not value.strip():
            if key in NON_BLANK_DATA_FALLBACK_KEYS and isinstance(data, Mapping):
                data_value = data.get(key)
                if isinstance(data_value, str) and data_value.strip():
                    return data_value
                if data_value not in (None, ""):
                    return data_value
            return default
        return value

    return data.get(key, default) if isinstance(data, Mapping) else default


def normalized_update_options(data: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """Return options that cannot hide required setup data with blank values."""

    updated = dict(options)
    for key in NON_BLANK_DATA_FALLBACK_KEYS:
        if key not in updated:
            continue
        value = updated[key]
        data_value = data.get(key)
        if value in (None, "") and data_value not in (None, "") or (
            isinstance(value, str)
            and not value.strip()
            and (
                (isinstance(data_value, str) and data_value.strip())
                or data_value not in (None, "")
            )
        ):
            updated.pop(key)
    return updated
