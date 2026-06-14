"""Controlled legacy MQTT migration helpers."""

from __future__ import annotations

from typing import Any

from .api import (
    C300XAgentApi,
    C300XAgentApiUnsupportedError,
    build_agent_base_url,
)
from .const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    DEFAULT_AGENT_PORT,
)


async def async_migrate_legacy_mqtt_if_available(api: C300XAgentApi) -> dict[str, Any]:
    """Run the one-shot legacy-to-native MQTT migration when the agent supports it."""

    try:
        return await api.async_migrate_legacy_mqtt_to_native()
    except C300XAgentApiUnsupportedError:
        return {"ok": True, "available": False, "skipped": "unsupported"}


async def async_migrate_legacy_mqtt_for_connection(
    hass: Any,
    connection: dict[str, Any],
    *,
    api_token: str,
    maintenance_token: str,
) -> dict[str, Any]:
    """Create a temporary API client and migrate legacy MQTT after bootstrap install."""

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    base_url = build_agent_base_url(
        str(connection.get(CONF_AGENT_HOST, "")),
        int(connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT)),
    )
    api = C300XAgentApi(
        async_get_clientsession(hass),
        base_url,
        api_token,
        maintenance_token=maintenance_token,
    )
    return await async_migrate_legacy_mqtt_if_available(api)
