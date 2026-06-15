"""Shared helpers for C300X service use cases."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from ..agent_diagnostics import async_refresh_agent_diagnostics
from ..capabilities import (
    capability_is_supported,
    entry_gui_function_patch_active,
    maintenance_action_is_supported,
    memo_text_write_supported,
)
from ..const import CONF_MAINTENANCE_TOKEN
from ..entity import entry_video_enabled
from ..entry_config import entry_config_value
from ..exceptions import service_validation_error
from ..qml_patch import async_refresh_qml_patch_status

MEDIA_PLAYER_DOMAIN = "media_player"
MEDIA_PLAYER_PLAY_MEDIA_SERVICE = "play_media"


async def raise_agent_command_failed(awaitable: Awaitable[Any]) -> None:
    """Run an agent command and translate failures into HA service errors."""

    try:
        await awaitable
    except Exception as err:
        raise service_validation_error("agent_command_failed") from err


def ensure_maintenance_action(entry: Any, action: str) -> None:
    """Reject maintenance services unless the agent advertises and authorizes them."""

    capabilities = getattr(entry.runtime_data, "capabilities", {})
    if not maintenance_action_is_supported(
        capabilities,
        action,
        entry_config_value(entry, CONF_MAINTENANCE_TOKEN, ""),
    ):
        raise service_validation_error("maintenance_action_not_supported")


def ensure_doorbell_video_supported(entry: Any) -> None:
    """Reject video activation unless HA and the agent expose doorbell video."""

    runtime_data = getattr(entry, "runtime_data", None)
    capabilities = getattr(runtime_data, "capabilities", {})
    if not (
        entry_video_enabled(entry)
        and capability_is_supported(capabilities, "doorbell_video")
    ):
        raise service_validation_error("doorbell_video_not_available")


def ensure_doorbell_call_supported(entry: Any) -> None:
    """Reject ring-call control unless HA and the agent expose it."""

    runtime_data = getattr(entry, "runtime_data", None)
    capabilities = getattr(runtime_data, "capabilities", {})
    if not (
        entry_video_enabled(entry)
        and capability_is_supported(capabilities, "doorbell_call")
    ):
        raise service_validation_error("doorbell_video_not_available")


def ensure_home_call_supported(entry: Any) -> None:
    """Reject local Home Call actions unless HA and the agent expose them."""

    runtime_data = getattr(entry, "runtime_data", None)
    capabilities = getattr(runtime_data, "capabilities", {})
    if not (
        entry_video_enabled(entry)
        and capability_is_supported(capabilities, "home_call")
    ):
        raise service_validation_error("home_call_not_available")


def ensure_text_memo_write_supported(entry: Any) -> None:
    """Reject text-memo creation unless the agent exposes it."""

    runtime_data = getattr(entry, "runtime_data", None)
    capabilities = getattr(runtime_data, "capabilities", {})
    if not memo_text_write_supported(capabilities):
        raise service_validation_error("text_memo_write_not_supported")


async def async_ensure_gui_function_patch(entry: Any) -> None:
    """Reject display-coupled actions unless the full C300X Display patch is active."""

    if entry_gui_function_patch_active(entry):
        return
    try:
        await async_refresh_qml_patch_status(entry)
    except Exception as err:
        raise service_validation_error("agent_command_failed") from err
    if not entry_gui_function_patch_active(entry):
        raise service_validation_error("gui_function_patch_required")


async def latest_item_id_for_entry(
    entry: Any,
    *,
    cache_attr: str,
    refresh: Callable[[], Awaitable[dict[str, Any]]],
    latest: Callable[[dict[str, Any]], str | None],
    unavailable_error: str,
) -> str:
    """Return a cached latest id, refreshing once if the cache has none."""

    payload = getattr(entry.runtime_data, cache_attr, {})
    item_id = latest(payload) if isinstance(payload, dict) else None
    if item_id is not None:
        return item_id
    try:
        payload = await refresh()
    except Exception as err:
        raise service_validation_error("agent_command_failed") from err
    item_id = latest(payload)
    if item_id is None:
        raise service_validation_error(unavailable_error)
    return item_id


async def async_refresh_after_message_mutation(
    hass: HomeAssistant,
    entry: Any,
    *,
    refresh: Callable[[], Awaitable[dict[str, Any]]],
    signal: str,
) -> None:
    """Refresh a message-backed cache and notify HA listeners."""

    try:
        await refresh()
    except Exception as err:
        raise service_validation_error("agent_command_failed") from err
    async_dispatcher_send(hass, signal, entry.entry_id)
    await async_refresh_agent_diagnostics(hass, entry)


async def async_play_media(
    hass: HomeAssistant,
    media_player_entity_id: str,
    *,
    media_content_id: str,
    media_content_type: str,
) -> None:
    """Play one media-source item through Home Assistant media_player."""

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        MEDIA_PLAYER_PLAY_MEDIA_SERVICE,
        {
            ATTR_ENTITY_ID: media_player_entity_id,
            "media_content_id": media_content_id,
            "media_content_type": media_content_type,
        },
        blocking=True,
    )
