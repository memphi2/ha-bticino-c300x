"""Config-entry identity checks and authenticated discovery adoption."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from .api_errors import C300XAgentApiError
from .const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_MAINTENANCE_TOKEN,
    DEFAULT_AGENT_PORT,
    DOMAIN,
)
from .discovery import discovery_matches_entry, discovery_model_conflicts
from .entry_config import entry_config_value
from .entry_types import BticinoC300XConfigEntry


def reconfigure_unique_id(entry: BticinoC300XConfigEntry) -> str:
    """Keep the existing identity during reconfiguration."""
    return str(getattr(entry, "unique_id", None) or DOMAIN)


def normalize_discovery_host(host: str) -> str:
    """Normalize a host name for local discovery comparisons."""
    return host.strip().lower().rstrip(".")


def manual_setup_unique_id(connection: dict[str, Any]) -> str:
    """Return the deterministic fallback identity for manual setup."""
    host = normalize_discovery_host(str(connection.get(CONF_AGENT_HOST, "")))
    port = int(connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT))
    return f"{DOMAIN}:{host}:{port}" if host else DOMAIN


def entry_uses_manual_setup_unique_id(entry: BticinoC300XConfigEntry) -> bool:
    """Identify entries that still have a host-based setup identity."""
    unique_id = str(getattr(entry, "unique_id", "") or "")
    return unique_id == DOMAIN or unique_id.startswith(f"{DOMAIN}:")


def entry_connection_matches_discovery(
    entry: BticinoC300XConfigEntry, connection: dict[str, Any],
) -> bool:
    """Compare the effective configured endpoint with an advertised endpoint."""
    host = normalize_discovery_host(str(entry_config_value(entry, CONF_AGENT_HOST, "") or ""))
    advertised = normalize_discovery_host(str(connection.get(CONF_AGENT_HOST, "")))
    return bool(host and host == advertised) and int(
        entry_config_value(entry, CONF_AGENT_PORT, DEFAULT_AGENT_PORT)
    ) == int(connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT))


def stable_unique_id_from_setup_data(setup_data: dict[str, Any]) -> str | None:
    """Return the normalized agent identity when setup data advertises one."""
    from .discovery import discovery_unique_id

    device_id = setup_data.get("device_id")
    return discovery_unique_id({"id": device_id}) if device_id else None


def entry_identity_connection(entry: BticinoC300XConfigEntry) -> dict[str, Any]:
    """Snapshot the effective endpoint and credentials, not unrelated settings."""
    return {
        key: entry_config_value(entry, key, default)
        for key, default in (
            (CONF_AGENT_HOST, ""), (CONF_AGENT_PORT, DEFAULT_AGENT_PORT),
            (CONF_AGENT_TOKEN, ""), (CONF_MAINTENANCE_TOKEN, ""),
        )
    }



async def async_adopt_discovery_identity(
    hass: Any,
    entry: BticinoC300XConfigEntry,
    read_setup: Callable[..., Awaitable[dict[str, Any]]],
    current_entries: Callable[[], list[BticinoC300XConfigEntry]],
) -> None:
    """Treat discovery only as a hint to read the already trusted endpoint."""
    saved = entry_identity_connection(entry)
    saved_id = entry.unique_id
    if not saved[CONF_AGENT_TOKEN]:
        return
    try:
        setup = await read_setup(hass, saved, api_token=saved[CONF_AGENT_TOKEN])
    except C300XAgentApiError:
        return
    actual = stable_unique_id_from_setup_data(setup)
    if (
        actual is None
        or saved != entry_identity_connection(entry)
        or saved_id != entry.unique_id
        or entry not in (entries := current_entries())
        or any(
            other is not entry and discovery_matches_entry(actual, other.unique_id)
            for other in entries
        )
    ):
        return
    hass.config_entries.async_update_entry(entry, unique_id=actual)


async def async_existing_manual_discovery(
    flow: Any,
    discovered_unique_id: str | None,
    connection: dict[str, Any],
    matches: Callable[[str | None, str | None], bool],
    read_setup: Callable[..., Awaitable[dict[str, Any]]],
    *,
    model: str = "",
) -> dict[str, Any] | None:
    """Deduplicate discovery and adopt only identity read from the saved endpoint."""
    if discovered_unique_id is None:
        return None
    current_entries = getattr(flow, "_async_current_entries", None)
    if current_entries is None:
        return None
    for entry in current_entries():
        entry_unique_id = str(getattr(entry, "unique_id", "") or "")
        if matches(discovered_unique_id, entry_unique_id):
            return None
        if not entry_uses_manual_setup_unique_id(entry):
            continue
        if not entry_connection_matches_discovery(entry, connection):
            continue
        if discovery_model_conflicts(entry, model):
            continue
        runtime = getattr(entry, "runtime_data", None)
        resources = getattr(runtime, "resources", None)
        await async_adopt_discovery_identity(flow.hass, entry, read_setup, current_entries)
        # Unload closes resources before HA removes runtime_data. A discovery
        # read must not attach new work to that closed or replaced lifetime.
        if (
            runtime is not None and resources is not None and not resources.closed
            and getattr(entry, "runtime_data", None) is runtime
            and getattr(runtime, "resources", None) is resources
            and entry in current_entries()
        ):
            flow._async_request_event_registration(entry)
        return cast(dict[str, Any], flow.async_abort(reason="already_configured"))
    return None
