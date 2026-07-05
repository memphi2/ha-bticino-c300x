"""BTicino C300X Home Assistant integration."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Any

from homeassistant.helpers import config_validation as cv

from .api import C300XAgentApiError, C300XAgentApiUnsupportedError
from .const import (
    CONF_AGENT_HOST,
    CONF_EVENT_WEBHOOK_ID,
    CONF_EVENT_WEBHOOK_TOKEN,
    CONF_SHARED_SECRET,
    CONF_WEBHOOK_ID,
    DOMAIN,
)
from .entry_config import (
    entry_config_value as _entry_config_value,
)
from .entry_config import (
    normalized_update_options,
)
from .entry_types import BticinoC300XConfigEntry
from .runtime_manager import (
    BASE_PLATFORMS,
    CAMERA_PLATFORM,
    C300XRuntimeManager,
    _async_configure_device_activations,
    _async_configure_display_bridge,
    _async_notify_display_bridge_alarm_if_listening,
    _async_refresh_device_user_status,
    _async_refresh_self_test,
    _async_remove_stale_gui_dependent_entities,
    _async_schedule_display_bridge_notify,
    _async_start_setup_recovery,
    _async_sync_device_ui_patch,
    _async_sync_device_user,
    _async_track_display_bridge_updates,
    _entry_activation_config,
    _entry_platforms,
    _offline_setup_data,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

__all__ = (
    "BASE_PLATFORMS",
    "CAMERA_PLATFORM",
    "C300XAgentApiError",
    "C300XAgentApiUnsupportedError",
    "C300XRuntimeManager",
    "_async_configure_device_activations",
    "_async_configure_display_bridge",
    "_async_notify_display_bridge_alarm_if_listening",
    "_async_refresh_device_user_status",
    "_async_refresh_self_test",
    "_async_remove_stale_gui_dependent_entities",
    "_async_schedule_display_bridge_notify",
    "_async_start_setup_recovery",
    "_async_sync_device_ui_patch",
    "_async_sync_device_user",
    "_async_track_display_bridge_updates",
    "_entry_activation_config",
    "_entry_config_value",
    "_entry_platforms",
    "_offline_setup_data",
    "async_migrate_entry",
    "async_setup",
    "async_setup_entry",
    "async_unload_entry",
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration domain."""

    from .blueprint_installer import async_install_bundled_blueprints
    from .camera import async_register_home_call_ws
    from .frontend import async_setup_frontend
    from .services import async_setup_services

    hass.data.setdefault(DOMAIN, {})
    await async_install_bundled_blueprints(hass)
    await async_setup_frontend(hass)
    await async_setup_services(hass)
    async_register_home_call_ws(hass)
    return True


async def async_migrate_entry(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> bool:
    """Normalize existing entries before Home Assistant sets them up."""

    data = dict(getattr(entry, "data", {}) or {})
    options = normalized_update_options(data, dict(getattr(entry, "options", {}) or {}))
    original_data = dict(data)
    original_options = dict(getattr(entry, "options", {}) or {})

    if not str(data.get(CONF_AGENT_HOST, "") or "").strip() and data.get("controller_host"):
        data[CONF_AGENT_HOST] = data["controller_host"]

    _ensure_generated_setup_secret(data, CONF_WEBHOOK_ID, 24)
    _ensure_generated_setup_secret(data, CONF_SHARED_SECRET, 32)
    _ensure_generated_setup_secret(data, CONF_EVENT_WEBHOOK_ID, 24)
    _ensure_generated_setup_secret(data, CONF_EVENT_WEBHOOK_TOKEN, 32)

    if (
        data != original_data
        or options != original_options
        or getattr(entry, "minor_version", 1) < 2
    ):
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            options=options,
            version=1,
            minor_version=2,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> bool:
    """Set up a C300X config entry."""

    return await C300XRuntimeManager(hass, entry).async_prepare()


def _ensure_generated_setup_secret(
    data: dict[str, Any],
    key: str,
    token_bytes: int,
) -> None:
    """Generate a setup secret when an older config entry does not have one."""

    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return
    if value not in (None, ""):
        return
    data[key] = secrets.token_urlsafe(token_bytes)


async def async_unload_entry(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> bool:
    """Unload a C300X config entry."""

    return await C300XRuntimeManager(hass, entry).async_unload()
