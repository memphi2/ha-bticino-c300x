"""Pure config-entry identity and discovery endpoint comparisons."""

from __future__ import annotations

from typing import Any

from .const import CONF_AGENT_HOST, CONF_AGENT_PORT, DEFAULT_AGENT_PORT, DOMAIN
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
