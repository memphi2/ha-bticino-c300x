"""Diagnostics for BTicino C300X."""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .callback_target import (
    callback_address_type,
    callback_host_type,
    callback_target_is_clean_local_http,
    clean_callback_host,
)
from .const import (
    CONF_ACTIONS,
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_ALARM_ENTITY_ID,
    CONF_CALLBACK_BASE_URL,
    CONF_DASHBOARD_ENTITIES,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS,
    CONF_EVENT_WEBHOOK_ID,
    CONF_MAINTENANCE_TOKEN,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    CONF_WEATHER_ENTITY_ID,
    CONF_WEBHOOK_ID,
    DEFAULT_AGENT_PORT,
)
from .device_installer import installer_bundle_status
from .entity import entry_config_value, entry_video_enabled
from .fingerprint import fnv1a64_fingerprint

_SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "username",
    "host",
    "url",
    "webhook",
    "entity_id",
    "device_id",
    "path",
)
_SAFE_AGENT_DIAGNOSTIC_KEYS = (
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
    "agent_init_script_present",
    "agent_init_link_ok",
    "subscription_count",
    "recent_event_count",
    "recent_event_capacity",
    "display_bridge_registered",
    "display_bridge_disabled",
    "home_assistant_connected_this_run",
    "home_assistant_last_seen_at",
    "ui_event_revision",
    "video_running",
    "video_media_starting",
    "video_call_active",
    "video_clients",
    "video_bridge_open_fds",
    "video_bridge_active_threads",
    "flexisip_backup_available",
    "flexisip_restart_marker",
    "flexisip_backup_marker",
    "flexisip_reference_state",
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict:
    """Return safe diagnostics without secrets."""

    actions = entry.options.get(CONF_ACTIONS, {})
    dashboard_entities = entry_config_value(entry, CONF_DASHBOARD_ENTITIES, [])
    runtime = getattr(entry, "runtime_data", None)
    network = await _async_network_diagnostics(hass, entry)
    bundle_status = await _async_installer_bundle_status(hass)
    return {
        "entry": _entry_diagnostics(entry),
        "configuration": {
            "agent_configured": bool(entry_config_value(entry, CONF_AGENT_HOST, "")),
            "agent_endpoint": network["agent_endpoint"],
            "agent_token_configured": bool(
                entry_config_value(entry, CONF_AGENT_TOKEN, "")
            ),
            "maintenance_token_configured": bool(
                entry_config_value(entry, CONF_MAINTENANCE_TOKEN, "")
            ),
            "webhook_configured": bool(entry.data.get(CONF_WEBHOOK_ID)),
            "event_webhook_configured": bool(entry.data.get(CONF_EVENT_WEBHOOK_ID)),
            "video_enabled": entry_video_enabled(entry),
            "video_port_configured": bool(
                entry_config_value(entry, CONF_VIDEO_PORT, "")
            ),
            "video_stream_path_configured": bool(
                entry_config_value(entry, CONF_VIDEO_STREAM_PATH, "")
            ),
            "stair_light_configured": bool(
                entry_config_value(entry, CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS, "")
            ),
            "alarm_entity_configured": bool(_configured_alarm_entity(entry)),
            "weather_entity_configured": bool(_configured_weather_entity(entry)),
            "action_count": len(actions) if isinstance(actions, dict) else 0,
            "action_ids_configured": bool(actions),
            "dashboard_entity_count": len(dashboard_entities)
            if isinstance(dashboard_entities, list)
            else 0,
            "dashboard_entity_domains": _entity_domain_counts(dashboard_entities),
        },
        "network": network,
        "installation": _installation_diagnostics(runtime, bundle_status),
        "runtime": {
            "loaded": runtime is not None,
            "loaded_platforms": list(getattr(runtime, "loaded_platforms", ()) or ()),
            "connection": _connection_diagnostics(runtime),
            "agent": _agent_info_diagnostics(runtime),
            "capabilities": _capability_diagnostics(runtime),
            "update": _agent_update_diagnostics(runtime),
            "event_state": _event_state_diagnostics(runtime),
            "caches": _cache_diagnostics(runtime),
            "system_metrics": _safe_system_metrics(runtime),
            "display_bridge": _operation_diagnostics(
                getattr(runtime, "display_bridge_diagnostics", None)
            ),
            "qml_patch": _safe_status_dict(
                getattr(runtime, "qml_patch_status", {}) if runtime is not None else {}
            ),
            "qml_patch_check": _operation_diagnostics(
                getattr(runtime, "qml_patch_diagnostics", None)
            ),
        },
        "agent_write_diagnostics": _agent_write_diagnostics(entry),
    }


def _entry_diagnostics(entry: ConfigEntry) -> dict[str, Any]:
    return {
        "title_configured": bool(getattr(entry, "title", "")),
        "entry_id_fingerprint": fnv1a64_fingerprint(str(getattr(entry, "entry_id", ""))),
        "version": getattr(entry, "version", None),
        "minor_version": getattr(entry, "minor_version", None),
        "disabled_by": str(getattr(entry, "disabled_by", "") or "") or None,
        "state": str(getattr(entry, "state", "") or "") or None,
    }


def _agent_write_diagnostics(entry: ConfigEntry) -> dict | None:
    """Return safe write diagnostics if runtime data is available."""

    if not hasattr(entry, "runtime_data"):
        return None
    diagnostics = getattr(entry.runtime_data, "agent_diagnostics", {})
    if not isinstance(diagnostics, dict):
        return None
    return {key: diagnostics.get(key) for key in _SAFE_AGENT_DIAGNOSTIC_KEYS}


def _connection_diagnostics(runtime: Any | None) -> dict[str, Any] | None:
    if runtime is None:
        return None
    state = getattr(runtime, "connection_state", None)
    if state is None:
        return None
    return {
        "available": getattr(state, "available", None),
        "state": getattr(state, "connection_state", None),
        "reconnect_count": getattr(state, "reconnect_count", None),
        "last_connection_stage": getattr(state, "last_connection_stage", None),
        "last_reconnect_reason": getattr(state, "last_reconnect_reason", None),
        "last_connection_error": _safe_error_summary(
            getattr(state, "last_connection_error", None)
        ),
        "next_reconnect_delay_seconds": getattr(
            state,
            "next_reconnect_delay_seconds",
            None,
        ),
        "event_subscription": {
            "id_configured": bool(getattr(state, "event_subscription_id", None)),
            "event_count": getattr(state, "event_subscription_event_count", None),
            "callback_scheme": getattr(
                state,
                "event_subscription_callback_scheme",
                None,
            ),
            "callback_host_type": getattr(
                state,
                "event_subscription_callback_host_type",
                None,
            ),
            "callback_is_clean_local_http": _subscription_callback_is_clean(state),
            "last_attempt_at": _isoformat(
                getattr(state, "event_subscription_last_attempt_at", None)
            ),
            "last_success_at": _isoformat(
                getattr(state, "event_subscription_last_success_at", None)
            ),
            "last_failure_at": _isoformat(
                getattr(state, "event_subscription_last_failure_at", None)
            ),
            "last_error": _safe_error_summary(
                getattr(state, "event_subscription_last_error", None)
            ),
        },
    }


def _operation_diagnostics(operation: Any | None) -> dict[str, Any] | None:
    if operation is None:
        return None
    data: dict[str, Any] = {
        "last_attempt_at": _isoformat(getattr(operation, "last_attempt_at", None)),
        "last_success_at": _isoformat(getattr(operation, "last_success_at", None)),
        "last_failure_at": _isoformat(getattr(operation, "last_failure_at", None)),
        "last_error": _safe_error_summary(getattr(operation, "last_error", None)),
    }
    if hasattr(operation, "callback_scheme") or hasattr(operation, "callback_host_type"):
        scheme = getattr(operation, "callback_scheme", None)
        host_type = getattr(operation, "callback_host_type", None)
        data.update(
            {
                "callback_scheme": scheme,
                "callback_host_type": host_type,
                "callback_is_clean_local_http": callback_target_is_clean_local_http(
                    scheme,
                    host_type,
                ),
            }
        )
    return data


async def _async_network_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    host = str(entry_config_value(entry, CONF_AGENT_HOST, "") or "").strip()
    try:
        port = int(entry_config_value(entry, CONF_AGENT_PORT, DEFAULT_AGENT_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_AGENT_PORT
    endpoint = {
        "host_configured": bool(host),
        "host_type": callback_host_type(host),
        "host_is_private_address": _host_private_address(host),
        "port": port,
    }
    callback_base_url = str(
        entry_config_value(entry, CONF_CALLBACK_BASE_URL, "") or ""
    ).strip()
    callback_override = _callback_base_url_diagnostics(callback_base_url)
    if not host:
        return {
            "agent_endpoint": endpoint,
            "callback_base_url_override": callback_override,
            "route": None,
            "same_lan_prefix_guess": None,
            "subscription_callback_expected": "http_local_reachable",
        }
    async_add_executor_job = getattr(hass, "async_add_executor_job", None)
    if callable(async_add_executor_job):
        route = await async_add_executor_job(_route_diagnostics, host, port)
    else:
        route = _route_diagnostics(host, port)
    return {
        "agent_endpoint": endpoint,
        "callback_base_url_override": callback_override,
        "route": route,
        "same_lan_prefix_guess": route.get("same_lan_prefix_guess")
        if isinstance(route, dict)
        else None,
        "subscription_callback_expected": "http_local_reachable",
    }


def _callback_base_url_diagnostics(value: str) -> dict[str, Any]:
    parts = urlsplit(value)
    scheme = parts.scheme.strip().lower() or None
    host_type = callback_host_type(parts.hostname)
    return {
        "configured": bool(value),
        "scheme": scheme,
        "host_type": host_type,
        "is_clean_local_http": callback_target_is_clean_local_http(
            scheme,
            host_type,
        )
        if value
        else None,
    }


def _route_diagnostics(host: str, port: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "resolved": False,
        "selected_source_type": None,
        "selected_target_type": None,
        "same_lan_prefix_guess": None,
        "error": None,
    }
    try:
        candidates = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
    except OSError as err:
        result["error"] = type(err).__name__
        return result
    result["resolved"] = bool(candidates)
    for family, socktype, proto, _canonname, sockaddr in candidates:
        with socket.socket(family, socktype, proto) as sock:
            try:
                sock.connect(sockaddr)
                source = str(sock.getsockname()[0]).split("%", 1)[0]
                target = str(sockaddr[0]).split("%", 1)[0]
            except OSError:
                continue
        source_ip = _ip_address(source)
        target_ip = _ip_address(target)
        result["selected_source_type"] = callback_address_type(source_ip)
        result["selected_target_type"] = callback_address_type(target_ip)
        result["same_lan_prefix_guess"] = _same_lan_prefix_guess(source_ip, target_ip)
        return result
    result["error"] = "no_usable_route"
    return result


async def _async_installer_bundle_status(hass: HomeAssistant) -> dict[str, Any]:
    async_add_executor_job = getattr(hass, "async_add_executor_job", None)
    if callable(async_add_executor_job):
        return await async_add_executor_job(installer_bundle_status)
    return installer_bundle_status()


def _installation_diagnostics(
    runtime: Any | None,
    bundle_status: dict[str, Any],
) -> dict[str, Any]:
    connection = _connection_diagnostics(runtime)
    update = _agent_update_diagnostics(runtime)
    return {
        "packaged_agent_bundle_available": bool(bundle_status.get("available")),
        "packaged_agent_bundle_reason": bundle_status.get("reason"),
        "packaged_agent_payload_count": len(bundle_status.get("payloads", []))
        if isinstance(bundle_status.get("payloads"), list)
        else None,
        "runtime_loaded": runtime is not None,
        "agent_reachable": connection.get("available") if connection else None,
        "event_subscription_endpoint_usable": (
            connection.get("event_subscription", {}).get("last_success_at") is not None
            if connection
            else None
        ),
        "agent_update_state": update.get("state") if update else None,
        "agent_update_reason": update.get("reason") if update else None,
    }


def _agent_info_diagnostics(runtime: Any | None) -> dict[str, Any] | None:
    if runtime is None:
        return None
    info = getattr(runtime, "agent_info", {})
    if not isinstance(info, Mapping):
        return None
    device_id = info.get("device_id")
    return {
        "version": info.get("version"),
        "implementation": info.get("implementation"),
        "api_version": info.get("api_version"),
        "model": info.get("model"),
        "firmware": info.get("firmware"),
        "device_id_configured": bool(device_id),
        "device_id_fingerprint": fnv1a64_fingerprint(str(device_id))
        if device_id
        else None,
    }


def _capability_diagnostics(runtime: Any | None) -> dict[str, Any] | None:
    if runtime is None:
        return None
    capabilities = getattr(runtime, "capabilities", {})
    if not isinstance(capabilities, Mapping):
        return None
    return {
        str(key): _safe_capability_value(value)
        for key, value in sorted(capabilities.items())
    }


def _safe_capability_value(value: Any) -> Any:
    if isinstance(value, bool):
        return {"supported": value}
    if isinstance(value, Mapping):
        return {
            str(key): item
            for key, item in sorted(value.items())
            if isinstance(item, bool | int | float) or item is None
        }
    return {"configured": value is not None}


def _agent_update_diagnostics(runtime: Any | None) -> dict[str, Any] | None:
    if runtime is None:
        return None
    update_state = getattr(runtime, "agent_update_state", None)
    if update_state is None:
        return None
    installed_bundle_hash = getattr(update_state, "installed_bundle_hash", None)
    available_bundle_hash = getattr(update_state, "available_bundle_hash", None)
    return {
        "state": getattr(update_state, "state", None),
        "reason": getattr(update_state, "reason", None),
        "update_required": getattr(update_state, "update_required", None),
        "repair_fixable": getattr(update_state, "repair_fixable", None),
        "self_update_supported": getattr(update_state, "self_update_supported", None),
        "installed_version": getattr(update_state, "installed_version", None),
        "available_version": getattr(update_state, "available_version", None),
        "installed_api_version": getattr(update_state, "installed_api_version", None),
        "available_api_version": getattr(update_state, "available_api_version", None),
        "installed_bundle_hash_configured": bool(installed_bundle_hash),
        "available_bundle_hash_configured": bool(available_bundle_hash),
        "bundle_hash_match": (
            installed_bundle_hash == available_bundle_hash
            if installed_bundle_hash and available_bundle_hash
            else None
        ),
    }


def _event_state_diagnostics(runtime: Any | None) -> dict[str, Any] | None:
    if runtime is None:
        return None
    state = getattr(runtime, "event_state", None)
    if state is None:
        return None
    return {
        "event_sequence": getattr(state, "event_sequence", None),
        "last_event": getattr(state, "last_event", None),
        "last_event_time": getattr(state, "last_event_time", None),
        "video_available": getattr(state, "video_available", None),
        "video_active_until": getattr(state, "video_active_until", None),
        "call_active": getattr(state, "call_active", None),
        "smartphone_forwarding_known": getattr(
            state,
            "smartphone_forwarding_mode",
            None,
        )
        is not None,
        "ringer_known": getattr(state, "ringer_muted", None) is not None,
        "voicemail_total": getattr(state, "voicemail_total", None),
        "voicemail_unread": getattr(state, "voicemail_unread", None),
        "memos_total": getattr(state, "memos_total", None),
        "memos_unread": getattr(state, "memos_unread", None),
    }


def _cache_diagnostics(runtime: Any | None) -> dict[str, Any] | None:
    if runtime is None:
        return None
    messages = getattr(runtime, "answering_machine_messages", {})
    memos = getattr(runtime, "memos", {})
    return {
        "agent_diagnostics_updated_at": _isoformat(
            getattr(runtime, "agent_diagnostics_updated_at", None)
        ),
        "system_metrics_updated_at": _isoformat(
            getattr(runtime, "system_metrics_updated_at", None)
        ),
        "answering_machine_messages_updated_at": _isoformat(
            getattr(runtime, "answering_machine_messages_updated_at", None)
        ),
        "answering_machine_message_count": _sequence_count(
            messages.get("messages") if isinstance(messages, Mapping) else None
        ),
        "memos_updated_at": _isoformat(getattr(runtime, "memos_updated_at", None)),
        "text_memo_count": _sequence_count(
            memos.get("text") if isinstance(memos, Mapping) else None
        ),
        "voice_memo_count": _sequence_count(
            memos.get("voice") if isinstance(memos, Mapping) else None
        ),
    }


def _safe_system_metrics(runtime: Any | None) -> dict[str, Any] | None:
    if runtime is None:
        return None
    metrics = getattr(runtime, "system_metrics", {})
    if not isinstance(metrics, Mapping):
        return None
    return {
        key: metrics.get(key)
        for key in (
            "cpu_count",
            "cpu_usage_percent",
            "load_1m",
            "load_5m",
            "load_15m",
            "load_1m_percent",
            "memory_total_kb",
            "memory_available_kb",
            "memory_used_kb",
            "memory_usage_percent",
            "temperature_c",
            "temperature_source",
        )
    }


def _safe_status_dict(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        str(key): item
        for key, item in sorted(value.items())
        if not _is_sensitive_key(str(key))
        and not isinstance(item, dict | list | tuple | set)
    }


def _configured_alarm_entity(entry: ConfigEntry) -> str:
    value = entry.options.get(CONF_ALARM_ENTITY_ID) or entry.data.get(
        CONF_ALARM_ENTITY_ID,
        "",
    )
    return value if isinstance(value, str) else ""


def _configured_weather_entity(entry: ConfigEntry) -> str:
    value = entry.options.get(CONF_WEATHER_ENTITY_ID) or entry.data.get(
        CONF_WEATHER_ENTITY_ID,
        "",
    )
    return value if isinstance(value, str) else ""


def _entity_domain_counts(values: Any) -> dict[str, int]:
    if not isinstance(values, list):
        return {}
    counts: dict[str, int] = {}
    for value in values:
        if not isinstance(value, str) or "." not in value:
            continue
        domain = value.split(".", 1)[0]
        counts[domain] = counts.get(domain, 0) + 1
    return dict(sorted(counts.items()))


def _sequence_count(value: Any) -> int | None:
    return len(value) if isinstance(value, list | tuple) else None


def _isoformat(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return None


def _safe_error_summary(value: Any) -> dict[str, str | None] | None:
    if not value:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    error_type, separator, message = text.partition(":")
    return {
        "type": error_type[:80],
        "message": _redact_error_message(message if separator else ""),
    }


def _redact_error_message(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    text = re.sub(r"\b[a-z][a-z0-9+.-]*://\S+", "<url>", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ipv4>", text)
    text = re.sub(
        r"\[[0-9a-f:.%]+\](?::\d{1,5})?",
        "<ipv6>",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(?:[a-z0-9-]+\.)+[a-z][a-z0-9-]*(?::\d{1,5})?\b",
        "<hostname>",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?<=\bhost\s)[a-z0-9-]+(?::\d{1,5})?\b",
        "<hostname>",
        text,
        flags=re.IGNORECASE,
    )
    words = []
    for word in text.split():
        clean = word.strip("[](),;")
        if ":" in clean and _ip_address(clean.split("%", 1)[0]) is not None:
            words.append(word.replace(clean, "<ipv6>"))
        else:
            words.append(word)
    return " ".join(words)[:180]


def _is_sensitive_key(key: str) -> bool:
    clean = key.lower()
    return any(part in clean for part in _SENSITIVE_KEY_PARTS)


def _subscription_callback_is_clean(state: Any) -> bool | None:
    scheme = getattr(state, "event_subscription_callback_scheme", None)
    host_type = getattr(state, "event_subscription_callback_host_type", None)
    return callback_target_is_clean_local_http(scheme, host_type)


def _host_private_address(host: str) -> bool | None:
    address = _ip_address(clean_callback_host(host))
    return address.is_private if address is not None else None


def _ip_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _same_lan_prefix_guess(
    source: ipaddress.IPv4Address | ipaddress.IPv6Address | None,
    target: ipaddress.IPv4Address | ipaddress.IPv6Address | None,
) -> bool | None:
    if source is None or target is None or source.version != target.version:
        return None
    prefix = 24 if source.version == 4 else 64
    source_network = ipaddress.ip_network(f"{source}/{prefix}", strict=False)
    target_network = ipaddress.ip_network(f"{target}/{prefix}", strict=False)
    return source_network == target_network
