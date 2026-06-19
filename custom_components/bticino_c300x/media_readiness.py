"""Read-only media readiness aggregation for BTicino C300X."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .capabilities import capability_is_supported
from .const import CONF_VIDEO_ENABLED, SMARTPHONE_FORWARDING_MODE_HOME_ASSISTANT
from .entry_config import entry_config_value

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
    connection_state = runtime_data.connection_state
    capabilities = runtime_data.capabilities
    self_test = runtime_data.self_test_status
    checks = self_test.get("checks") if isinstance(self_test, Mapping) else None
    if not isinstance(checks, Mapping):
        checks = {}

    failed: list[str] = []
    warnings: list[str] = []
    agent_reachable = bool(connection_state.available)
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
            if media_readiness_optional_ipv6_failure(name, reason, checks):
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

    agent_info = runtime_data.agent_info
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
        "https_microphone_ok": None,
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


def media_readiness_optional_ipv6_failure(
    check_name: str,
    reason: str,
    checks: Mapping[str, Any],
) -> bool:
    """Return true when a self-test failure is only optional IPv6."""

    if check_name == "firewall" and reason in {
        "ipv6_media_ports_missing",
        "media_ports_open_ipv6_optional_missing",
    }:
        return True
    if check_name != "talkback_rtp" or reason != "talkback_rtp_firewall_missing":
        return False
    firewall = checks.get("firewall")
    if not isinstance(firewall, Mapping):
        return False
    return firewall.get("reason") in {
        "ipv6_media_ports_missing",
        "media_ports_open_ipv6_optional_missing",
    }


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
    present = device_user_status.get("homeassistant_user_present")
    routing = device_user_status.get("device_routing_applied")
    label = device_user_status.get("media_user_label_applied")
    if present is None and routing is None and label is None:
        return None
    return present is True and routing is not False and label is not False


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


def media_readiness_action(
    status: str,
    failed: list[str],
    warnings: list[str],
) -> str:
    """Return a stable action code for the aggregated readiness state."""

    if status == "ready":
        return "no_action_needed"
    if "agent_reachable" in failed:
        return "check_agent_reachability_and_token"
    if "capabilities" in failed or "media_capabilities_missing" in warnings:
        return "update_or_reconfigure_device_agent"
    if "firewall" in failed or "talkback_rtp" in failed or "rtsp" in failed:
        return "apply_firewall_or_update_device_agent"
    if "homeassistant_user" in failed or "device_routing" in failed:
        return "run_homeassistant_media_user_setup"
    if "forwarding_homeassistant" in failed:
        return "set_forwarding_to_homeassistant"
    if "callback_url" in failed:
        return "configure_reachable_callback_url"
    if "self_test_not_loaded" in warnings:
        return "refresh_or_reload_integration"
    return "check_media_readiness_details"
