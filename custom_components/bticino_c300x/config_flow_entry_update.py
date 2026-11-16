"""Atomic entry updates with listener-aware recovery of unloaded entries."""

from typing import Any, cast

from homeassistant.config_entries import ConfigFlowResult


def async_ensure_entry_reload(
    hass: Any, entry: Any, *, changed: bool, had_listeners: bool, force: bool = False,
) -> None:
    """Use the listener snapshot from before an eager listener can unload."""
    if (changed or force) and not (changed and had_listeners):
        hass.config_entries.async_schedule_reload(entry.entry_id)


def async_update_reconfigured_entry(
    flow: Any, entry: Any, data_updates: dict[str, Any], clear_keys: frozenset[str],
) -> ConfigFlowResult:
    """Clear shadowing options and write data in one listener notification."""
    options = {
        key: value for key, value in entry.options.items()
        if key not in clear_keys or key not in data_updates
    }
    changed = options != dict(entry.options) or any(
        entry.data.get(key) != value for key, value in data_updates.items()
    )
    had_listeners = bool(entry.update_listeners)
    result = flow.async_update_and_abort(entry, data_updates=data_updates, options=options)
    async_ensure_entry_reload(flow.hass, entry, changed=changed, had_listeners=had_listeners, force=not had_listeners)
    return cast(ConfigFlowResult, result)
