"""Runtime data models for BTicino C300X."""

from __future__ import annotations

import ipaddress
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit


@dataclass(slots=True)
class C300XOperationDiagnostics:
    """Safe runtime diagnostics for one integration-side operation."""

    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_error: str | None = None

    def mark_attempt(self, now: datetime) -> None:
        """Record that the operation was attempted."""

        self.last_attempt_at = now

    def mark_success(self, now: datetime) -> None:
        """Record that the operation completed successfully."""

        self.last_success_at = now
        self.last_error = None

    def mark_failure(self, error: str, now: datetime) -> None:
        """Record the safe reason for the last failed operation."""

        self.last_failure_at = now
        self.last_error = error


@dataclass(slots=True)
class C300XCallbackDiagnostics(C300XOperationDiagnostics):
    """Safe callback-target diagnostics without exposing callback URLs."""

    callback_scheme: str | None = None
    callback_host_type: str | None = None

    def mark_callback_attempt(self, callback_url: str, now: datetime) -> None:
        """Record a callback operation attempt without storing the URL."""

        self.mark_attempt(now)
        self.callback_scheme = _callback_scheme(callback_url)
        self.callback_host_type = _callback_host_type(callback_url)


@dataclass(slots=True)
class C300XConnectionState:
    """Runtime connection state for the device agent."""

    available: bool = True
    connection_state: str = "connected"
    reconnect_count: int = 0
    last_connection_stage: str | None = None
    last_reconnect_reason: str | None = None
    last_connection_error: str | None = None
    next_reconnect_delay_seconds: int | None = None
    was_reconnecting: bool = False
    expire_unavailable: Callable[[], None] | None = None
    event_subscription_id: str | None = None
    event_subscription_event_count: int | None = None
    event_subscription_callback_scheme: str | None = None
    event_subscription_callback_host_type: str | None = None
    event_subscription_last_attempt_at: datetime | None = None
    event_subscription_last_success_at: datetime | None = None
    event_subscription_last_failure_at: datetime | None = None
    event_subscription_last_error: str | None = None

    def mark_connected(self) -> None:
        """Mark the agent as connected and count recovered reconnects."""

        if self.was_reconnecting:
            self.reconnect_count += 1
        self.available = True
        self.connection_state = "connected"
        self.next_reconnect_delay_seconds = None
        self.was_reconnecting = False
        if self.expire_unavailable:
            self.expire_unavailable()
            self.expire_unavailable = None

    def mark_reconnecting(
        self,
        reason: str,
        next_delay_seconds: int,
        error: str | None = None,
    ) -> None:
        """Mark a reconnectable outage while preserving short grace availability."""

        self.connection_state = "reconnecting" if self.available else "disconnected"
        self.last_connection_stage = _connection_stage_from_reason(reason)
        self.last_reconnect_reason = reason
        self.last_connection_error = error or reason
        self.next_reconnect_delay_seconds = next_delay_seconds
        self.was_reconnecting = True

    def mark_unavailable(self) -> None:
        """Mark the agent disconnected after reconnect grace expires."""

        self.available = False
        self.connection_state = "disconnected"

    def mark_event_subscription_attempt(
        self,
        callback_url: str,
        event_count: int,
        now: datetime,
    ) -> None:
        """Record a safe event-subscription registration attempt."""

        self.event_subscription_event_count = max(0, event_count)
        self.event_subscription_callback_scheme = _callback_scheme(callback_url)
        self.event_subscription_callback_host_type = _callback_host_type(callback_url)
        self.event_subscription_last_attempt_at = now

    def mark_event_subscription_success(
        self,
        subscription_id: str | None,
        event_count: int,
        callback_url: str,
        now: datetime,
    ) -> None:
        """Record safe metadata for a successful event subscription."""

        self.mark_event_subscription_attempt(callback_url, event_count, now)
        self.event_subscription_id = subscription_id
        self.event_subscription_last_success_at = now
        self.event_subscription_last_error = None

    def mark_event_subscription_failure(
        self,
        now: datetime,
        error: str | None = None,
    ) -> None:
        """Record that event subscription setup failed."""

        self.event_subscription_last_failure_at = now
        self.event_subscription_last_error = error


def _connection_stage_from_reason(reason: str) -> str:
    """Return a stable operator-facing connection stage for diagnostics."""

    if reason == "event_subscription_registration":
        return "event_subscription"
    if reason.endswith("Error") or reason.endswith("Timeout"):
        return "agent_api"
    return reason or "unknown"


def _callback_scheme(callback_url: str) -> str | None:
    scheme = urlsplit(callback_url).scheme.strip().lower()
    return scheme or None


def _callback_host_type(callback_url: str) -> str | None:
    host = urlsplit(callback_url).hostname
    if not host:
        return None
    clean_host = host.strip("[]").split("%", 1)[0].lower()
    if clean_host.endswith(".local"):
        return "mdns"
    if clean_host in {"localhost", "localhost.localdomain"}:
        return "loopback"
    try:
        address = ipaddress.ip_address(clean_host)
    except ValueError:
        return "hostname"
    if address.is_loopback:
        return "loopback"
    if address.is_link_local:
        return "link_local_ipv6" if address.version == 6 else "link_local_ipv4"
    return "ipv6" if address.version == 6 else "ipv4"


def callback_target_is_clean_local_http(
    scheme: str | None,
    host_type: str | None,
) -> bool | None:
    """Return whether a callback target can be used by the native C agent."""

    if scheme is None and host_type is None:
        return None
    return scheme == "http" and host_type not in {
        None,
        "loopback",
        "mdns",
        "link_local_ipv4",
        "link_local_ipv6",
    }


@dataclass(slots=True)
class C300XEventState:
    """Runtime state derived from device-agent push events."""

    video_available: bool = False
    video_active_until: str | None = None
    video_stream_path: str | None = None
    smartphone_forwarding_mode: str | None = None
    ringer_muted: bool | None = None
    door_unlock_state: str | None = None
    call_active: bool = False
    voicemail_available: bool | None = None
    voicemail_total: int | None = None
    voicemail_unread: int | None = None
    voicemail_read: int | None = None
    voicemail_newest_at: str | None = None
    memos_available: bool | None = None
    memos_total: int | None = None
    memos_text_total: int | None = None
    memos_voice_total: int | None = None
    memos_unread: int | None = None
    memos_read: int | None = None
    memos_newest_at: str | None = None
    last_event: str | None = None
    last_event_time: str | None = None
    last_event_data: dict[str, Any] = field(default_factory=dict)
    event_sequence: int = 0
    reset_video: Callable[[], None] | None = None


@dataclass(slots=True)
class BticinoC300XRuntimeData:
    """Runtime-only resources for a config entry."""

    api: Any
    event_state: C300XEventState
    connection_state: C300XConnectionState
    capabilities: dict[str, Any]
    agent_info: dict[str, Any]
    unregister_webhook: Callable[[], None]
    unregister_event_webhook: Callable[[], None]
    unregister_event_registration: Callable[[], None] | None
    unregister_display_bridge_updates: Callable[[], None] | None
    loaded_platforms: tuple[str, ...]
    system_metrics: dict[str, Any] = field(default_factory=dict)
    system_metrics_updated_at: datetime | None = None
    answering_machine_messages: dict[str, Any] = field(default_factory=dict)
    answering_machine_messages_updated_at: datetime | None = None
    answering_machine_messages_refresh_task: Any | None = None
    memos: dict[str, Any] = field(default_factory=dict)
    memos_updated_at: datetime | None = None
    memos_refresh_task: Any | None = None
    qml_patch_status: dict[str, Any] = field(default_factory=dict)
    qml_patch_status_updated_at: datetime | None = None
    display_bridge_diagnostics: C300XCallbackDiagnostics = field(
        default_factory=C300XCallbackDiagnostics
    )
    qml_patch_diagnostics: C300XOperationDiagnostics = field(
        default_factory=C300XOperationDiagnostics
    )
    agent_diagnostics: dict[str, Any] = field(default_factory=dict)
    agent_diagnostics_updated_at: datetime | None = None
    agent_update_state: Any | None = None
