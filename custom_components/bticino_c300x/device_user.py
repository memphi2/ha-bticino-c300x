"""Safe helpers for the C300X Flexisip media user."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


def homeassistant_account_label(hass: HomeAssistant) -> str:
    """Return the display label written to the C300X account list."""

    config = getattr(hass, "config", None)
    location_name = str(getattr(config, "location_name", "") or "").strip()
    if not location_name or location_name.casefold() == "home assistant":
        return "Home Assistant"
    return f"Home Assistant {location_name}"


def media_user_attributes(entry: ConfigEntry) -> dict[str, Any]:
    """Return safe attributes for the media identity selected by the agent."""

    status = getattr(entry.runtime_data, "device_user_status", {})
    if not isinstance(status, dict) or not status:
        return {}
    if status.get("homeassistant_user_present") is not True:
        return {}
    attributes: dict[str, Any] = {"media_user_account": "homeassistant"}
    label = str(status.get("account_label") or "").strip()
    if label:
        attributes["media_user_label"] = label
    return attributes


def media_user_attribute(entry: ConfigEntry) -> dict[str, Any]:
    """Return one safe nested media-user attribute for compact entities."""

    attributes = media_user_attributes(entry)
    media_user: dict[str, Any] = {}
    if account := attributes.get("media_user_account"):
        media_user["account"] = account
    if label := attributes.get("media_user_label"):
        media_user["label"] = label
    if not media_user:
        return {}
    return {"media_user": media_user}
