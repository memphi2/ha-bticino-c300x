"""Runtime write-diagnostics helpers for the C300X device agent."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import (
    C300XAgentApiError,
    C300XAgentApiResponseError,
    normalize_agent_diagnostics,
)
from .capabilities import diagnostics_supported
from .const import SIGNAL_AGENT_DIAGNOSTICS_CHANGED
from .entry_types import BticinoC300XConfigEntry

_WRITE_DIAGNOSTIC_KEYS = (
    "agent_write_count",
    "last_write_at",
    "last_write_reason",
    "last_write_class",
    "qml_patch_last_action",
)
_MEDIA_DIAGNOSTIC_KEYS = (
    "video_running",
    "video_media_starting",
    "video_call_active",
    "video_clients",
    "video_media_owner",
    "video_external_media_active",
    "video_external_owner",
    "video_last_block_reason",
    "video_bridge_media_active",
    "video_bridge_stop_in_progress",
    "video_bridge_open_fds",
    "video_bridge_active_threads",
    "ring_receiver_running",
    "ring_registered",
    "ring_call_active",
    "ring_media_active",
    "home_call_running",
    "home_call_active",
)
_UI_EVENT_DIAGNOSTIC_KEYS = (
    "ui_event_waiters",
    "ui_event_waiter_capacity",
    "ui_event_waiter_overflows",
)


def publish_agent_media_facts(
    hass: HomeAssistant | None,
    entry: BticinoC300XConfigEntry,
    bridge: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    """Publish the camera's live media view for diagnostics consumers.

    The agent pushes ``agent.diagnostics_changed`` only from writes, and its
    payload carries write counters only -- nothing ever refreshes the media
    half of the stored diagnostics snapshot when a call starts or ends. The
    camera already keeps an event- and status-fed bridge view, so mirroring it
    here keeps the diagnostics sensor honest without a single extra request to
    the device.
    """

    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None or not isinstance(bridge, Mapping):
        return None
    facts = _media_facts_from_bridge(bridge)
    # Stamp on every observation, not only on change: the timestamp says when
    # this view was last confirmed, and a call that stays active must not age
    # out behind an unrelated snapshot refresh.
    runtime_data.agent_media_facts_updated_at = datetime.now(UTC)
    if facts == runtime_data.agent_media_facts:
        return facts
    runtime_data.agent_media_facts = facts
    if isinstance(hass, HomeAssistant):
        # Consumers read the facts on demand, so the signal is only the
        # re-render trigger: a camera that is not wired into hass yet (entity
        # construction, initial status apply) just stores them.
        async_dispatcher_send(hass, SIGNAL_AGENT_DIAGNOSTICS_CHANGED, entry.entry_id)
    return facts


def _media_facts_from_bridge(bridge: Mapping[str, Any]) -> dict[str, Any]:
    """Return diagnostics-shaped media facts, every key always answered.

    media_owner is the authority, not the presence of a key. The camera's
    bridge view is cumulative -- push events merge into it and the closed-event
    reset clears only some keys -- so a value left over from an earlier status
    would otherwise be republished as live and latch the sensor. The agent
    derives the owner from exactly these flags and only ever names one, so
    scoping each flag to its owner cannot report a finished call as running.
    """

    owner = bridge.get("media_owner")
    owner_name = owner if isinstance(owner, str) else None
    idle = owner_name in (None, "", "idle")
    agent_owned = owner_name == "agent"
    ring_owned = owner_name == "ring"
    home_owned = owner_name == "home_call"

    def owned_flag(bridge_key: str, owned: bool, *, unstated: bool = False) -> bool:
        """Return a flag only its owner may set, preferring the reported value.

        Push-event bridges carry fewer keys than the status endpoint, so an
        absent key is unknown, not false. `unstated` says what the owner alone
        proves: it must never claim more than the payload does.
        """

        if not owned:
            return False
        if bridge_key in bridge:
            return bool(bridge[bridge_key])
        return unstated

    return {
        # Not part of how the agent derives the owner, so it is reported as
        # given -- the camera clears it together with the rest of the window.
        "video_media_starting": bool(bridge.get("media_starting")),
        "video_call_active": owned_flag("call_active", agent_owned),
        # Owner "agent" is bridge media OR an on-demand call, so media-active is
        # the part it proves on its own.
        "video_bridge_media_active": owned_flag(
            "media_active", agent_owned, unstated=True
        ),
        "video_bridge_stop_in_progress": bool(bridge.get("stop_in_progress")),
        "video_external_media_active": (
            not idle
            and not agent_owned
            and not ring_owned
            and not home_owned
            and bool(bridge.get("external_media_active"))
        ),
        "ring_call_active": owned_flag("ring_call_active", ring_owned, unstated=True),
        "ring_media_active": ring_owned and bool(bridge.get("ring_media_active")),
        # Owner "home_call" is set while starting too, so an unstated home call
        # is reported as starting rather than as an established call.
        "home_call_running": owned_flag(
            "home_call_running",
            home_owned,
            unstated="home_call_active" not in bridge,
        ),
        "home_call_active": owned_flag("home_call_active", home_owned),
        "video_clients": (
            int(bridge["clients"]) if isinstance(bridge.get("clients"), int) else 0
        ),
        "video_media_owner": owner_name,
    }


async def async_refresh_agent_diagnostics(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> Mapping[str, Any] | None:
    """Refresh safe write diagnostics once and notify interested entities."""

    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None or not diagnostics_supported(runtime_data.capabilities):
        return None
    try:
        diagnostics = cast(Mapping[str, Any], await runtime_data.api.async_diagnostics())
    except C300XAgentApiError:
        return None
    _store_agent_diagnostics(
        hass,
        entry,
        diagnostics,
        updated_by="api_refresh",
        reason="api_refresh",
        notify_if_unchanged=True,
    )
    return diagnostics


def apply_agent_diagnostics_event(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    data: dict[str, Any],
) -> Mapping[str, Any] | None:
    """Apply write diagnostics carried in a push event without callback recursion."""

    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None or not diagnostics_supported(runtime_data.capabilities):
        return None
    try:
        diagnostics = normalize_agent_diagnostics(data)
    except C300XAgentApiResponseError:
        return None
    _store_agent_diagnostics(
        hass,
        entry,
        diagnostics,
        updated_by="push_event",
        reason=_agent_diagnostics_change_reason(
            runtime_data.agent_diagnostics,
            diagnostics,
        ),
        notify_if_unchanged=False,
    )
    return diagnostics


def _store_agent_diagnostics(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    diagnostics: Mapping[str, Any],
    *,
    updated_by: str,
    reason: str,
    notify_if_unchanged: bool,
) -> bool:
    """Store diagnostics and dispatch only when the visible state should change."""

    runtime_data = entry.runtime_data
    _update_device_reboot_count(runtime_data, diagnostics)
    changed = diagnostics != runtime_data.agent_diagnostics
    if not changed and not notify_if_unchanged:
        return False
    runtime_data.agent_diagnostics = diagnostics
    runtime_data.agent_diagnostics_updated_at = datetime.now(UTC)
    runtime_data.agent_diagnostics_updated_by = updated_by
    runtime_data.agent_diagnostics_change_reason = (
        reason if changed else f"{reason}_unchanged"
    )
    async_dispatcher_send(hass, SIGNAL_AGENT_DIAGNOSTICS_CHANGED, entry.entry_id)
    from .repair_issues import async_sync_entry_repair_issues

    async_sync_entry_repair_issues(hass, entry)
    return True


def _update_device_reboot_count(
    runtime_data: Any,
    diagnostics: Mapping[str, Any],
) -> None:
    """Count a device/agent reboot when the reported agent uptime drops.

    The agent reports a monotonic uptime; within one process it only grows, so a
    new sample lower than the previous one means the agent restarted -- on this
    device that is (almost always) a full reboot. Old agents that do not report
    an uptime leave the value None and are simply skipped.
    """

    new_uptime = diagnostics.get("agent_uptime_seconds")
    if not isinstance(new_uptime, int):
        return
    previous = runtime_data.agent_uptime_seconds
    if isinstance(previous, int) and new_uptime < previous:
        runtime_data.device_reboot_count += 1
    runtime_data.agent_uptime_seconds = new_uptime


def _agent_diagnostics_change_reason(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
) -> str:
    """Return a compact operator-facing reason for a diagnostics change."""

    if not previous:
        return "initial_push"
    if _changed(previous, current, _WRITE_DIAGNOSTIC_KEYS):
        return "write_diagnostics_changed"
    if _changed(previous, current, _MEDIA_DIAGNOSTIC_KEYS):
        return "media_diagnostics_changed"
    if _changed(previous, current, _UI_EVENT_DIAGNOSTIC_KEYS):
        return "display_event_watchdog_changed"
    if previous.get("last_wake_reason") != current.get("last_wake_reason"):
        return "agent_wake_reason_changed"
    if previous.get("poll_wakeups") != current.get("poll_wakeups"):
        return "agent_poll_activity_changed"
    return "agent_diagnostics_changed"


def _changed(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    keys: tuple[str, ...],
) -> bool:
    return any(previous.get(key) != current.get(key) for key in keys)
