"""Display support is a device fact, separate from saved display preferences."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DISPLAY_SUPPORTED = "device_display_supported"


def device_display_support(setup: Mapping[str, Any]) -> bool | None:
    """Return explicit support, leaving older/temporarily offline agents unknown."""

    # Only the C100X: a C300X keeps its display options on every firmware.
    if setup.get("model") == "C100X" or setup.get("display_kind") == "qt5_ondisk":
        return False
    capabilities = setup.get("capabilities", {})
    if not isinstance(capabilities, Mapping):
        return None
    bridge = capabilities.get("display_bridge")
    if isinstance(bridge, Mapping) and isinstance(bridge.get("supported"), bool):
        return bridge["supported"]
    if isinstance(bridge, bool):
        return bridge
    maintenance = capabilities.get("maintenance")
    if isinstance(maintenance, Mapping) and maintenance.get("supported") is True:
        value = maintenance.get("qml_patch")
        if isinstance(value, bool):
            return value
    return None


def entry_display_supported(entry: Any) -> bool:
    """Honor current facts first, then the last confirmed fact across restarts."""

    runtime = getattr(entry, "runtime_data", None)
    info = getattr(runtime, "agent_info", {})
    support = device_display_support({
        **(info if isinstance(info, Mapping) else {}),
        "capabilities": getattr(runtime, "capabilities", {}),
    })
    if support is not None:
        return support
    return getattr(entry, "data", {}).get(DISPLAY_SUPPORTED) is not False


def remember_display_support(hass: Any, entry: Any, setup: Mapping[str, Any]) -> None:
    """Persist only known facts; never erase layouts or change device settings."""

    supported = device_display_support(setup)
    if supported is not None and entry.data.get(DISPLAY_SUPPORTED) is not supported:
        hass.config_entries.async_update_entry(entry, data={**entry.data, DISPLAY_SUPPORTED: supported})
