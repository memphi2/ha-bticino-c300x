"""Safe helpers for the C300X Flexisip media user."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant

from .entry_types import BticinoC300XConfigEntry


def homeassistant_account_label(hass: HomeAssistant) -> str:
    """Return the display label written to the C300X account list."""

    config = getattr(hass, "config", None)
    location_name = str(getattr(config, "location_name", "") or "").strip()
    if not location_name or location_name.casefold() == "home assistant":
        return "Home Assistant"
    return f"Home Assistant {location_name}"


def device_user_status_available(status: Mapping[str, Any]) -> bool:
    """Return whether a device-user status payload is usable."""

    return status.get("available") is not False and status.get("status_available") is not False


def device_user_bootstrap_needed(status: Mapping[str, Any]) -> bool:
    """Return true for a hard missing media-user/routing status."""

    if not device_user_status_available(status):
        return False
    if status.get("homeassistant_user_present") is False:
        return True
    if status.get("media_identity_available") is False:
        return True
    if status.get("routes_consistent") is False:
        return True
    return (
        status.get("homeassistant_user_present") is True
        and "device_routing_applied" in status
        and status.get("device_routing_applied") is False
    )


def device_user_bootstrap_satisfied(status: Mapping[str, Any]) -> bool:
    """Return true when startup can mark the one-time bootstrap as done."""

    if not device_user_status_available(status):
        return False
    return (
        status.get("homeassistant_user_present") is True
        and status.get("media_identity_available") is not False
        and status.get("routes_consistent") is not False
        and status.get("device_routing_applied") is not False
    )


def device_user_ready(status: Mapping[str, Any]) -> bool | None:
    """Return whether the dedicated media user and route state are ready."""

    if not device_user_status_available(status):
        return None
    present = status.get("homeassistant_user_present")
    media_identity = status.get("media_identity_available")
    routes = status.get("routes_consistent")
    routing = status.get("device_routing_applied")
    if (
        present is None
        and media_identity is None
        and routes is None
        and routing is None
    ):
        return None
    return (
        present is True
        and media_identity is not False
        and routes is not False
        and routing is not False
    )


def device_user_repair_reason(status: Mapping[str, Any]) -> str | None:
    """Return the stable repair reason for a broken media-user status."""

    if not device_user_status_available(status):
        return None
    if status.get("homeassistant_user_present") is False:
        return "homeassistant_user_missing"
    if status.get("routes_consistent") is False:
        return "homeassistant_routes_inconsistent"
    if status.get("media_identity_available") is False:
        return "media_identity_missing"
    if (
        status.get("homeassistant_user_present") is True
        and "device_routing_applied" in status
        and status.get("device_routing_applied") is False
    ):
        return "device_routing_missing"
    return None


def media_user_attributes(entry: BticinoC300XConfigEntry) -> dict[str, Any]:
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


def media_user_attribute(entry: BticinoC300XConfigEntry) -> dict[str, Any]:
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
