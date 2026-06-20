"""Read-only media readiness aggregation for BTicino C300X."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .capabilities import capability_is_supported
from .const import CONF_VIDEO_ENABLED, SMARTPHONE_FORWARDING_MODE_HOME_ASSISTANT
from .device_user import device_user_ready
from .entry_config import entry_config_value
from .media_setup import (
    media_readiness_action,
    self_test_failure_is_optional_ipv6_only,
)

MEDIA_READINESS_STATUS_OPTIONS = ("ready", "warning", "blocked", "unavailable")
MEDIA_READINESS_REQUIRED_SELF_TEST_CHECKS = (
    "capabilities",
    "firewall",
    "rtsp",
    "talkback_rtp",
    "homeassistant_user",
    "device_routing",
    "startup",
)


def media_readiness(entry: ConfigEntry) -> dict[str, Any]:
    """Return a read-only readiness summary for local media features."""

    runtime_data = entry.runtime_data
    connection_state = getattr(runtime_data, "connection_state", None)
    capabilities = getattr(runtime_data, "capabilities", {})
    self_test = getattr(runtime_data, "self_test_status", {})
    checks = self_test.get("checks") if isinstance(self_test, Mapping) else None
    if not isinstance(checks, Mapping):
        checks = {}

    failed: list[str] = []
    warnings: list[str] = []
    agent_reachable = bool(getattr(connection_state, "available", False))
    if not agent_reachable:
        failed.append("agent_reachable")

    video_enabled = bool(entry_config_value(entry, CONF_VIDEO_ENABLED, False))
    ring_call_supported = capability_is_supported(capabilities, "doorbell_call")
    home_call_supported = capability_is_supported(capabilities, "home_call")
    doorbell_video_supported = capability_is_supported(capabilities, "doorbell_video")
    media_capability_active = any(
        (doorbell_video_supported, ring_call_supported, home_call_supported)
    )
    if video_enabled and not media_capability_active:
        warnings.append("media_capabilities_missing")

    check_results = {
        name: self_test_check_ok(checks, name)
        for name in MEDIA_READINESS_REQUIRED_SELF_TEST_CHECKS
    }
    for name, ok in check_results.items():
        if ok is False:
            reason = self_test_check_reason(checks, name)
            if self_test_failure_is_optional_ipv6_only(name, reason, checks):
                warnings.append(f"{name}:optional_ipv6")
            else:
                failed.append(name)
    if isinstance(self_test, Mapping) and not self_test:
        warnings.append("self_test_not_loaded")

    forwarding_state = getattr(runtime_data.event_state, "smartphone_forwarding_mode", None)
    forwarding_homeassistant = forwarding_state == SMARTPHONE_FORWARDING_MODE_HOME_ASSISTANT
    if ring_call_supported and forwarding_state is not None and not forwarding_homeassistant:
        failed.append("forwarding_homeassistant")
    elif ring_call_supported and forwarding_state is None:
        warnings.append("forwarding_unknown")

    callback_url_ok = event_callback_ready(connection_state)
    if callback_url_ok is False:
        failed.append("callback_url")
    elif callback_url_ok is None:
        warnings.append("callback_url_unknown")

    status = "ready"
    if failed:
        status = "blocked"
    elif warnings:
        status = "warning"
    if not agent_reachable:
        status = "unavailable"

    agent_info = getattr(runtime_data, "agent_info", {})
    agent_version = agent_info.get("version") if isinstance(agent_info, Mapping) else None
    return {
        "status": status,
        "agent_reachable": agent_reachable,
        "agent_version_ok": bool(agent_version) if agent_reachable else False,
        "agent_version": agent_version,
        "media_user_ok": media_user_ready(
            getattr(runtime_data, "device_user_status", {}),
            checks,
        ),
        "forwarding_homeassistant": forwarding_homeassistant,
        "forwarding_state": forwarding_state,
        "rtsp_ok": check_results["rtsp"],
        "webrtc_available": video_enabled and doorbell_video_supported,
        "https_microphone_requirement": "secure_context_required_for_microphone",
        "talkback_rtp_ok": check_results["talkback_rtp"],
        "callback_url_ok": callback_url_ok,
        "ring_call_supported": ring_call_supported,
        "home_call_supported": home_call_supported,
        "doorbell_video_supported": doorbell_video_supported,
        "video_enabled": video_enabled,
        "self_test_ok": self_test.get("ok") if isinstance(self_test, Mapping) else None,
        "failed_checks": failed,
        "warnings": warnings,
        "recommended_action": media_readiness_action(status, failed, warnings),
    }


def self_test_check_ok(checks: Mapping[str, Any], name: str) -> bool | None:
    """Return the normalized boolean result for one self-test check."""

    check = checks.get(name)
    if not isinstance(check, Mapping):
        return None
    ok = check.get("ok")
    return ok if isinstance(ok, bool) else None


def self_test_check_reason(checks: Mapping[str, Any], name: str) -> str:
    """Return one self-test check reason code."""

    check = checks.get(name)
    if not isinstance(check, Mapping):
        return ""
    reason = check.get("reason")
    return reason if isinstance(reason, str) else ""


def media_user_ready(
    device_user_status: Mapping[str, Any],
    checks: Mapping[str, Any],
) -> bool | None:
    """Return whether the dedicated media user and route state are ready."""

    user_check = self_test_check_ok(checks, "homeassistant_user")
    routing_check = self_test_check_ok(checks, "device_routing")
    if user_check is not None or routing_check is not None:
        return user_check is not False and routing_check is not False
    if not isinstance(device_user_status, Mapping):
        return None
    return device_user_ready(device_user_status)


def event_callback_ready(connection_state: Any) -> bool | None:
    """Return whether the agent callback target is known-good."""

    if getattr(connection_state, "event_subscription_last_success_at", None) is not None:
        return True
    if getattr(connection_state, "event_subscription_last_error", None):
        return False
    scheme = getattr(connection_state, "event_subscription_callback_scheme", None)
    host_type = getattr(connection_state, "event_subscription_callback_host_type", None)
    if scheme is None and host_type is None:
        return None
    return scheme == "http" and host_type not in {
        "loopback",
        "link_local",
        "mdns",
        "unknown",
    }

