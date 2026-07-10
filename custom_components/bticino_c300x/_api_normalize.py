"""Response normalization and URL helpers for the C300X device-agent client.

Split out of api.py so the api mixins can share these without a cycle.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .agent_contracts import (
    AgentDiagnosticsStatus,
    AuthConfigStatus,
    DoorbellVideoStatus,
    FirewallStatus,
    ForwardingStatus,
    HomeCallStatus,
    RingCallStatus,
    SelfTestStatus,
)
from .agent_contracts.self_test import normalize_self_test_contract
from .api_errors import C300XAgentApiResponseError
from .const import DEFAULT_AGENT_PORT, SMARTPHONE_FORWARDING_MODES
from .fingerprint import fnv1a64_fingerprint
from .forwarding import coerce_forwarding_mode_state
from .validation_patterns import ACTIVATION_ID_RE
from .value_parsing import optional_bool as _optional_bool
from .value_parsing import optional_int as _optional_int
from .value_parsing import optional_mapping as _json_object
from .value_parsing import optional_string as _optional_string


def build_agent_base_url(host: str, port: int) -> str:
    """Build the HTTP device-agent base URL from config entry data."""

    normalized_host = host.strip().strip("/")
    normalized_port = port if port > 0 else DEFAULT_AGENT_PORT
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"
    return f"http://{normalized_host}:{normalized_port}"


def _http_error_text(status: int, text: str, *, fallback: str | None = None) -> str:
    """Return a compact, safe HTTP error text from an agent response."""

    base = fallback or f"device agent returned HTTP {status}"
    detail = _agent_error_detail(text)
    if detail:
        return f"{base}: {detail}"
    return base


def _agent_error_detail(text: str) -> str | None:
    """Extract a short non-secret agent error from a JSON response body."""

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    for key in ("error", "message"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return _compact_agent_error_value(value)
    return None


def _compact_agent_error_value(value: str, *, max_length: int = 120) -> str:
    """Return one safe line from an agent error string."""

    compacted = " ".join(value.strip().split())
    if len(compacted) > max_length:
        return f"{compacted[: max_length - 3]}..."
    return compacted


def display_bridge_callback_fingerprint(
    enabled: bool,
    webhook_url: str,
    shared_secret: str,
) -> str:
    """Return the non-secret display-bridge callback fingerprint used by the agent."""

    material = f"{1 if enabled else 0}\n{webhook_url if enabled else ''}\n{shared_secret if enabled else ''}"
    return fnv1a64_fingerprint(material)


def _json_list(value: Any) -> list[Any]:
    """Return a JSON list value or an empty list."""

    return value if isinstance(value, list) else []


def _ok_response(data: Any) -> dict[str, Any]:
    """Return mutation responses as dictionaries."""

    return data if isinstance(data, dict) else {"ok": True, "raw": data}


def normalize_doorbell_video(data: Any) -> DoorbellVideoStatus:
    """Normalize device-agent doorbell video status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("doorbell video returned non-object JSON")
    bridge = _json_object(data.get("bridge"))
    return DoorbellVideoStatus(
        raw=data,
        available=bool(data.get("available")),
        window_available=bool(data.get("window_available")),
        stream_path=_optional_string(data.get("stream_path")),
        audio_stream_path=_optional_string(data.get("audio_stream_path")),
        recorder_stream_path=_optional_string(data.get("recorder_stream_path")),
        media_owner=_optional_string(bridge.get("media_owner")) or "unknown",
        external_media_active=_optional_bool(bridge.get("external_media_active"))
        is True,
        external_owner=_optional_string(bridge.get("external_owner")),
        last_block_reason=_optional_string(bridge.get("last_block_reason")),
        bridge=bridge,
    )


def _doorbell_video_has_ring_call(data: Mapping[str, Any]) -> bool:
    """Return true while the native bridge owns a doorbell ring call."""

    bridge = _json_object(data.get("bridge"))
    owner = str(data.get("media_owner") or bridge.get("media_owner") or "").lower()
    return owner == "ring" or bool(
        bridge.get("ring_call_active") or bridge.get("ring_media_active")
    )


def normalize_doorbell_call(data: Any) -> RingCallStatus:
    """Normalize device-agent doorbell ring-call control status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("doorbell call returned non-object JSON")
    return RingCallStatus(
        raw=data,
        supported=bool(data.get("supported")),
        active=bool(data.get("active")),
        early_media_active=bool(data.get("early_media_active")),
        audio_active=bool(data.get("audio_active")),
        answer_requested=bool(data.get("answer_requested")),
        answered=bool(data.get("answered")),
        can_answer=bool(data.get("can_answer")),
        can_hangup=bool(data.get("can_hangup")),
        media_owner=_optional_string(data.get("media_owner")) or "unknown",
        ring_receiver_running=bool(data.get("ring_receiver_running")),
        ring_registered=bool(data.get("ring_registered")),
        capture_supported=bool(data.get("capture_supported")),
        open_fds=_optional_int(data.get("open_fds"), 0) or 0,
        active_threads=_optional_int(data.get("active_threads"), 0) or 0,
        last_error=_optional_string(data.get("last_error")),
    )


def normalize_home_call(data: Any) -> HomeCallStatus:
    """Normalize device-agent local Home Call status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("home call returned non-object JSON")
    return HomeCallStatus(
        raw=data,
        available=bool(data.get("available")),
        running=bool(data.get("running")),
        active=bool(data.get("active")),
        answered=bool(data.get("answered")),
        rtp_proxy=bool(data.get("rtp_proxy")),
        target_audio_port=_optional_int(data.get("target_audio_port")),
        rtp_packets=_optional_int(data.get("rtp_packets"), 0) or 0,
        rtcp_packets=_optional_int(data.get("rtcp_packets"), 0) or 0,
        max_duration_seconds=_optional_int(data.get("max_duration_seconds")),
        last_error=_optional_string(data.get("last_error")),
    )


def normalize_activations(data: Any) -> dict[str, Any]:
    """Normalize configured C300X activation discovery responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("activations returned non-object JSON")
    items = _json_list(data.get("items"))
    normalized_items = [
        activation
        for activation in (_normalize_activation(item) for item in items)
        if activation is not None
    ]
    return {
        "available": bool(data.get("available", True)),
        "supported": bool(data.get("supported", bool(normalized_items))),
        "count": _optional_int(data.get("count"), len(normalized_items)),
        "items": normalized_items,
        "raw": data,
    }


def normalize_system_metrics(data: Any) -> dict[str, Any]:
    """Normalize device-agent system metric responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("system metrics returned non-object JSON")
    return {
        "cpu_count": _optional_int(data.get("cpu_count")),
        "cpu_usage_percent": _optional_float(data.get("cpu_usage_percent")),
        "load_1m": _optional_float(data.get("load_1m")),
        "load_5m": _optional_float(data.get("load_5m")),
        "load_15m": _optional_float(data.get("load_15m")),
        "load_1m_percent": _optional_float(data.get("load_1m_percent")),
        "load_5m_percent": _optional_float(data.get("load_5m_percent")),
        "load_15m_percent": _optional_float(data.get("load_15m_percent")),
        "memory_total_kb": _optional_int(data.get("memory_total_kb")),
        "memory_available_kb": _optional_int(data.get("memory_available_kb")),
        "memory_used_kb": _optional_int(data.get("memory_used_kb")),
        "memory_usage_percent": _optional_float(data.get("memory_usage_percent")),
        "temperature_c": _optional_float(data.get("temperature_c")),
        "temperature_source": data.get("temperature_source"),
        "raw": data,
    }


def normalize_agent_diagnostics(data: Any) -> AgentDiagnosticsStatus:
    """Normalize non-sensitive agent diagnostics."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("diagnostics returned non-object JSON")
    return AgentDiagnosticsStatus(
        raw=data,
        agent_write_count=_optional_int(data.get("agent_write_count")) or 0,
        last_write_at=_optional_int(data.get("last_write_at")),
        last_write_reason=_optional_string(data.get("last_write_reason")),
        last_write_class=_optional_string(data.get("last_write_class")),
        qml_patch_last_action=_optional_string(data.get("qml_patch_last_action")),
        loop_iterations=_optional_int(data.get("loop_iterations")),
        poll_wakeups=_optional_int(data.get("poll_wakeups")),
        accepted_clients=_optional_int(data.get("accepted_clients")),
        last_wake_reason=_optional_string(data.get("last_wake_reason")),
        last_poll_timeout_ms=_optional_int(data.get("last_poll_timeout_ms")),
        last_poll_count=_optional_int(data.get("last_poll_count")),
        open_fd_count=_optional_int(data.get("open_fd_count")),
        agent_init_script_present=_optional_bool(data.get("agent_init_script_present")),
        agent_init_link_ok=_optional_bool(data.get("agent_init_link_ok")),
        subscription_count=_optional_int(data.get("subscription_count")),
        recent_event_count=_optional_int(data.get("recent_event_count")),
        recent_event_capacity=_optional_int(data.get("recent_event_capacity")),
        display_bridge_registered=_optional_bool(data.get("display_bridge_registered")),
        display_bridge_disabled=_optional_bool(data.get("display_bridge_disabled")),
        home_assistant_connected_this_run=_optional_bool(
            data.get("home_assistant_connected_this_run")
        ),
        home_assistant_last_seen_at=_optional_int(
            data.get("home_assistant_last_seen_at")
        ),
        ui_event_revision=_optional_int(data.get("ui_event_revision")),
        ui_event_waiters=_optional_int(data.get("ui_event_waiters")),
        ui_event_waiter_capacity=_optional_int(data.get("ui_event_waiter_capacity")),
        ui_event_waiter_overflows=_optional_int(data.get("ui_event_waiter_overflows")),
        video_running=_optional_bool(data.get("video_running")),
        video_rtsp_server_running=_optional_bool(
            data.get("video_rtsp_server_running")
        ),
        video_media_starting=_optional_bool(data.get("video_media_starting")),
        video_call_active=_optional_bool(data.get("video_call_active")),
        video_clients=_optional_int(data.get("video_clients")),
        video_media_owner=_optional_string(data.get("video_media_owner")),
        video_external_media_active=_optional_bool(
            data.get("video_external_media_active")
        ),
        video_external_owner=_optional_string(data.get("video_external_owner")),
        video_last_block_reason=_optional_string(data.get("video_last_block_reason")),
        video_bridge_running=_optional_bool(data.get("video_bridge_running")),
        video_bridge_media_active=_optional_bool(data.get("video_bridge_media_active")),
        video_bridge_stop_in_progress=_optional_bool(
            data.get("video_bridge_stop_in_progress")
        ),
        video_bridge_open_fds=_optional_int(data.get("video_bridge_open_fds")),
        video_bridge_active_threads=_optional_int(
            data.get("video_bridge_active_threads")
        ),
        ring_receiver_running=_optional_bool(data.get("ring_receiver_running")),
        ring_registered=_optional_bool(data.get("ring_registered")),
        ring_call_active=_optional_bool(data.get("ring_call_active")),
        ring_media_active=_optional_bool(data.get("ring_media_active")),
        home_call_running=_optional_bool(data.get("home_call_running")),
        home_call_active=_optional_bool(data.get("home_call_active")),
        flexisip_backup_available=_optional_bool(data.get("flexisip_backup_available")),
        flexisip_restart_marker=_optional_bool(data.get("flexisip_restart_marker")),
        flexisip_backup_marker=_optional_bool(data.get("flexisip_backup_marker")),
        flexisip_reference_state=_optional_string(data.get("flexisip_reference_state")),
    )


def normalize_self_test(data: Any) -> SelfTestStatus:
    """Normalize device-agent self-test status."""

    return normalize_self_test_contract(data, C300XAgentApiResponseError)


def normalize_device_user_status(data: Any) -> dict[str, Any]:
    """Normalize non-sensitive Flexisip device-user status."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("device user status returned non-object JSON")
    available = _optional_bool(data.get("ok")) is not False

    def status_bool(key: str) -> bool | None:
        if not available:
            return None
        return _optional_bool(data.get(key))

    return {
        "available": available,
        "supported": _optional_bool(data.get("supported")) is True,
        "domain_present": status_bool("domain_present"),
        "homeassistant_user_present": status_bool("homeassistant_user_present"),
        "accounts_homeassistant_present": status_bool(
            "accounts_homeassistant_present"
        ),
        "route_int_homeassistant_present": status_bool(
            "route_int_homeassistant_present"
        ),
        "route_ext_homeassistant_present": status_bool(
            "route_ext_homeassistant_present"
        ),
        "route_conf_homeassistant_present": status_bool(
            "route_conf_homeassistant_present"
        ),
        "route_conf_is_symlink": status_bool("route_conf_is_symlink"),
        "writable_files_present": status_bool("writable_files_present"),
        "media_identity_available": status_bool("media_identity_available"),
        "routes_consistent": status_bool("routes_consistent"),
        "device_routing_supported": status_bool("device_routing_supported"),
        "device_routing_applied": status_bool("device_routing_applied"),
        "device_routing_state": _optional_string(
            data.get("device_routing_state")
        ),
        "device_routing_backup_present": status_bool("device_routing_backup_present"),
        "device_routing_error": _optional_string(
            data.get("device_routing_error")
        ),
        "media_user_label_available": status_bool("media_user_label_available"),
        "media_user_label_applied": status_bool("media_user_label_applied"),
        "media_user_label_state": _optional_string(
            data.get("media_user_label_state")
        ),
        "account_label": _optional_string(data.get("account_label")),
        "error": _optional_string(data.get("error")),
        "raw": _safe_device_user_raw(data),
    }


_SAFE_DEVICE_USER_RAW_KEYS = frozenset(
    {
        "ok",
        "status_available",
        "supported",
        "domain_present",
        "homeassistant_user_present",
        "accounts_homeassistant_present",
        "route_int_homeassistant_present",
        "route_ext_homeassistant_present",
        "route_conf_homeassistant_present",
        "route_conf_is_symlink",
        "writable_files_present",
        "media_identity_available",
        "routes_consistent",
        "device_routing_supported",
        "device_routing_applied",
        "device_routing_state",
        "device_routing_backup_present",
        "device_routing_error",
        "media_user_label_available",
        "media_user_label_applied",
        "media_user_label_state",
        "error",
    }
)


def _safe_device_user_raw(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a non-sensitive raw view for device-user diagnostics.

    The device-side SIP realm and AOR values are local implementation details.
    Keep the functional presence flags, but never preserve unknown fields from
    this endpoint because they may include route contents, digests, or AORs.
    """

    return {key: data.get(key) for key in _SAFE_DEVICE_USER_RAW_KEYS if key in data}


def normalize_auth_config_status(data: Any) -> AuthConfigStatus:
    """Normalize bootstrap/auth configuration status."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("auth config returned non-object JSON")
    no_auth = _optional_bool(data.get("noAuth"))
    if no_auth is None:
        no_auth = _optional_bool(data.get("no_auth"))
    return AuthConfigStatus(
        raw=data,
        no_auth=bool(no_auth),
        restart_required=_optional_bool(data.get("restart_required")) is True,
        api_token_configured=bool(data.get("api_token_configured")),
        maintenance_token_configured=bool(data.get("maintenance_token_configured")),
        maintenance_enabled=_optional_bool(data.get("maintenance_enabled")),
        maintenance_no_auth_allowed=_optional_bool(
            data.get("maintenance_no_auth_allowed")
        ),
        mdns_enabled=_optional_bool(data.get("mdns_enabled")),
        firewall_enabled=_optional_bool(data.get("firewall_enabled")),
        ipv6_firewall_enabled=_optional_bool(data.get("ipv6_firewall_enabled")),
        activations_enabled=_optional_bool(data.get("activations_enabled")),
        activations_auto_discover=_optional_bool(data.get("activations_auto_discover")),
    )


def normalize_ssh_status(data: Any) -> dict[str, Any]:
    """Normalize maintenance SSH status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("SSH status returned non-object JSON")
    raw_value = data.get("running", data.get("enabled"))
    if raw_value is None:
        return {"running": None, "enabled": None, "raw": data}
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"true", "1", "on", "running", "enabled"}:
            running = True
        elif normalized in {"false", "0", "off", "stopped", "disabled"}:
            running = False
        else:
            running = None
    else:
        running = bool(raw_value)
    return {
        "running": running,
        "enabled": running,
        "raw": data.get("raw", data),
    }


def normalize_qml_patch_status(data: Any) -> dict[str, Any]:
    """Normalize maintenance Display patch status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("Display patch status returned non-object JSON")
    state = str(data.get("state") or "").strip().lower()
    patched = _optional_bool(data.get("patched"))
    if patched is None:
        if state in {"patched", "applied"}:
            patched = True
        elif state in {"original", "restored", "not_patched"}:
            patched = False
    if not state:
        if patched is True:
            state = "patched"
        elif patched is False:
            state = "original"
        else:
            state = "unknown"
    return {
        "available": bool(data.get("available", True)),
        "patched": patched,
        "state": state,
        "core_patched": _optional_bool(data.get("core_patched")),
        "core_state": _optional_string(data.get("core_state")),
        "backup_available": _optional_bool(data.get("backup_available")),
        "core_backup_available": _optional_bool(data.get("core_backup_available")),
        "gui_running": _optional_bool(data.get("gui_running")),
        "raw": data.get("raw", data),
    }


def normalize_firewall_status(data: Any) -> FirewallStatus:
    """Normalize maintenance firewall status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("firewall status returned non-object JSON")
    state = _optional_string(data.get("state")) or "unknown"
    patched = _optional_bool(data.get("patched"))
    if patched is None and state == "patched":
        patched = True
    elif patched is None and state in {"original", "missing"}:
        patched = False
    return FirewallStatus(
        raw=data,
        available=data.get("available", True) is not False,
        state=state,
        patched=patched,
        family=_optional_string(data.get("family")),
        exists=_optional_bool(data.get("exists")),
        backup_available=_optional_bool(data.get("backup_available")),
        api_port=_optional_int(data.get("api_port")),
        rtsp_port=_optional_int(data.get("rtsp_port")),
        talkback_rtp_port=_optional_int(data.get("talkback_rtp_port")),
        media_ports_enabled=_optional_bool(data.get("media_ports_enabled")),
        changed_files=_optional_int(data.get("changed_files")),
    )


def normalize_mqtt_status(data: Any) -> dict[str, Any]:
    """Normalize native MQTT bridge status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("MQTT status returned non-object JSON")
    topics = _json_object(data.get("topics"))
    return {
        "available": data.get("available", True) is not False,
        "enabled": _optional_bool(data.get("enabled")),
        "configured": _optional_bool(data.get("configured")),
        "connected": _optional_bool(data.get("connected")),
        "subscribed": _optional_bool(data.get("subscribed")),
        "host_configured": _optional_bool(data.get("host_configured")),
        "username_configured": _optional_bool(data.get("username_configured")),
        "password_configured": _optional_bool(data.get("password_configured")),
        "port": _optional_int(data.get("port")),
        "client_id": _optional_string(data.get("client_id")),
        "command_host": _optional_string(data.get("command_host")),
        "command_port": _optional_int(data.get("command_port")),
        "command_topic": _optional_string(topics.get("command")),
        "event_topic": _optional_string(topics.get("event")),
        "json_event_topic": _optional_string(topics.get("json_event")),
        "status_topic": _optional_string(topics.get("status")),
        "availability_topic": _optional_string(topics.get("availability")),
        "qos": _optional_int(data.get("qos")),
        "keepalive_seconds": _optional_int(data.get("keepalive_seconds")),
        "reconnect_initial_seconds": _optional_int(
            data.get("reconnect_initial_seconds")
        ),
        "reconnect_max_seconds": _optional_int(data.get("reconnect_max_seconds")),
        "legacy_installed": _optional_bool(data.get("legacy_installed")),
        "legacy_enabled": _optional_bool(data.get("legacy_enabled")),
        "legacy_running": _optional_bool(data.get("legacy_running")),
        "exclusive": data.get("exclusive") is True,
        "raw": data,
    }


def normalize_legacy_mqtt_status(data: Any) -> dict[str, Any]:
    """Normalize legacy TcpDump2Mqtt patch status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("legacy MQTT status returned non-object JSON")
    return {
        "available": data.get("available", True) is not False,
        "enabled": _optional_bool(data.get("enabled")),
        "installed": _optional_bool(data.get("installed")),
        "running": _optional_bool(data.get("running")),
        "backup_available": _optional_bool(data.get("backup_available")),
        "native_enabled": _optional_bool(data.get("native_enabled")),
        "exclusive": data.get("exclusive") is True,
        "script_path": _optional_string(data.get("script_path")),
        "init_link": _optional_string(data.get("init_link")),
        "flexisip_backup_available": _optional_bool(
            data.get("flexisip_backup_available")
        ),
        "flexisip_restart_marker": _optional_bool(data.get("flexisip_restart_marker")),
        "flexisip_reference_state": _optional_string(
            data.get("flexisip_reference_state")
        ),
        "raw": data,
    }


def normalize_smartphone_forwarding_mode(mode: Any) -> str:
    """Validate and normalize a smartphone-forwarding mode string."""

    value = str(mode or "").strip().lower()
    if value not in SMARTPHONE_FORWARDING_MODES:
        raise C300XAgentApiResponseError("invalid smartphone-forwarding mode")
    return value


def normalize_smartphone_forwarding(data: Any) -> ForwardingStatus:
    """Normalize device-agent smartphone-forwarding responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("smartphone-forwarding returned non-object JSON")
    if "state" in data and isinstance(data["state"], dict):
        raw_value = data["state"].get("smartphone_forwarding")
        if raw_value is None:
            return ForwardingStatus(raw=data, mode=None, state="unknown")
        return _normalized_smartphone_forwarding(raw_value, raw_value, raw=data)
    if data.get("mode") is None and data.get("state") == "unknown":
        return ForwardingStatus(raw=data.get("raw", data), mode=None, state="unknown")
    if "enabled" in data:
        return _normalized_smartphone_forwarding(
            data["enabled"],
            data["enabled"],
            raw=data.get("raw"),
        )
    normalized = coerce_forwarding_mode_state(data.get("mode"), data.get("state"))
    if normalized["mode"] is None:
        raise C300XAgentApiResponseError("smartphone-forwarding mode is missing")
    mode_value = normalized["mode"]
    return ForwardingStatus(
        raw=data.get("raw"),
        mode=mode_value if isinstance(mode_value, int) else None,
        state=str(normalized["state"]),
    )


def _normalized_smartphone_forwarding(
    mode: Any,
    state: Any,
    *,
    raw: Any,
) -> ForwardingStatus:
    normalized = coerce_forwarding_mode_state(mode, state)
    mode_value = normalized["mode"]
    return ForwardingStatus(
        raw=raw,
        mode=mode_value if isinstance(mode_value, int) else None,
        state=str(normalized["state"]),
    )


def normalize_ringer(data: Any) -> dict[str, Any]:
    """Normalize device-agent ringer responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("ringer returned non-object JSON")
    raw_value: Any
    if "state" in data and isinstance(data["state"], dict):
        raw_value = data["state"].get("ringer_muted")
        volume_value = data["state"].get("ringer_volume")
        has_volume = "ringer_volume" in data["state"]
        raw = data
    else:
        raw_value = data.get("muted")
        volume_value = data.get("volume")
        has_volume = "volume" in data
        raw = data.get("raw", data)
    result: dict[str, Any] = {"muted": None, "raw": raw}
    if raw_value is None:
        result["muted"] = None
    elif isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"true", "1", "on", "muted"}:
            result["muted"] = True
        elif normalized in {"false", "0", "off", "unmuted"}:
            result["muted"] = False
        else:
            result["muted"] = bool(raw_value)
    else:
        result["muted"] = bool(raw_value)
    if has_volume:
        result["volume"] = _normalize_ringer_volume(volume_value)
    return result


def _normalize_ringer_volume(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    try:
        volume = int(value)
    except (TypeError, ValueError):
        return None
    if 0 <= volume <= 10:
        return volume
    return None


def normalize_answering_machine(data: Any) -> dict[str, Any]:
    """Normalize device-agent answering-machine responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("answering-machine returned non-object JSON")
    raw_value: Any
    if "state" in data and isinstance(data["state"], dict):
        raw_value = data["state"].get("answering_machine_enabled")
        raw = data
    else:
        raw_value = data.get("enabled")
        raw = data.get("raw", data)
    result: dict[str, Any] = {
        "enabled": None,
        "greeting_message_enabled": _optional_bool(data.get("greeting_message_enabled")),
        "status_fields": (
            data.get("status_fields")
            if isinstance(data.get("status_fields"), list)
            else []
        ),
        "raw": raw,
    }
    if raw_value is None:
        return result
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"true", "1", "on", "enabled"}:
            result["enabled"] = True
            return result
        if normalized in {"false", "0", "off", "disabled"}:
            result["enabled"] = False
            return result
    result["enabled"] = bool(raw_value)
    return result


def normalize_answering_machine_messages(data: Any) -> dict[str, Any]:
    """Normalize device-agent answering-machine video message metadata."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError(
            "answering-machine messages returned non-object JSON"
        )
    messages = _json_list(data.get("messages"))
    normalized_messages = [
        message
        for message in (_normalize_voicemail_message(item) for item in messages)
        if message is not None
    ]
    return {
        "available": bool(data.get("available", True)),
        "total": _optional_int(data.get("total"), len(normalized_messages)),
        "unread": _optional_int(data.get("unread"), 0),
        "read": _optional_int(data.get("read"), 0),
        "newest_at": data.get("newest_at"),
        "messages": normalized_messages,
        "raw": data,
    }


def normalize_memos(data: Any) -> dict[str, Any]:
    """Normalize device-agent local memo metadata."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("memos returned non-object JSON")
    memos = _json_list(data.get("memos"))
    normalized_memos = [
        memo
        for memo in (_normalize_memo(item) for item in memos)
        if memo is not None
    ]
    text_total = _optional_int(data.get("text_total"), None)
    voice_total = _optional_int(data.get("voice_total"), None)
    if text_total is None:
        text_total = sum(1 for memo in normalized_memos if memo["kind"] == "text")
    if voice_total is None:
        voice_total = sum(1 for memo in normalized_memos if memo["kind"] == "voice")
    return {
        "available": bool(data.get("available", True)),
        "total": _optional_int(data.get("total"), text_total + voice_total),
        "text_total": text_total,
        "voice_total": voice_total,
        "unread": _optional_int(data.get("unread"), 0),
        "read": _optional_int(data.get("read"), 0),
        "newest_at": data.get("newest_at"),
        "memos": normalized_memos,
        "raw": data,
    }


def _normalize_voicemail_message(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    message_id = str(data.get("id") or "").strip()
    if not message_id:
        return None
    return {
        "id": message_id,
        "read": _optional_bool(data.get("read")),
        "date": data.get("date"),
        "unix_time": _optional_int(data.get("unix_time")),
        "iso_time": data.get("iso_time"),
        "has_thumbnail": bool(data.get("has_thumbnail")),
        "has_video": bool(data.get("has_video")),
        "media_mime_type": data.get("media_mime_type"),
        "media_size": _optional_int(data.get("media_size")),
    }


def _normalize_memo(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    memo_id = str(data.get("id") or "").strip()
    kind = str(data.get("kind") or "").strip().lower()
    if not memo_id or kind not in {"text", "voice"}:
        return None
    text = data.get("text")
    return {
        "id": memo_id,
        "kind": kind,
        "read": _optional_bool(data.get("read")),
        "date": data.get("date"),
        "unix_time": _optional_int(data.get("unix_time")),
        "iso_time": data.get("iso_time"),
        "has_text": bool(data.get("has_text")),
        "has_audio": bool(data.get("has_audio")),
        "audio_mime_type": data.get("audio_mime_type"),
        "audio_size": _optional_int(data.get("audio_size")),
        "text": text if isinstance(text, str) else None,
        "text_truncated": bool(data.get("text_truncated")),
    }


def _normalize_activation(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    activation_id = str(data.get("id") or "").strip()
    if not ACTIVATION_ID_RE.fullmatch(activation_id):
        return None
    name = str(data.get("name") or "").strip()
    if not name:
        name = activation_id.replace("_", " ").replace("-", " ").title()
    activation_type = str(data.get("type") or "unknown").strip().lower()
    if activation_type not in {
        "lock",
        "light",
        "stair_light",
        "generic",
        "scenario",
        "unknown",
    }:
        activation_type = "unknown"
    address_mode = str(
        data.get("addressMode") or data.get("address_mode") or "manual"
    ).strip().lower()
    if address_mode not in {"manual", "auto"}:
        address_mode = "manual"
    source = str(data.get("source") or "agent").strip().lower() or "agent"
    return {
        "id": activation_id,
        "name": name,
        "type": activation_type,
        "address_mode": address_mode,
        "address": _optional_string(data.get("address")),
        "source": source,
        "executable": _optional_bool(data.get("executable")) is True,
    }


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as err:
        raise C300XAgentApiResponseError("system metric value is invalid") from err
