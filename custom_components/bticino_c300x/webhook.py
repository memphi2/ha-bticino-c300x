"""Webhook endpoints for C300X device-agent and display-bridge events."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from hmac import compare_digest
from typing import Any

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .action import ActionValidationError
from .agent_diagnostics import (
    apply_agent_diagnostics_event,
    async_refresh_agent_diagnostics,
)
from .api import (
    C300XAgentApiResponseError,
    normalize_answering_machine_messages,
    normalize_memos,
    normalize_system_metrics,
)
from .capabilities import event_label
from .const import (
    CONF_EVENT_WEBHOOK_ID,
    CONF_EVENT_WEBHOOK_TOKEN,
    CONF_SHARED_SECRET,
    CONF_VIDEO_STREAM_PATH,
    CONF_WEBHOOK_ID,
    DEFAULT_EVENT_RESET_SECONDS,
    DEFAULT_VIDEO_STREAM_PATH,
    DOMAIN,
    EVENT_AGENT_EVENT_RECEIVED,
    HEADER_EVENT_TOKEN,
    HEADER_SHARED_SECRET,
    SIGNAL_EVENT_STATE_CHANGED,
    SIGNAL_MEMOS_CHANGED,
    SIGNAL_SYSTEM_METRICS_CHANGED,
    SIGNAL_VIDEO_MESSAGES_CHANGED,
)
from .data import C300XEventState
from .entity import entry_config_value
from .event_payload import agent_event_display_data
from .event_types import normalize_event_type, payload_event_key
from .executor import (
    async_dashboard_payload,
    async_execute_action,
    async_execute_alarm_command,
    async_execute_dashboard_action,
    async_status,
    async_trigger_stair_light,
)
from .forwarding import forwarding_state_from_value
from .video import (
    call_later,
    optional_string,
    resolve_doorbell_camera_entity_id,
    safe_stream_path,
)

_LOGGER = logging.getLogger(__name__)
type _DisplayBridgeHandler = Callable[["_DisplayBridgeContext"], Awaitable[dict[str, Any]]]
type _AgentEventStateHandler = Callable[["_AgentEventContext"], None]


@dataclass(slots=True)
class _DisplayBridgeContext:
    """Display-bridge command payload context."""

    hass: HomeAssistant
    entry: ConfigEntry
    payload: dict[str, Any]


@dataclass(slots=True)
class _AgentEventContext:
    """Event payload context used by state mutation handlers."""

    hass: HomeAssistant
    entry: ConfigEntry
    event_state: C300XEventState
    event_type: str
    payload: dict[str, Any]
    data: dict[str, Any]


def async_register_webhook(hass: HomeAssistant, entry: ConfigEntry) -> Callable[[], None]:
    """Register the per-entry webhook and return an unregister callback."""

    webhook_id = entry.data[CONF_WEBHOOK_ID]

    async def _handler(
        hass: HomeAssistant,
        webhook_id: str,
        request: web.Request,
    ) -> web.Response:
        return await _async_handle_webhook(hass, entry, request)

    webhook.async_register(
        hass,
        DOMAIN,
        entry.title,
        webhook_id,
        _handler,
        local_only=False,
        allowed_methods=("POST",),
    )

    def _unregister() -> None:
        webhook.async_unregister(hass, webhook_id)

    return _unregister


def async_register_agent_event_webhook(
    hass: HomeAssistant,
    entry: ConfigEntry,
    event_state: C300XEventState,
) -> Callable[[], None]:
    """Register the device-agent-to-HA push-event webhook."""

    webhook_id = entry.data[CONF_EVENT_WEBHOOK_ID]

    async def _handler(
        hass: HomeAssistant,
        webhook_id: str,
        request: web.Request,
    ) -> web.Response:
        return await _async_handle_agent_event(hass, entry, event_state, request)

    webhook.async_register(
        hass,
        DOMAIN,
        f"{entry.title} device-agent events",
        webhook_id,
        _handler,
        local_only=False,
        allowed_methods=("POST",),
    )

    def _unregister() -> None:
        webhook.async_unregister(hass, webhook_id)

    return _unregister


async def _async_handle_webhook(
    hass: HomeAssistant,
    entry: ConfigEntry,
    request: web.Request,
) -> web.Response:
    """Handle a webhook request from the local C300X display bridge."""

    expected_secret = entry.data.get(CONF_SHARED_SECRET, "")
    supplied_secret = request.headers.get(HEADER_SHARED_SECRET, "")
    if not expected_secret or not compare_digest(expected_secret, supplied_secret):
        return _json_error("unauthorized", status=401)

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - request body parsing must not leak details
        return _json_error("invalid_json", status=400)

    if not isinstance(payload, dict):
        return _json_error("invalid_payload", status=400)

    message_type = payload.get("type", "status")
    handler = _DISPLAY_BRIDGE_HANDLERS.get(str(message_type))
    if handler is None:
        return _json_error("unsupported_type", status=400)

    try:
        return web.json_response(
            await handler(_DisplayBridgeContext(hass, entry, payload))
        )
    except KeyError:
        return _json_error("unknown_action", status=404)
    except (ActionValidationError, ValueError) as err:
        return _json_error(str(err), status=400)
    except Exception as err:  # noqa: BLE001 - HA service errors should be contained
        _LOGGER.warning("C300X webhook command failed: %s", err)
        return _json_error("command_failed", status=500)


async def _display_bridge_status(context: _DisplayBridgeContext) -> dict[str, Any]:
    return await async_status(context.hass, context.entry)


async def _display_bridge_dashboard(context: _DisplayBridgeContext) -> dict[str, Any]:
    return await async_dashboard_payload(context.hass, context.entry)


async def _display_bridge_action(context: _DisplayBridgeContext) -> dict[str, Any]:
    return await async_execute_action(
        context.hass,
        context.entry,
        context.payload.get("action_id", ""),
    )


async def _display_bridge_dashboard_action(
    context: _DisplayBridgeContext,
) -> dict[str, Any]:
    return await async_execute_dashboard_action(
        context.hass,
        context.entry,
        str(context.payload.get("entity_id", "")),
    )


async def _display_bridge_stair_light(context: _DisplayBridgeContext) -> dict[str, Any]:
    return await async_trigger_stair_light(
        context.hass,
        context.entry,
        optional_string(context.payload.get("address")),
    )


async def _display_bridge_alarm_command(
    context: _DisplayBridgeContext,
) -> dict[str, Any]:
    return await async_execute_alarm_command(
        context.hass,
        context.entry,
        str(context.payload.get("command", "")),
        optional_string(context.payload.get("code")),
        force=context.payload.get("force") is True,
        check=context.payload.get("check") is True,
    )


_DISPLAY_BRIDGE_HANDLERS: dict[str, _DisplayBridgeHandler] = {
    "status": _display_bridge_status,
    "alarm_status": _display_bridge_status,
    "dashboard": _display_bridge_dashboard,
    "action": _display_bridge_action,
    "dashboard_action": _display_bridge_dashboard_action,
    "stair_light": _display_bridge_stair_light,
    "alarm_command": _display_bridge_alarm_command,
}


async def _async_handle_agent_event(
    hass: HomeAssistant,
    entry: ConfigEntry,
    event_state: C300XEventState,
    request: web.Request,
) -> web.Response:
    """Handle device-agent push events."""

    runtime_data = getattr(entry, "runtime_data", None)
    runtime_event_state = getattr(runtime_data, "event_state", None)
    if getattr(runtime_event_state, "event_sequence", None) is not None:
        event_state = runtime_event_state

    expected_token = entry.data.get(CONF_EVENT_WEBHOOK_TOKEN, "")
    supplied_token = request.headers.get(HEADER_EVENT_TOKEN, "")
    if not expected_token or not compare_digest(expected_token, supplied_token):
        return _json_error("unauthorized", status=401)

    payload = await _event_payload(request)
    event_type = _normalize_event_type(_event_type_value(payload))
    if not event_type:
        return _json_error("unsupported_event", status=400)

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    snapshot = _is_snapshot_payload(payload)
    if event_type == "system_metrics_changed":
        _apply_system_metrics_event(hass, entry, data)
        return web.json_response({"ok": True})
    if event_type == "agent_diagnostics_changed":
        if apply_agent_diagnostics_event(hass, entry, data) is None:
            await async_refresh_agent_diagnostics(hass, entry)
        return web.json_response({"ok": True})

    event_at = dt_util.utcnow().isoformat()
    _apply_agent_event_state(
        _AgentEventContext(
            hass=hass,
            entry=entry,
            event_state=event_state,
            event_type=event_type,
            payload=payload,
            data=data,
        )
    )

    event_data = _event_data(
        _AgentEventContext(
            hass=hass,
            entry=entry,
            event_state=event_state,
            event_type=event_type,
            payload=payload,
            data=data,
        ),
        event_at,
    )

    if snapshot:
        _apply_snapshot_entity_refresh(hass, entry, event_type)
    else:
        event_state.last_event = event_type
        event_state.last_event_time = event_at
        event_state.event_sequence += 1
        event_state.last_event_data = event_data
        hass.bus.async_fire(
            EVENT_AGENT_EVENT_RECEIVED,
            event_data,
        )
        async_dispatcher_send(hass, SIGNAL_EVENT_STATE_CHANGED, entry.entry_id)
    return web.json_response({"ok": True})


async def _event_payload(request: web.Request) -> dict[str, Any]:
    if request.method != "POST":
        return {}
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - event parsing must not leak details
        return {}
    return payload if isinstance(payload, dict) else {}


def _apply_agent_event_state(context: _AgentEventContext) -> None:
    """Apply state side effects for a normalized device-agent event."""

    handler = _AGENT_EVENT_STATE_HANDLERS.get(context.event_type)
    if handler is not None:
        handler(context)


def _apply_doorbell_pressed(context: _AgentEventContext) -> None:
    _activate_doorbell_state(context)


def _apply_doorbell_view_requested(context: _AgentEventContext) -> None:
    _activate_video_state(context, default_available=True)


def _apply_doorbell_media_closed(context: _AgentEventContext) -> None:
    _clear_video_state(context.event_state)


def _apply_door_unlock_event(context: _AgentEventContext) -> None:
    context.event_state.door_unlock_state = context.event_type


def _apply_call_event(context: _AgentEventContext) -> None:
    context.event_state.call_active = context.event_type == "call_started"


def _apply_ringer_event(context: _AgentEventContext) -> None:
    context.event_state.ringer_muted = context.event_type == "ringer_muted"


def _apply_smartphone_forwarding_event(context: _AgentEventContext) -> None:
    context.event_state.smartphone_forwarding_mode = _optional_forwarding_mode(
        context.data.get("mode")
    )


def _apply_voicemail_event_context(context: _AgentEventContext) -> None:
    _apply_voicemail_event(context.event_state, context.data)
    if _is_snapshot_payload(context.payload):
        _cache_voicemail_snapshot(context.entry, context.event_state)


def _apply_memos_event_context(context: _AgentEventContext) -> None:
    _apply_memos_event(context.event_state, context.data)
    if _is_snapshot_payload(context.payload):
        _cache_memos_snapshot(context.entry, context.event_state)


_AGENT_EVENT_STATE_HANDLERS: dict[str, _AgentEventStateHandler] = {
    "doorbell_pressed": _apply_doorbell_pressed,
    "doorbell_view_requested": _apply_doorbell_view_requested,
    "doorbell_media_closed": _apply_doorbell_media_closed,
    "door_unlock_started": _apply_door_unlock_event,
    "door_unlock_ended": _apply_door_unlock_event,
    "call_started": _apply_call_event,
    "call_ended": _apply_call_event,
    "ringer_muted": _apply_ringer_event,
    "ringer_unmuted": _apply_ringer_event,
    "smartphone_forwarding_changed": _apply_smartphone_forwarding_event,
    "answering_machine_messages_changed": _apply_voicemail_event_context,
    "memos_changed": _apply_memos_event_context,
}


def _activate_doorbell_state(context: _AgentEventContext) -> None:
    _activate_video_state(context, default_available=False)


def _activate_video_state(
    context: _AgentEventContext,
    *,
    default_available: bool,
) -> None:
    video = (
        context.data.get("video")
        if isinstance(context.data.get("video"), dict)
        else {}
    )
    context.event_state.video_available = bool(video.get("available", default_available))
    stream_path = video.get("stream_path") or video.get("rtsp_url")
    context.event_state.video_stream_path = str(stream_path) if stream_path else None
    ttl_seconds = _ttl_seconds(context.payload.get("ttl_seconds"))
    context.event_state.video_active_until = (
        (dt_util.utcnow() + timedelta(seconds=ttl_seconds)).isoformat()
        if ttl_seconds > 0
        else None
    )
    _schedule_video_reset(
        context.hass,
        context.entry,
        context.event_state,
        ttl_seconds,
    )


def _schedule_video_reset(
    hass: HomeAssistant,
    entry: ConfigEntry,
    event_state: C300XEventState,
    ttl_seconds: int,
) -> None:
    if event_state.reset_video:
        event_state.reset_video()
        event_state.reset_video = None
    if ttl_seconds <= 0:
        return

    def _reset_video(now=None) -> None:
        event_state.reset_video = None
        _clear_video_state(event_state, cancel_timer=False)
        async_dispatcher_send(hass, SIGNAL_EVENT_STATE_CHANGED, entry.entry_id)

    event_state.reset_video = call_later(hass, ttl_seconds, _reset_video)


def _clear_video_state(
    event_state: C300XEventState,
    *,
    cancel_timer: bool = True,
) -> None:
    if cancel_timer and event_state.reset_video:
        event_state.reset_video()
    event_state.reset_video = None
    event_state.video_available = False
    event_state.video_active_until = None
    event_state.video_stream_path = None


def _event_data(context: _AgentEventContext, event_at: str) -> dict[str, Any]:
    label = event_label(context.event_type, getattr(context.hass.config, "language", None))
    label_en = event_label(context.event_type, "en")
    label_de = event_label(context.event_type, "de")
    label_it = event_label(context.event_type, "it")
    label_fr = event_label(context.event_type, "fr")
    event_name = label or label_en or context.event_type
    event_data: dict[str, Any] = {
        "entry_id": context.entry.entry_id,
        "event": event_name,
        "event_key": context.event_type,
        "event_name": event_name,
        "event_type": context.event_type,
        "event_value": event_name,
        "event_label": label,
        "event_label_en": label_en,
        "event_label_de": label_de,
        "event_label_it": label_it,
        "event_label_fr": label_fr,
        "event_at": event_at,
        "data": context.data,
    }
    if context.event_type in {"doorbell_pressed", "doorbell_view_requested"}:
        event_data.update(
            _doorbell_event_data(
                context.hass,
                context.entry,
                context.event_state,
                _ttl_seconds(context.payload.get("ttl_seconds")),
            )
        )
    elif context.event_type in {"door_unlock_started", "door_unlock_ended"}:
        event_data["address"] = context.data.get("address")
    elif context.event_type in {"ringer_muted", "ringer_unmuted"}:
        event_data["muted"] = context.event_state.ringer_muted
    elif context.event_type == "smartphone_forwarding_changed":
        event_data["mode"] = context.event_state.smartphone_forwarding_mode
    elif context.event_type == "answering_machine_messages_changed":
        event_data["voicemail"] = _voicemail_event_data(context.event_state)
    elif context.event_type == "memos_changed":
        event_data["memos"] = _memos_event_data(context.event_state)
    return agent_event_display_data(
        event_data,
        getattr(context.hass.config, "language", None),
    )


def _apply_voicemail_event(event_state: C300XEventState, data: dict[str, Any]) -> None:
    voicemail = data.get("voicemail") if isinstance(data.get("voicemail"), dict) else data
    event_state.voicemail_available = _optional_bool(voicemail.get("available"))
    event_state.voicemail_total = _optional_int(voicemail.get("total"))
    event_state.voicemail_unread = _optional_int(voicemail.get("unread"))
    event_state.voicemail_read = _optional_int(voicemail.get("read"))
    event_state.voicemail_newest_at = optional_string(voicemail.get("newest_at"))


def _voicemail_event_data(event_state: C300XEventState) -> dict[str, Any]:
    return {
        "available": event_state.voicemail_available,
        "total": event_state.voicemail_total,
        "unread": event_state.voicemail_unread,
        "read": event_state.voicemail_read,
        "newest_at": event_state.voicemail_newest_at,
    }


def _apply_memos_event(event_state: C300XEventState, data: dict[str, Any]) -> None:
    memos = data.get("memos") if isinstance(data.get("memos"), dict) else data
    event_state.memos_available = _optional_bool(memos.get("available"))
    event_state.memos_total = _optional_int(memos.get("total"))
    event_state.memos_text_total = _optional_int(memos.get("text_total"))
    event_state.memos_voice_total = _optional_int(memos.get("voice_total"))
    event_state.memos_unread = _optional_int(memos.get("unread"))
    event_state.memos_read = _optional_int(memos.get("read"))
    event_state.memos_newest_at = optional_string(memos.get("newest_at"))


def _memos_event_data(event_state: C300XEventState) -> dict[str, Any]:
    return {
        "available": event_state.memos_available,
        "total": event_state.memos_total,
        "text_total": event_state.memos_text_total,
        "voice_total": event_state.memos_voice_total,
        "unread": event_state.memos_unread,
        "read": event_state.memos_read,
        "newest_at": event_state.memos_newest_at,
    }


def _apply_snapshot_entity_refresh(
    hass: HomeAssistant,
    entry: ConfigEntry,
    event_type: str,
) -> None:
    """Refresh stateful entities for subscription snapshots without firing events."""

    if event_type == "answering_machine_messages_changed":
        async_dispatcher_send(hass, SIGNAL_VIDEO_MESSAGES_CHANGED, entry.entry_id)
    elif event_type == "memos_changed":
        async_dispatcher_send(hass, SIGNAL_MEMOS_CHANGED, entry.entry_id)


def _cache_voicemail_snapshot(entry: ConfigEntry, event_state: C300XEventState) -> None:
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None:
        return
    current = getattr(runtime_data, "answering_machine_messages", {})
    messages = current.get("messages", []) if isinstance(current, dict) else []
    runtime_data.answering_machine_messages = normalize_answering_machine_messages(
        {**_voicemail_event_data(event_state), "messages": messages}
    )
    runtime_data.answering_machine_messages_updated_at = dt_util.utcnow()


def _cache_memos_snapshot(entry: ConfigEntry, event_state: C300XEventState) -> None:
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None:
        return
    current = getattr(runtime_data, "memos", {})
    memos = current.get("memos", []) if isinstance(current, dict) else []
    runtime_data.memos = normalize_memos({**_memos_event_data(event_state), "memos": memos})
    runtime_data.memos_updated_at = dt_util.utcnow()


def _apply_system_metrics_event(
    hass: HomeAssistant,
    entry: ConfigEntry,
    data: dict[str, Any],
) -> None:
    metrics = (
        data.get("system_metrics")
        if isinstance(data.get("system_metrics"), dict)
        else data
    )
    try:
        entry.runtime_data.system_metrics = normalize_system_metrics(metrics)
    except C300XAgentApiResponseError:
        _LOGGER.debug("Ignoring invalid C300X system metrics event payload")
        return
    entry.runtime_data.system_metrics_updated_at = dt_util.utcnow()
    async_dispatcher_send(hass, SIGNAL_SYSTEM_METRICS_CHANGED, entry.entry_id)


def _doorbell_event_data(
    hass: HomeAssistant,
    entry: ConfigEntry,
    event_state: C300XEventState,
    active_seconds: int,
) -> dict[str, Any]:
    event_data = {
        "active_seconds": active_seconds,
        "active_until": event_state.video_active_until,
        **_video_event_data(hass, entry, event_state),
    }
    return event_data


def _video_event_data(
    hass: HomeAssistant,
    entry: ConfigEntry,
    event_state: C300XEventState,
) -> dict[str, Any]:
    camera_entity_id = resolve_doorbell_camera_entity_id(hass, entry)
    stream_path = safe_stream_path(
        event_state.video_stream_path
        or entry_config_value(entry, CONF_VIDEO_STREAM_PATH, DEFAULT_VIDEO_STREAM_PATH)
    )
    event_data: dict[str, Any] = {
        "video_available": camera_entity_id is not None,
        "video_window_available": event_state.video_available,
        "video_active_until": event_state.video_active_until,
        "stream_path": stream_path,
    }
    if camera_entity_id is not None:
        event_data["camera_entity_id"] = camera_entity_id
    return event_data


def _normalize_event_type(value: Any) -> str:
    return normalize_event_type(value) or ""


def _event_type_value(payload: dict[str, Any]) -> Any:
    if not isinstance(payload, dict):
        return ""
    return payload_event_key(payload) or ""


def _ttl_seconds(value: Any) -> int:
    try:
        ttl_seconds = int(value)
    except (TypeError, ValueError):
        return DEFAULT_EVENT_RESET_SECONDS
    return max(ttl_seconds, 0)


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "on", "muted"}:
        return True
    if text in {"false", "0", "off", "unmuted"}:
        return False
    return None


def _optional_forwarding_mode(value: Any) -> str | None:
    return forwarding_state_from_value(value)


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_snapshot_payload(payload: dict[str, Any]) -> bool:
    """Return true when the agent explicitly marks a callback as a snapshot."""

    for key in ("snapshot", "replay"):
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() == "true":
            return True
    source = payload.get("source")
    return isinstance(source, str) and source.strip().lower() == "snapshot"


def _json_error(error: str, status: int) -> web.Response:
    return web.json_response({"ok": False, "error": error}, status=status)
