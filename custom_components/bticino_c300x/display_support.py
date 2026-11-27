"""Display support is a device fact, separate from saved display preferences."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import CONF_DEVICE_UI_ENABLED
from .device_profile import entry_profile, setup_profile

DISPLAY_SUPPORTED = "device_display_supported"


def device_display_support(setup: Mapping[str, Any]) -> bool | None:
    """Return explicit support, leaving older/temporarily offline agents unknown."""

    capabilities = setup.get("capabilities", {})
    # Only the C100X: a C300X keeps its display options on every firmware.
    if _c100x(setup):
        # Its pages count once the agent confirmed them in their trial boot.
        status = capabilities.get("c100x_display") if isinstance(capabilities, Mapping) else None
        if not isinstance(status, Mapping):
            return False
        if status.get("status_known") is False:
            return None
        bridge = capabilities.get("display_bridge")
        return (status.get("confirmed") is True and isinstance(bridge, Mapping)
                and bridge.get("supported") is True)
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


def _c100x(setup: Mapping[str, Any]) -> bool:
    return setup_profile(setup).is_c100x


def setup_is_c100x(setup: Any) -> bool:
    """Return whether agent setup data names a C100X."""

    return isinstance(setup, Mapping) and _c100x(setup)


def setup_display_pages_default(setup: Mapping[str, Any]) -> bool:
    """Whether a new entry offers the Home Assistant display pages switched on.

    Only a C300X whose agent confirms its display: the C100X activates its
    pages separately with a reboot, and an unknown display stays off.
    """

    return not _c100x(setup) and device_display_support(setup) is True


def entry_is_c100x(entry: Any) -> bool:
    """Return whether the loaded entry's agent reported a C100X."""

    return entry_profile(entry).is_c100x


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
    if supported is None or entry.data.get(DISPLAY_SUPPORTED) is supported:
        return
    data = {**entry.data, DISPLAY_SUPPORTED: supported}
    if supported and _c100x(setup):
        # The C100X pages were just confirmed on the device: the setting
        # follows, so the pages, notifications and bridge start with them.
        hass.config_entries.async_update_entry(
            entry, data=data, options={**entry.options, CONF_DEVICE_UI_ENABLED: True},
        )
        return
    hass.config_entries.async_update_entry(entry, data=data)
