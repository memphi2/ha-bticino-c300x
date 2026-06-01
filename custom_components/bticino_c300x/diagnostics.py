"""Diagnostics for BTicino C300X."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACTIONS,
    CONF_AGENT_HOST,
    CONF_AGENT_TOKEN,
    CONF_ALARM_ENTITY_ID,
    CONF_DASHBOARD_ENTITIES,
    CONF_EVENT_WEBHOOK_ID,
    CONF_MAINTENANCE_TOKEN,
    CONF_STAIR_LIGHT_ADDRESS,
    CONF_WEBHOOK_ID,
)
from .entity import entry_config_value, entry_video_enabled


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict:
    """Return safe diagnostics without secrets."""

    actions = entry.options.get(CONF_ACTIONS, {})
    dashboard_entities = entry_config_value(entry, CONF_DASHBOARD_ENTITIES, [])
    return {
        "entry_title_configured": bool(entry.title),
        "agent_configured": bool(entry_config_value(entry, CONF_AGENT_HOST, "")),
        "agent_token_configured": bool(entry_config_value(entry, CONF_AGENT_TOKEN, "")),
        "maintenance_token_configured": bool(
            entry_config_value(entry, CONF_MAINTENANCE_TOKEN, "")
        ),
        "webhook_configured": bool(entry.data.get(CONF_WEBHOOK_ID)),
        "event_webhook_configured": bool(entry.data.get(CONF_EVENT_WEBHOOK_ID)),
        "video_enabled": entry_video_enabled(entry),
        "stair_light_configured": bool(
            entry_config_value(entry, CONF_STAIR_LIGHT_ADDRESS, "")
        ),
        "alarm_entity_configured": bool(
            entry.options.get(
                CONF_ALARM_ENTITY_ID,
                entry.data.get(CONF_ALARM_ENTITY_ID, ""),
            )
        ),
        "action_count": len(actions) if isinstance(actions, dict) else 0,
        "action_ids_configured": bool(actions),
        "dashboard_entity_count": len(dashboard_entities)
        if isinstance(dashboard_entities, list)
        else 0,
        "qml_patch_status": getattr(entry.runtime_data, "qml_patch_status", {}).get(
            "state"
        )
        if hasattr(entry, "runtime_data")
        else None,
        "agent_write_diagnostics": _agent_write_diagnostics(entry),
    }


def _agent_write_diagnostics(entry: ConfigEntry) -> dict | None:
    """Return safe write diagnostics if runtime data is available."""

    if not hasattr(entry, "runtime_data"):
        return None
    diagnostics = getattr(entry.runtime_data, "agent_diagnostics", {})
    if not isinstance(diagnostics, dict):
        return None
    return {
        key: diagnostics.get(key)
        for key in (
            "agent_write_count",
            "last_write_at",
            "last_write_reason",
            "last_write_class",
            "subscription_store_writes",
            "qml_patch_last_action",
            "last_wake_reason",
            "loop_iterations",
            "poll_wakeups",
            "accepted_clients",
            "last_poll_timeout_ms",
            "last_poll_count",
            "open_fd_count",
            "video_running",
            "video_media_starting",
            "video_call_active",
            "video_clients",
            "video_bridge_open_fds",
            "video_bridge_active_threads",
        )
    }
