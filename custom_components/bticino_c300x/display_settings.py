"""The two display settings the station may change from its Integration tab.

The display bridge is not an options writer: only the keys below, only the
values listed for each, and only through the authenticated display webhook.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_DASHBOARD_NAVIGATION,
    CONF_DASHBOARD_PREVENT_RETURN,
    DASHBOARD_NAVIGATION_PAGER,
    DASHBOARD_NAVIGATION_TABS,
)
from .dashboard_config import (
    configured_dashboard_navigation,
    configured_dashboard_prevent_return,
)
from .entry_types import BticinoC300XConfigEntry

_ALLOWED: dict[str, dict[str, Any]] = {
    CONF_DASHBOARD_PREVENT_RETURN: {"on": True, "off": False},
    CONF_DASHBOARD_NAVIGATION: {
        DASHBOARD_NAVIGATION_PAGER: DASHBOARD_NAVIGATION_PAGER,
        DASHBOARD_NAVIGATION_TABS: DASHBOARD_NAVIGATION_TABS,
    },
}
DISPLAY_SETTING_KEYS = frozenset(_ALLOWED)


def _manifest_version() -> str:
    try:
        manifest = json.loads(Path(__file__).with_name("manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(manifest.get("version") or "") if isinstance(manifest, dict) else ""


INTEGRATION_VERSION = _manifest_version()


def display_settings(entry: BticinoC300XConfigEntry) -> dict[str, Any]:
    """Return the stored values the way the display reads them."""

    return {
        "preventReturnToHomepage": configured_dashboard_prevent_return(entry),
        "navigation": configured_dashboard_navigation(entry),
    }


def display_status_details(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> dict[str, Any]:
    """Return what the station's Integration tab shows about this side."""

    return {
        **display_settings(entry),
        "integration_version": INTEGRATION_VERSION,
        "instance_name": str(getattr(getattr(hass, "config", None), "location_name", "") or "")[:64],
    }


async def async_set_display_setting(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, key: Any, value: Any
) -> dict[str, Any]:
    """Store one allowed value and answer with what is stored now."""

    values = _ALLOWED.get(key) if isinstance(key, str) else None
    if values is None or not isinstance(value, str) or value not in values:
        raise ValueError("invalid_display_setting")
    stored = values[value]
    if key not in entry.options or entry.options[key] != stored:
        hass.config_entries.async_update_entry(entry, options={**entry.options, key: stored})
    return {"ok": True, **display_settings(entry)}

