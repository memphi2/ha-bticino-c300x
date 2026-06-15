"""Typed maintenance device-agent contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .base import AgentContract


@dataclass(frozen=True, slots=True, eq=False)
class AuthConfigStatus(AgentContract):
    """Normalized bootstrap/auth configuration status."""

    no_auth: bool
    restart_required: bool
    api_token_configured: bool
    maintenance_token_configured: bool
    maintenance_enabled: bool | None
    maintenance_no_auth_allowed: bool | None
    mdns_enabled: bool | None
    firewall_enabled: bool | None
    ipv6_firewall_enabled: bool | None
    activations_enabled: bool | None
    activations_auto_discover: bool | None
    activation_stair_light_address: str | None


@dataclass(frozen=True, slots=True, eq=False)
class FirewallStatus(AgentContract):
    """Normalized firewall patch status."""

    available: bool
    state: str
    patched: bool | None
    family: str | None
    exists: bool | None
    backup_available: bool | None
    api_port: int | None
    rtsp_port: int | None
    talkback_rtp_port: int | None
    media_ports_enabled: bool | None
    changed_files: int | None
