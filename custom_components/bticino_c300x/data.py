"""Runtime data models for BTicino C300X."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class C300XConnectionState:
    """Runtime connection state for the device agent."""

    available: bool = True
    connection_state: str = "connected"
    reconnect_count: int = 0
    last_reconnect_reason: str | None = None
    last_connection_error: str | None = None
    next_reconnect_delay_seconds: int | None = None
    was_reconnecting: bool = False
    expire_unavailable: Callable[[], None] | None = None

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
        self.last_reconnect_reason = reason
        self.last_connection_error = error or reason
        self.next_reconnect_delay_seconds = next_delay_seconds
        self.was_reconnecting = True

    def mark_unavailable(self) -> None:
        """Mark the agent disconnected after reconnect grace expires."""

        self.available = False
        self.connection_state = "disconnected"


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
    agent_diagnostics: dict[str, Any] = field(default_factory=dict)
    agent_diagnostics_updated_at: datetime | None = None
