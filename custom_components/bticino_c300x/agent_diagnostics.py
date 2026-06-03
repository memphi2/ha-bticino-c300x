"""Runtime write-diagnostics helpers for the C300X device agent."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import (
    C300XAgentApiError,
    C300XAgentApiResponseError,
    normalize_agent_diagnostics,
)
from .capabilities import diagnostics_supported
from .const import SIGNAL_AGENT_DIAGNOSTICS_CHANGED


async def async_refresh_agent_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any] | None:
    """Refresh safe write diagnostics once and notify interested entities."""

    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None or not diagnostics_supported(runtime_data.capabilities):
        return None
    try:
        diagnostics = await runtime_data.api.async_diagnostics()
    except C300XAgentApiError:
        return None
    runtime_data.agent_diagnostics = diagnostics
    runtime_data.agent_diagnostics_updated_at = datetime.now(UTC)
    async_dispatcher_send(hass, SIGNAL_AGENT_DIAGNOSTICS_CHANGED, entry.entry_id)
    from .repair_issues import async_sync_entry_repair_issues

    async_sync_entry_repair_issues(hass, entry)
    return diagnostics


def apply_agent_diagnostics_event(
    hass: HomeAssistant,
    entry: ConfigEntry,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    """Apply write diagnostics carried in a push event without callback recursion."""

    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None or not diagnostics_supported(runtime_data.capabilities):
        return None
    try:
        diagnostics = normalize_agent_diagnostics(data)
    except C300XAgentApiResponseError:
        return None
    runtime_data.agent_diagnostics = diagnostics
    runtime_data.agent_diagnostics_updated_at = datetime.now(UTC)
    async_dispatcher_send(hass, SIGNAL_AGENT_DIAGNOSTICS_CHANGED, entry.entry_id)
    from .repair_issues import async_sync_entry_repair_issues

    async_sync_entry_repair_issues(hass, entry)
    return diagnostics
