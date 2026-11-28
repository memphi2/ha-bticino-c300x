"""Setup probes against the device agent, kept apart from the flow steps."""

from __future__ import annotations

from typing import Any, cast

from .api import (
    C300XAgentApi,
    C300XAgentApiAuthError,
    C300XAgentApiError,
    C300XAgentApiUnsupportedError,
    build_agent_base_url,
)
from .const import CONF_AGENT_HOST, CONF_AGENT_PORT, DEFAULT_AGENT_PORT


async def async_agent_setup_data(
    hass: Any,
    connection: dict[str, Any],
    *,
    api_token: str = "",
) -> dict[str, Any]:
    """Return setup data from the configured agent endpoint."""

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    base_url = build_agent_base_url(
        str(connection.get(CONF_AGENT_HOST, "")),
        int(connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT)),
    )
    api = C300XAgentApi(async_get_clientsession(hass), base_url, api_token)
    return cast(dict[str, Any], await api.async_validate_setup())


async def async_agent_ready_for_setup(
    hass: Any,
    connection: dict[str, Any],
    *,
    api_token: str = "",
) -> dict[str, Any]:
    """Validate the agent endpoints required for a usable config entry."""

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    base_url = build_agent_base_url(
        str(connection.get(CONF_AGENT_HOST, "")),
        int(connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT)),
    )
    api = C300XAgentApi(async_get_clientsession(hass), base_url, api_token)
    setup_data = cast(dict[str, Any], await api.async_validate_setup())
    try:
        await api.async_self_test()
    except C300XAgentApiAuthError:
        raise
    except C300XAgentApiUnsupportedError:
        pass
    except C300XAgentApiError:
        pass
    await api.async_list_event_subscriptions()
    return setup_data
