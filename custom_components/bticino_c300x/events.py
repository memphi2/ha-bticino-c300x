"""Device-agent push-event registration helpers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later

from .agent_diagnostics import async_refresh_agent_diagnostics
from .api import C300XAgentApi
from .callback_url import async_generate_agent_callback_url
from .capabilities import EVENT_ENTITY_EXCLUDED_TYPES, events_for_capabilities
from .const import (
    CONF_EVENT_WEBHOOK_ID,
    CONF_EVENT_WEBHOOK_TOKEN,
    DEFAULT_RECONNECT_GRACE_SECONDS,
    DOMAIN,
    SIGNAL_CONNECTION_STATE_CHANGED,
)
from .data import C300XConnectionState
from .event_types import HA_EVENT_TYPES
from .fingerprint import fnv1a64_fingerprint

_LOGGER = logging.getLogger(__name__)
_REGISTRATION_RETRY_SECONDS = 30
_MAX_REGISTRATION_RETRY_SECONDS = 300
_ENTITY_REGISTRY_REFRESH_SECONDS = 1


async def async_start_agent_event_registration(
    hass: HomeAssistant,
    entry: ConfigEntry,
    api: C300XAgentApi,
    capabilities: dict[str, Any],
    connection_state: C300XConnectionState,
) -> Callable[[], None] | None:
    """Register the HA event webhook with the C300X device agent."""

    subscription_id: str | None = None
    stopped = False
    retry_cancel: CALLBACK_TYPE | None = None
    registry_refresh_cancel: CALLBACK_TYPE | None = None
    entity_registry_cancel: CALLBACK_TYPE | None = None
    retry_delay_seconds = _REGISTRATION_RETRY_SECONDS

    async def _register(now: Any = None) -> None:
        nonlocal registry_refresh_cancel, retry_cancel, retry_delay_seconds, subscription_id
        if stopped:
            return
        if retry_cancel is not None:
            retry_cancel()
            retry_cancel = None
        if registry_refresh_cancel is not None:
            registry_refresh_cancel()
            registry_refresh_cancel = None
        base_url = await async_generate_agent_callback_url(
            hass,
            entry,
            entry.data[CONF_EVENT_WEBHOOK_ID],
        )
        token = entry.data[CONF_EVENT_WEBHOOK_TOKEN]
        try:
            registration_events = _active_events_for_capabilities(
                hass,
                entry,
                capabilities,
            )
            if registration_events:
                subscription_id = await _ensure_subscription(
                    api,
                    callback_url=base_url,
                    token=token,
                    events=registration_events,
                )
            else:
                await _remove_inactive_subscriptions(
                    api,
                    callback_url=base_url,
                )
                subscription_id = None
            connection_state.mark_connected()
            retry_delay_seconds = _REGISTRATION_RETRY_SECONDS
            async_dispatcher_send(hass, SIGNAL_CONNECTION_STATE_CHANGED, entry.entry_id)
            await async_refresh_agent_diagnostics(hass, entry)
        except Exception as err:  # noqa: BLE001 - keep HA running if agent is offline
            _LOGGER.debug("C300X event registration failed: %s", err)
            connection_state.mark_reconnecting(
                type(err).__name__,
                retry_delay_seconds,
                _connection_error_text(err),
            )
            _schedule_unavailable_expiry(hass, entry, connection_state)
            async_dispatcher_send(hass, SIGNAL_CONNECTION_STATE_CHANGED, entry.entry_id)
            if not stopped:
                retry_cancel = async_call_later(
                    hass,
                    retry_delay_seconds,
                    _register,
                )
                if retry_delay_seconds < _MAX_REGISTRATION_RETRY_SECONDS:
                    retry_delay_seconds = min(
                        _MAX_REGISTRATION_RETRY_SECONDS,
                        retry_delay_seconds * 2,
                    )

    def _schedule_registry_refresh(now: Any = None) -> None:
        nonlocal registry_refresh_cancel
        if stopped or registry_refresh_cancel is not None:
            return
        registry_refresh_cancel = async_call_later(
            hass,
            _ENTITY_REGISTRY_REFRESH_SECONDS,
            _register,
        )

    entity_registry_cancel = _async_listen_entity_registry_updates(
        hass,
        _schedule_registry_refresh,
    )
    task = hass.async_create_task(_register())

    def _unregister() -> None:
        nonlocal stopped
        stopped = True
        if not task.done():
            task.cancel()
        if retry_cancel is not None:
            retry_cancel()
        if registry_refresh_cancel is not None:
            registry_refresh_cancel()
        if entity_registry_cancel is not None:
            entity_registry_cancel()

    return _unregister


def _async_listen_entity_registry_updates(
    hass: HomeAssistant,
    callback: Callable[[Any], None],
) -> CALLBACK_TYPE | None:
    """Listen for entity enable/disable changes that affect push subscriptions."""

    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        return None
    event_type = getattr(er, "EVENT_ENTITY_REGISTRY_UPDATED", "entity_registry_updated")
    bus = getattr(hass, "bus", None)
    async_listen = getattr(bus, "async_listen", None)
    if not callable(async_listen):
        return None
    return async_listen(event_type, callback)


def _active_events_for_capabilities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    capabilities: dict[str, Any],
) -> list[str]:
    """Return only push events that currently have an enabled HA consumer."""

    events = events_for_capabilities(capabilities)
    try:
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        return events
    registry = er.async_get(hass)
    if registry is None or not hasattr(registry, "async_get_entity_id"):
        return events
    return _filter_events_for_active_entities(events, entry.entry_id, registry)


_EVENT_ENTITY_CONSUMER = ("event", "agent_event")
_EVENT_CONSUMERS: dict[str, tuple[tuple[str, str], ...]] = {
    "agent.diagnostics_changed": (("sensor", "agent_writes"),),
    "system.metrics_changed": (
        ("sensor", "device_cpu"),
        ("sensor", "device_load"),
        ("sensor", "device_temperature"),
    ),
    "answering_machine.messages_changed": (
        ("sensor", "voicemail_messages"),
        ("sensor", "voicemail_unread"),
        ("sensor", "latest_video_message"),
        ("button", "delete_latest_video_message"),
    ),
    "memos.changed": (
        ("sensor", "text_memos"),
        ("sensor", "latest_text_memo"),
        ("sensor", "voice_memos"),
        ("sensor", "latest_voice_memo"),
        ("button", "delete_latest_text_memo"),
        ("button", "delete_latest_voice_memo"),
    ),
    "smartphone_forwarding.changed": (("switch", "smartphone_forwarding"),),
    "ringer.muted": (("switch", "ringer_mute"),),
    "ringer.unmuted": (("switch", "ringer_mute"),),
    "doorbell.pressed": (
        ("event", "doorbell_event"),
        ("binary_sensor", "doorbell_video_available"),
        ("camera", "doorbell_camera"),
    ),
    "doorbell.view_requested": (
        ("binary_sensor", "doorbell_video_available"),
        ("camera", "doorbell_camera"),
    ),
    "doorbell.media.closed": (
        ("binary_sensor", "doorbell_video_available"),
        ("camera", "doorbell_camera"),
    ),
}


def _filter_events_for_active_entities(
    events: list[str],
    entry_id: str,
    registry: Any,
) -> list[str]:
    """Filter agent event subscriptions to enabled HA consumers."""

    event_entity_active = _registry_entity_active(
        registry,
        entry_id,
        *_EVENT_ENTITY_CONSUMER,
    )
    active_events: list[str] = []
    for event in events:
        ha_event_type = HA_EVENT_TYPES.get(event)
        visible_in_event_entity = (
            ha_event_type is not None and ha_event_type not in EVENT_ENTITY_EXCLUDED_TYPES
        )
        if visible_in_event_entity and event_entity_active:
            active_events.append(event)
            continue
        if any(
            _registry_entity_active(registry, entry_id, domain, key)
            for domain, key in _EVENT_CONSUMERS.get(event, ())
        ):
            active_events.append(event)
    return active_events


def _registry_entity_active(
    registry: Any,
    entry_id: str,
    domain: str,
    key: str,
) -> bool:
    unique_id = f"{entry_id}_{key}"
    entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
    if entity_id is None:
        return True
    entity = registry.async_get(entity_id)
    return entity is None or getattr(entity, "disabled_by", None) is None


async def _ensure_subscription(
    api: C300XAgentApi,
    *,
    callback_url: str,
    token: str,
    events: list[str],
) -> str | None:
    """Reuse a persisted event subscription or create one when needed."""

    subscriptions = _subscriptions(await api.async_list_event_subscriptions())
    for subscription in subscriptions:
        if _subscription_matches(subscription, callback_url, token, events):
            # Confirm the persisted subscription once on setup/reconnect. The
            # agent treats an identical POST as read-only and uses it to push
            # current event-backed snapshots without HA polling the device.
            response = await api.async_register_event_subscription(
                callback_url=callback_url,
                token=token,
                events=events,
            )
            return _subscription_id(response) or _subscription_id(
                {"subscription": subscription}
            )

    response = await api.async_register_event_subscription(
        callback_url=callback_url,
        token=token,
        events=events,
    )
    return _subscription_id(response)


async def _remove_inactive_subscriptions(
    api: C300XAgentApi,
    *,
    callback_url: str,
) -> None:
    """Remove persisted subscriptions for this HA webhook when no events are active."""

    for subscription in _subscriptions(await api.async_list_event_subscriptions()):
        if not _subscription_belongs_to_webhook(subscription, callback_url):
            continue
        subscription_id = _subscription_id({"subscription": subscription})
        if subscription_id:
            await api.async_delete_event_subscription(subscription_id)


def _subscriptions(response: dict[str, Any]) -> list[dict[str, Any]]:
    subscriptions = response.get("subscriptions")
    if not isinstance(subscriptions, list):
        return []
    return [item for item in subscriptions if isinstance(item, dict)]


def _subscription_belongs_to_webhook(
    subscription: dict[str, Any],
    callback_url: str,
) -> bool:
    """Return true for persisted subscriptions owned by this HA entry."""

    return subscription.get("callback_url") == callback_url


def _subscription_matches(
    subscription: dict[str, Any],
    callback_url: str,
    token: str,
    events: list[str],
) -> bool:
    stored_callback_url = subscription.get("callback_url")
    stored_events = subscription.get("events")
    stored_token_fingerprint = subscription.get("token_fingerprint")
    return (
        stored_callback_url == callback_url
        and stored_token_fingerprint == event_token_fingerprint(token)
        and isinstance(stored_events, list)
        and {str(event) for event in stored_events} == set(events)
    )


def event_token_fingerprint(token: str) -> str:
    """Return a stable non-secret fingerprint for subscription token matching."""

    return fnv1a64_fingerprint(token)


def _schedule_unavailable_expiry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    connection_state: C300XConnectionState,
) -> None:
    """Mark the agent unavailable after a short reconnect grace window."""

    if connection_state.expire_unavailable is not None:
        return

    def _expire(now: Any = None) -> None:
        connection_state.expire_unavailable = None
        connection_state.mark_unavailable()
        async_dispatcher_send(hass, SIGNAL_CONNECTION_STATE_CHANGED, entry.entry_id)

    connection_state.expire_unavailable = async_call_later(
        hass,
        DEFAULT_RECONNECT_GRACE_SECONDS,
        _expire,
    )


def _subscription_id(response: dict[str, Any]) -> str | None:
    subscription = response.get("subscription")
    if not isinstance(subscription, dict):
        return None
    value = subscription.get("id")
    return value if isinstance(value, str) and value else None


def _connection_error_text(err: Exception) -> str:
    """Return a compact connection error text for diagnostics."""

    name = type(err).__name__
    message = " ".join(str(err).split())
    if not message or message == name:
        return name
    value = f"{name}: {message}"
    if len(value) > 180:
        return f"{value[:177]}..."
    return value
