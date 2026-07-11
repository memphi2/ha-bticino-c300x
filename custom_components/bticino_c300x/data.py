"""Runtime data models for BTicino C300X."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .callback_target import (
    callback_url_host_type,
    callback_url_scheme,
)
from .media_timeline import C300XMediaTimeline
from .media_watchdog import AgentCpuWatchdog


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
        self.callback_scheme = callback_url_scheme(callback_url)
        self.callback_host_type = callback_url_host_type(callback_url)


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
        self.event_subscription_callback_scheme = callback_url_scheme(callback_url)
        self.event_subscription_callback_host_type = callback_url_host_type(callback_url)
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
    if reason.endswith(("Error", "Timeout")):
        return "agent_api"
    return reason or "unknown"


@dataclass(slots=True)
class C300XEventState:
    """Runtime state derived from device-agent push events."""

    video_available: bool = False
    video_window_available: bool = False
    video_stream_path: str | None = None
    smartphone_forwarding_mode: str | None = None
    # Last codec the audio_codec select resolved as running on the device
    # (speex|pcmu). Durable across entity unavailability so consumers -- e.g.
    # ring-capture talkback -- can pick the matching RTP payload even during an
    # agent-connection blip. None until the select first resolves it.
    audio_codec: str | None = None
    ringer_muted: bool | None = None
    ringer_volume: int | None = None
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


@dataclass(slots=True)
class BticinoC300XRuntimeData:
    """Runtime-only resources for a config entry."""

    api: Any
    event_state: C300XEventState
    connection_state: C300XConnectionState
    capabilities: dict[str, Any]
    agent_info: Mapping[str, Any]
    unregister_webhook: Callable[[], None]
    unregister_event_webhook: Callable[[], None]
    unregister_event_registration: Callable[[], None] | None
    on_runtime_registration_created: Callable[[], Awaitable[None]] | None
    unregister_display_bridge_updates: Callable[[], None] | None
    loaded_platforms: tuple[str, ...]
    prepare_doorbell_video_stop: Callable[[], Awaitable[None]] | None = None
    prepare_home_call_stop: Callable[[], Awaitable[None]] | None = None
    system_metrics: dict[str, Any] = field(default_factory=dict)
    system_metrics_updated_at: datetime | None = None
    agent_cpu_watchdog: AgentCpuWatchdog = field(default_factory=AgentCpuWatchdog)
    agent_cpu_watchdog_task: Any | None = None
    answering_machine_messages: dict[str, Any] = field(default_factory=dict)
    answering_machine_messages_updated_at: datetime | None = None
    answering_machine_messages_refresh_task: Any | None = None
    startup_sync_task: Any | None = None
    memos: dict[str, Any] = field(default_factory=dict)
    memos_updated_at: datetime | None = None
    memos_refresh_task: Any | None = None
    activations: dict[str, Any] = field(default_factory=dict)
    qml_patch_status: dict[str, Any] = field(default_factory=dict)
    qml_patch_status_updated_at: datetime | None = None
    device_user_status: dict[str, Any] = field(default_factory=dict)
    device_user_status_updated_at: datetime | None = None
    self_test_status: Mapping[str, Any] = field(default_factory=dict)
    self_test_status_updated_at: datetime | None = None
    display_bridge_diagnostics: C300XCallbackDiagnostics = field(
        default_factory=C300XCallbackDiagnostics
    )
    display_bridge_alarm_notify_pending: bool = False
    qml_patch_diagnostics: C300XOperationDiagnostics = field(
        default_factory=C300XOperationDiagnostics
    )
    agent_diagnostics: Mapping[str, Any] = field(default_factory=dict)
    agent_diagnostics_updated_at: datetime | None = None
    agent_diagnostics_updated_by: str | None = None
    agent_diagnostics_change_reason: str | None = None
    # Count of observed agent restarts (device reboots): the agent-reported
    # uptime dropping between two diagnostics samples means the process (and, on
    # this device, usually the whole unit) restarted. Session-scoped like
    # C300XConnectionState.reconnect_count.
    device_reboot_count: int = 0
    agent_uptime_seconds: int | None = None
    media_timeline: C300XMediaTimeline = field(default_factory=C300XMediaTimeline)
    agent_update_state: Any | None = None
