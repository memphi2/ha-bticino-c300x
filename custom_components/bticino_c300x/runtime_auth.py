"""Authentication recovery for an already loaded entry."""

from homeassistant.core import HomeAssistant, callback

from .api import C300XAgentApi
from .api_errors import (
    C300XAgentApiAuthError,
    C300XAgentApiError,
    C300XAgentApiResponseError,
)
from .data import C300XConnectionState
from .entry_types import BticinoC300XConfigEntry
from .error_text import compact_error_text


async def async_classify_runtime_auth_error(
    api: C300XAgentApi, error: C300XAgentApiAuthError,
) -> C300XAgentApiError:
    """Maintenance 403 also means policy-disabled, not necessarily a bad key."""

    if not error.maintenance:
        return error
    try:
        await api.async_validate_maintenance_auth()
    except C300XAgentApiAuthError as rejected:
        return rejected
    except C300XAgentApiError:
        return C300XAgentApiResponseError("maintenance access denied; credentials could not be checked")
    return C300XAgentApiResponseError("maintenance operation is not permitted")


REAUTH_MAINTENANCE = "maintenance_key_rejected"


@callback
def async_request_maintenance_reauth(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    """Ask for a new maintenance key and leave the entry online.

    Calls, video, door and events use the access key, which still works. Only
    the maintenance actions fail until the key is replaced.
    """

    entry.async_start_reauth(hass, data={REAUTH_MAINTENANCE: True})


@callback
def async_request_reauth(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    connection_state: C300XConnectionState,
    error: C300XAgentApiAuthError,
) -> None:
    """Stop treating rejected credentials as a recoverable network outage."""

    connection_state.authentication_failed = False
    connection_state.mark_reconnecting(
        "maintenance_auth" if error.maintenance else "agent_auth", 0,
        compact_error_text(error),
    )
    connection_state.authentication_failed = True
    connection_state.mark_unavailable()
    connection_state.next_reconnect_delay_seconds = None
    if connection_state.expire_unavailable is not None:
        connection_state.expire_unavailable()
        connection_state.expire_unavailable = None
    # HA deduplicates against reauth and reconfigure flows for this entry.
    entry.async_start_reauth(hass)
