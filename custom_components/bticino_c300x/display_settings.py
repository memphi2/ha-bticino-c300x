"""What the station's Integration tab shows about the Home Assistant side."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .dashboard_config import (
    configured_dashboard_navigation,
    configured_dashboard_prevent_return,
)
from .entry_types import BticinoC300XConfigEntry


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
