"""Typed diagnostics device-agent contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .base import AgentContract


@dataclass(frozen=True, slots=True, eq=False)
class AgentDiagnosticsStatus(AgentContract):
    """Normalized non-sensitive device-agent diagnostics."""

    agent_write_count: int
    last_write_at: int | None
    last_write_reason: str | None
    last_write_class: str | None
    qml_patch_last_action: str | None
    loop_iterations: int | None
    poll_wakeups: int | None
    accepted_clients: int | None
    last_wake_reason: str | None
    last_poll_timeout_ms: int | None
    last_poll_count: int | None
    open_fd_count: int | None
    agent_init_script_present: bool | None
    agent_init_link_ok: bool | None
    subscription_count: int | None
    recent_event_count: int | None
    recent_event_capacity: int | None
    display_bridge_registered: bool | None
    display_bridge_disabled: bool | None
    home_assistant_connected_this_run: bool | None
    home_assistant_last_seen_at: int | None
    ui_event_revision: int | None
    video_running: bool | None
    video_rtsp_server_running: bool | None
    video_media_starting: bool | None
    video_call_active: bool | None
    video_clients: int | None
    video_media_owner: str | None
    video_external_media_active: bool | None
    video_external_owner: str | None
    video_last_block_reason: str | None
    video_bridge_running: bool | None
    video_bridge_media_active: bool | None
    video_bridge_stop_in_progress: bool | None
    video_bridge_open_fds: int | None
    video_bridge_active_threads: int | None
    ring_receiver_running: bool | None
    ring_registered: bool | None
    ring_call_active: bool | None
    ring_media_active: bool | None
    home_call_running: bool | None
    home_call_active: bool | None
    flexisip_backup_available: bool | None
    flexisip_restart_marker: bool | None
    flexisip_backup_marker: bool | None
    flexisip_reference_state: str | None
