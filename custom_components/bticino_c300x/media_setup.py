"""Shared media setup readiness and repair decisions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .capabilities import capability_is_supported, maintenance_action_is_advertised
from .const import SMARTPHONE_FORWARDING_MODE_HOME_ASSISTANT

DEVICE_USER_MEDIA_SETUP_CHECKS = frozenset({"homeassistant_user", "device_routing"})
NON_DEVICE_USER_MEDIA_SETUP_CHECKS = frozenset(
    {
        "capabilities",
        "firewall",
        "rtsp",
        "talkback_rtp",
        "forwarding_homeassistant",
    }
)
OPTIONAL_IPV6_REASONS = frozenset(
    {
        "ipv6_media_ports_missing",
        "media_ports_open_ipv6_optional_missing",
    }
)
SELF_TEST_REASON_TEXT = {
    "config_missing": "the device-agent configuration is missing",
    "ipv4_media_ports_missing": (
        "the required IPv4 media and talkback firewall setup is missing"
    ),
    "ipv6_media_ports_missing": (
        "only the optional IPv6 media firewall setup is missing"
    ),
    "media_ports_open_ipv6_optional_missing": (
        "the required IPv4 media ports are open; only the optional IPv6 firewall "
        "setup is missing"
    ),
    "talkback_rtp_firewall_missing": (
        "UDP talkback port 40004 is not open through the required IPv4 firewall setup"
    ),
    "video_runtime_unavailable": "the device-agent video runtime is unavailable",
    "rtsp_server_not_running": "the device-agent RTSP server is not running",
    "rtsp_config_missing": "the RTSP port or stream path is missing",
    "media_identity_missing": "no usable C300X media identity is configured",
    "homeassistant_routes_inconsistent": (
        "the Home Assistant media-user route files are inconsistent"
    ),
    "device_routing_status_failed": (
        "the Home Assistant media routing setup status could not be read"
    ),
    "device_routing_missing": (
        "the Home Assistant media routing setup is incomplete"
    ),
    "agent_init_script_missing": "the device-agent startup script is missing",
    "startup_link_missing": "the device-agent startup link is missing",
}


@dataclass(frozen=True, slots=True)
class SelfTestRepairSummary:
    """Repair-oriented summary of failed device-agent self-test checks."""

    failed: tuple[str, ...]
    reasons: tuple[str, ...]
    actions: tuple[str, ...]


def self_test_reason_text(reason: str) -> str:
    """Return readable self-test reason text while preserving native reason codes."""

    return SELF_TEST_REASON_TEXT.get(
        reason,
        "the device-agent reported an unknown setup problem",
    )


def self_test_repair_action(check_name: str, reason: str) -> str | None:
    """Return a user-facing next step for one failed self-test check."""

    if check_name == "firewall":
        if reason == "ipv4_media_ports_missing":
            return (
                "Turn on or apply the C300X Firewall switch. This opens the IPv4 "
                "media and talkback ports used by Home Assistant."
            )
        if reason == "ipv6_media_ports_missing":
            return (
                "IPv6 is optional; only turn on or apply the C300X IPv6 Firewall "
                "switch if this HA instance reaches the device over IPv6."
            )
    if check_name == "talkback_rtp" and reason == "talkback_rtp_firewall_missing":
        return (
            "Apply the C300X Firewall switch so UDP talkback port 40004 is open "
            "over IPv4. The IPv6 firewall switch is only needed for IPv6 setups."
        )
    if check_name == "rtsp":
        return (
            "Check that doorbell video is enabled and restart or update the C300X "
            "device agent if RTSP is not running."
        )
    if check_name == "homeassistant_user":
        return "Open the integration options and run the Home Assistant media-user setup."
    if check_name == "device_routing":
        return "Open the integration options and run the Home Assistant media-user setup again."
    if check_name == "startup":
        return "Run the device-agent repair/update action to recreate the startup link."
    if check_name == "capabilities":
        return "Update or reconfigure the C300X device agent, then reload the integration."
    return None


def self_test_failure_is_optional_ipv6_only(
    check_name: str,
    reason: str,
    checks: Mapping[str, Any],
) -> bool:
    """Return true when a self-test failure is only optional IPv6."""

    if check_name == "firewall" and reason in OPTIONAL_IPV6_REASONS:
        return True
    if check_name != "talkback_rtp" or reason != "talkback_rtp_firewall_missing":
        return False
    firewall = checks.get("firewall")
    if not isinstance(firewall, Mapping):
        return False
    return firewall.get("reason") in OPTIONAL_IPV6_REASONS


def summarize_self_test_failures(checks: Mapping[str, Any]) -> SelfTestRepairSummary:
    """Return failed self-test checks, readable reasons, and deduplicated actions."""

    failed: list[str] = []
    reasons: list[str] = []
    actions: list[str] = []
    for name, check in checks.items():
        if not isinstance(check, Mapping) or check.get("ok") is not False:
            continue
        check_name = str(name)
        reason = check.get("reason")
        reason_text = reason if isinstance(reason, str) else ""
        if self_test_failure_is_optional_ipv6_only(check_name, reason_text, checks):
            continue
        failed.append(check_name)
        if reason_text:
            reasons.append(f"{check_name}: {self_test_reason_text(reason_text)}")
            action = self_test_repair_action(check_name, reason_text)
            if action and action not in actions:
                actions.append(action)
    return SelfTestRepairSummary(tuple(failed), tuple(reasons), tuple(actions))


def media_setup_has_only_device_user_failures(failed: object) -> bool:
    """Return true when failures are covered by the dedicated media-user repair."""

    if not isinstance(failed, list) or not failed:
        return False
    checks = {str(check) for check in failed}
    return checks <= DEVICE_USER_MEDIA_SETUP_CHECKS


def media_setup_has_non_device_user_failure(failed: object) -> bool:
    """Return true when failures need the broader media setup repair."""

    if not isinstance(failed, list):
        return False
    checks = {str(check) for check in failed}
    return bool(checks & NON_DEVICE_USER_MEDIA_SETUP_CHECKS)


def media_setup_fixable_checks(
    failed: list[Any],
    capabilities: Mapping[str, Any],
) -> list[str]:
    """Return media setup checks that can be repaired from HA."""

    checks = {str(check) for check in failed}
    fixable: list[str] = []
    if "agent_reachable" in checks:
        fixable.append("agent_reachable")
    if checks & {"capabilities", "rtsp"}:
        fixable.append("agent_update")
    if checks & {"firewall", "talkback_rtp"} and maintenance_action_is_advertised(
        capabilities,
        "firewall_apply",
    ):
        fixable.append("firewall")
    if checks & DEVICE_USER_MEDIA_SETUP_CHECKS and maintenance_action_is_advertised(
        capabilities,
        "device_user_ensure",
    ):
        fixable.append("homeassistant_user")
    if "forwarding_homeassistant" in checks and capability_is_supported(
        capabilities,
        "smartphone_forwarding",
    ):
        fixable.append(SMARTPHONE_FORWARDING_MODE_HOME_ASSISTANT)
    return fixable


def media_readiness_action(
    status: str,
    failed: list[str],
    warnings: list[str],
) -> str:
    """Return a stable action code for the aggregated media-readiness state."""

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
