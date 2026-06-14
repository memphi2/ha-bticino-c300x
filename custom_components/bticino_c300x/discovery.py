"""Discovery helpers for a future C300X mDNS flow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import CONF_AGENT_HOST, CONF_AGENT_PORT, DEFAULT_NAME

C300X_ZEROCONF_TYPE = "_bticino-c300x-agent._tcp.local."
DISCOVERY_ID_KEYS = ("serial", "serialno", "uuid", "id", "mac")
DISCOVERY_NAME_KEYS = ("friendly_name", "display_name", "name", "model")
_GENERIC_DISCOVERY_NAMES = {
    "bticino c300x",
    "bticino c300x agent",
    "c300x",
    "c300x agent",
}


def discovery_unique_id(properties: Mapping[str, Any]) -> str | None:
    """Return a stable unique ID from mDNS TXT properties."""

    normalized = _normalized_properties(properties)
    for key in DISCOVERY_ID_KEYS:
        value = normalized.get(key)
        if value:
            return _normalize_unique_id(value)
    return None


def discovery_display_name(properties: Mapping[str, Any], service_name: Any) -> str:
    """Return a user-facing name for a discovered native agent."""

    normalized = _normalized_properties(properties)
    for key in DISCOVERY_NAME_KEYS:
        value = _clean_display_name(normalized.get(key, ""))
        if value:
            return value

    value = _clean_display_name(_to_text(service_name))
    return value or DEFAULT_NAME


def discovery_connection_updates(host: str, port: int) -> dict[str, str | int]:
    """Return config-entry connection updates from trusted discovery info."""

    clean_host = host.strip()
    if not clean_host:
        raise ValueError("discovery host is empty")
    clean_port = int(port)
    if clean_port <= 0 or clean_port > 65535:
        raise ValueError("discovery port is outside TCP range")
    return {
        CONF_AGENT_HOST: clean_host,
        CONF_AGENT_PORT: clean_port,
    }


def discovery_matches_entry(unique_id: str | None, entry_unique_id: str | None) -> bool:
    """Return true when a discovery identity matches an existing entry."""

    if unique_id is None or entry_unique_id is None:
        return False
    return _normalize_unique_id(unique_id) == _normalize_unique_id(entry_unique_id)


def _normalized_properties(properties: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_key, raw_value in properties.items():
        key = _to_text(raw_key).strip().lower()
        value = _to_text(raw_value).strip()
        if key and value:
            result[key] = value
    return result


def _to_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def _clean_display_name(value: str) -> str:
    clean = value.strip()
    if not clean:
        return ""
    suffix = f".{C300X_ZEROCONF_TYPE}"
    if clean.lower().endswith(suffix):
        clean = clean[: -len(suffix)]
    clean = clean.removesuffix(".local.").removesuffix(".local").strip(" .")
    clean = " ".join(clean.replace("_", " ").split())
    if clean.lower() in _GENERIC_DISCOVERY_NAMES:
        return DEFAULT_NAME
    return clean


def _normalize_unique_id(value: str) -> str:
    return value.strip().replace(":", "").replace("-", "").lower()
