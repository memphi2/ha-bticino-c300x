"""Home Assistant services for local testing and automation."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import voluptuous as vol
from homeassistant.components.media_player import (
    DOMAIN as MEDIA_PLAYER_DOMAIN,
)
from homeassistant.components.media_player import (
    SERVICE_PLAY_MEDIA,
    MediaType,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)

from .action import ActionValidationError
from .agent_diagnostics import async_refresh_agent_diagnostics
from .capabilities import (
    answering_machine_message_delete_supported,
    entry_device_ui_enabled,
    entry_gui_function_patch_active,
    maintenance_action_is_supported,
    memo_delete_supported,
)
from .const import (
    CONF_MAINTENANCE_TOKEN,
    DOMAIN,
    LOCK_ID_PATTERN,
    SERVICE_ALARM_COMMAND,
    SERVICE_DELETE_LATEST_TEXT_MEMO,
    SERVICE_DELETE_LATEST_VIDEO_MESSAGE,
    SERVICE_DELETE_LATEST_VOICE_MEMO,
    SERVICE_PLAY_LATEST_VIDEO_MESSAGE,
    SERVICE_PLAY_LATEST_VOICE_MEMO,
    SERVICE_REBOOT,
    SERVICE_RELOAD_GUI,
    SERVICE_RUN_ACTION,
    SERVICE_STAIR_LIGHT,
    SERVICE_UNLOCK_DOOR,
    SIGNAL_MEMOS_CHANGED,
    SIGNAL_QML_PATCH_CHANGED,
    SIGNAL_VIDEO_MESSAGES_CHANGED,
    STAIR_LIGHT_ADDRESS_PATTERN,
)
from .entity import entry_config_value
from .exceptions import service_validation_error
from .executor import (
    async_execute_action,
    async_execute_alarm_command,
    async_trigger_stair_light,
    async_unlock_door,
)
from .memos import (
    latest_memo_id,
    latest_voice_memo_audio_id,
    voice_memo_media_source_id,
)
from .qml_patch import async_refresh_qml_patch_status
from .video_messages import latest_video_message_id, video_message_media_source_id

_ATTR_ACTION_ID = "action_id"
_ATTR_ADDRESS = "address"
_ATTR_CODE = "code"
_ATTR_COMMAND = "command"
_ATTR_ENTRY_ID = "entry_id"
_ATTR_FORCE = "force"
_ATTR_LOCK_ID = "lock_id"
_ATTR_MEDIA_PLAYER_ENTITY_ID = "media_player_entity_id"
_STAIR_LIGHT_ADDRESS_RE = re.compile(STAIR_LIGHT_ADDRESS_PATTERN)
_LOCK_ID_RE = re.compile(LOCK_ID_PATTERN)
_BASE_SERVICES_MARKER = "__services_registered"
_GUI_REQUIRED_SERVICES_MARKER = "__gui_required_services_registered"
_GUI_REQUIRED_SERVICES_LISTENER_MARKER = "__gui_required_services_listener"
_DELETE_SERVICE_NAMES = (
    SERVICE_DELETE_LATEST_VIDEO_MESSAGE,
    SERVICE_DELETE_LATEST_TEXT_MEMO,
    SERVICE_DELETE_LATEST_VOICE_MEMO,
)
type _ServiceHandler = Callable[[ServiceCall], Awaitable[None]]
type _EntrySupport = Callable[[Any], bool]


def _boolean_service_value(value: Any) -> bool:
    """Validate service booleans without relying on HA-private helper names."""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "enable", "enabled"}:
            return True
        if lowered in {"0", "false", "no", "off", "disable", "disabled"}:
            return False
    raise vol.Invalid("expected boolean")


def _entry_for_call(hass: HomeAssistant, call: ServiceCall):
    entry_id = call.data.get(_ATTR_ENTRY_ID)
    entries = hass.config_entries.async_entries(DOMAIN)
    if entry_id:
        for entry in entries:
            if entry.entry_id == entry_id:
                return entry
        raise service_validation_error("unknown_entry")
    if len(entries) != 1:
        raise service_validation_error("entry_id_required")
    return entries[0]


def _stair_light_address(value: str) -> str:
    """Validate service-level OpenWebNet stair-light address input."""

    address = cv.string(value).strip()
    if not _STAIR_LIGHT_ADDRESS_RE.fullmatch(address):
        raise vol.Invalid("invalid staircase light address")
    return address


def _lock_id(value: str) -> str:
    """Validate service-level C300X lock id input."""

    lock_id = cv.string(value).strip()
    if not _LOCK_ID_RE.fullmatch(lock_id):
        raise vol.Invalid("invalid lock id")
    return lock_id


def _ensure_maintenance_action(entry, action: str) -> None:
    """Reject maintenance services unless the agent advertises and authorizes them."""

    capabilities = getattr(entry.runtime_data, "capabilities", {})
    if not maintenance_action_is_supported(
        capabilities,
        action,
        entry_config_value(entry, CONF_MAINTENANCE_TOKEN, ""),
    ):
        raise service_validation_error("maintenance_action_not_supported")


async def _async_ensure_gui_function_patch(entry) -> None:
    """Reject GUI-coupled actions unless the full C300X GUI patch is active."""

    if entry_gui_function_patch_active(entry):
        return
    try:
        await async_refresh_qml_patch_status(entry)
    except Exception as err:
        raise service_validation_error("agent_command_failed") from err
    if not entry_gui_function_patch_active(entry):
        raise service_validation_error("gui_function_patch_required")


async def _raise_agent_command_failed(awaitable: Awaitable[Any]) -> None:
    """Run an agent command and translate failures into HA service errors."""

    try:
        await awaitable
    except Exception as err:
        raise service_validation_error("agent_command_failed") from err


async def _latest_video_message_id_for_entry(entry: Any) -> str:
    """Return the newest stored video-message id, refreshing once if needed."""

    messages = getattr(entry.runtime_data, "answering_machine_messages", {})
    message_id = latest_video_message_id(messages) if isinstance(messages, dict) else None
    if message_id is not None:
        return message_id
    try:
        messages = await entry.runtime_data.api.async_answering_machine_messages()
    except Exception as err:
        raise service_validation_error("agent_command_failed") from err
    entry.runtime_data.answering_machine_messages = messages
    entry.runtime_data.answering_machine_messages_updated_at = datetime.now(UTC)
    message_id = latest_video_message_id(messages)
    if message_id is None:
        raise service_validation_error("video_message_not_available")
    return message_id


async def _latest_memo_id_for_entry(entry: Any, kind: str) -> str:
    """Return the newest memo id of one kind, refreshing once if needed."""

    memos = getattr(entry.runtime_data, "memos", {})
    memo_id = latest_memo_id(memos, kind) if isinstance(memos, dict) else None
    if memo_id is not None:
        return memo_id
    try:
        memos = await entry.runtime_data.api.async_memos()
    except Exception as err:
        raise service_validation_error("agent_command_failed") from err
    entry.runtime_data.memos = memos
    entry.runtime_data.memos_updated_at = datetime.now(UTC)
    memo_id = latest_memo_id(memos, kind)
    if memo_id is None:
        raise service_validation_error(f"{kind}_memo_not_available")
    return memo_id


async def _latest_voice_memo_audio_id_for_entry(entry: Any) -> str:
    """Return the newest playable voice memo id, refreshing once if needed."""

    memos = getattr(entry.runtime_data, "memos", {})
    memo_id = latest_voice_memo_audio_id(memos) if isinstance(memos, dict) else None
    if memo_id is not None:
        return memo_id
    try:
        memos = await entry.runtime_data.api.async_memos()
    except Exception as err:
        raise service_validation_error("agent_command_failed") from err
    entry.runtime_data.memos = memos
    entry.runtime_data.memos_updated_at = datetime.now(UTC)
    memo_id = latest_voice_memo_audio_id(memos)
    if memo_id is None:
        raise service_validation_error("voice_memo_not_available")
    return memo_id


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register domain services."""

    domain_data = hass.data.setdefault(DOMAIN, {})

    async def _handle_run_action(call: ServiceCall) -> None:
        entry = _entry_for_call(hass, call)
        try:
            await async_execute_action(hass, entry, call.data[_ATTR_ACTION_ID])
        except ActionValidationError as err:
            raise service_validation_error("invalid_action_id") from err
        except KeyError as err:
            raise service_validation_error(
                "unknown_action", {"action_id": str(err.args[0])}
            ) from err

    async def _handle_alarm_command(call: ServiceCall) -> None:
        entry = _entry_for_call(hass, call)
        try:
            await async_execute_alarm_command(
                hass,
                entry,
                call.data[_ATTR_COMMAND],
                call.data.get(_ATTR_CODE),
                force=bool(call.data.get(_ATTR_FORCE, False)),
            )
        except ActionValidationError as err:
            raise service_validation_error("invalid_alarm_command") from err
        except ValueError as err:
            raise service_validation_error("alarm_not_configured") from err

    async def _handle_stair_light(call: ServiceCall) -> None:
        entry = _entry_for_call(hass, call)
        await _raise_agent_command_failed(
            async_trigger_stair_light(hass, entry, call.data.get(_ATTR_ADDRESS))
        )

    async def _handle_unlock_door(call: ServiceCall) -> None:
        entry = _entry_for_call(hass, call)
        await _raise_agent_command_failed(
            async_unlock_door(hass, entry, call.data.get(_ATTR_LOCK_ID, "default"))
        )

    async def _handle_reboot(call: ServiceCall) -> None:
        entry = _entry_for_call(hass, call)
        _ensure_maintenance_action(entry, "reboot")
        await _raise_agent_command_failed(entry.runtime_data.api.async_reboot())

    async def _handle_reload_gui(call: ServiceCall) -> None:
        entry = _entry_for_call(hass, call)
        _ensure_maintenance_action(entry, "gui_reload")
        await _raise_agent_command_failed(entry.runtime_data.api.async_reload_gui())

    async def _handle_play_latest_video_message(call: ServiceCall) -> None:
        entry = _entry_for_call(hass, call)
        message_id = await _latest_video_message_id_for_entry(entry)
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_PLAY_MEDIA,
            {
                ATTR_ENTITY_ID: call.data[_ATTR_MEDIA_PLAYER_ENTITY_ID],
                "media_content_id": video_message_media_source_id(
                    entry.entry_id,
                    message_id,
                ),
                "media_content_type": MediaType.VIDEO,
            },
            blocking=True,
        )

    async def _handle_play_latest_voice_memo(call: ServiceCall) -> None:
        entry = _entry_for_call(hass, call)
        memo_id = await _latest_voice_memo_audio_id_for_entry(entry)
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_PLAY_MEDIA,
            {
                ATTR_ENTITY_ID: call.data[_ATTR_MEDIA_PLAYER_ENTITY_ID],
                "media_content_id": voice_memo_media_source_id(
                    entry.entry_id,
                    memo_id,
                ),
                "media_content_type": getattr(MediaType, "MUSIC", "music"),
            },
            blocking=True,
        )

    async def _handle_delete_latest_video_message(call: ServiceCall) -> None:
        entry = _entry_for_call(hass, call)
        await _async_ensure_gui_function_patch(entry)
        message_id = await _latest_video_message_id_for_entry(entry)
        await _raise_agent_command_failed(
            entry.runtime_data.api.async_delete_answering_machine_message(message_id)
        )
        try:
            messages = await entry.runtime_data.api.async_answering_machine_messages()
        except Exception as err:
            raise service_validation_error("agent_command_failed") from err
        entry.runtime_data.answering_machine_messages = messages
        entry.runtime_data.answering_machine_messages_updated_at = datetime.now(UTC)
        async_dispatcher_send(hass, SIGNAL_VIDEO_MESSAGES_CHANGED, entry.entry_id)
        await async_refresh_agent_diagnostics(hass, entry)

    async def _delete_latest_memo(call: ServiceCall, kind: str) -> None:
        entry = _entry_for_call(hass, call)
        await _async_ensure_gui_function_patch(entry)
        memo_id = await _latest_memo_id_for_entry(entry, kind)
        await _raise_agent_command_failed(entry.runtime_data.api.async_delete_memo(memo_id))
        try:
            memos = await entry.runtime_data.api.async_memos()
        except Exception as err:
            raise service_validation_error("agent_command_failed") from err
        entry.runtime_data.memos = memos
        entry.runtime_data.memos_updated_at = datetime.now(UTC)
        async_dispatcher_send(hass, SIGNAL_MEMOS_CHANGED, entry.entry_id)
        await async_refresh_agent_diagnostics(hass, entry)

    async def _handle_delete_latest_text_memo(call: ServiceCall) -> None:
        await _delete_latest_memo(call, "text")

    async def _handle_delete_latest_voice_memo(call: ServiceCall) -> None:
        await _delete_latest_memo(call, "voice")

    delete_handlers = {
        SERVICE_DELETE_LATEST_VIDEO_MESSAGE: _handle_delete_latest_video_message,
        SERVICE_DELETE_LATEST_TEXT_MEMO: _handle_delete_latest_text_memo,
        SERVICE_DELETE_LATEST_VOICE_MEMO: _handle_delete_latest_voice_memo,
    }

    if domain_data.get(_BASE_SERVICES_MARKER):
        _sync_gui_required_services(hass, delete_handlers)
        _ensure_gui_required_services_listener(hass, delete_handlers)
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_RUN_ACTION,
        _handle_run_action,
        schema=vol.Schema(
            {
                vol.Optional(_ATTR_ENTRY_ID): cv.string,
                vol.Required(_ATTR_ACTION_ID): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ALARM_COMMAND,
        _handle_alarm_command,
        schema=vol.Schema(
            {
                vol.Optional(_ATTR_ENTRY_ID): cv.string,
                vol.Required(_ATTR_COMMAND): cv.string,
                vol.Optional(_ATTR_CODE): cv.string,
                vol.Optional(_ATTR_FORCE, default=False): _boolean_service_value,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STAIR_LIGHT,
        _handle_stair_light,
        schema=vol.Schema(
            {
                vol.Optional(_ATTR_ENTRY_ID): cv.string,
                vol.Optional(_ATTR_ADDRESS): _stair_light_address,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UNLOCK_DOOR,
        _handle_unlock_door,
        schema=vol.Schema(
            {
                vol.Optional(_ATTR_ENTRY_ID): cv.string,
                vol.Optional(_ATTR_LOCK_ID, default="default"): _lock_id,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REBOOT,
        _handle_reboot,
        schema=vol.Schema({vol.Optional(_ATTR_ENTRY_ID): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RELOAD_GUI,
        _handle_reload_gui,
        schema=vol.Schema({vol.Optional(_ATTR_ENTRY_ID): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PLAY_LATEST_VIDEO_MESSAGE,
        _handle_play_latest_video_message,
        schema=vol.Schema(
            {
                vol.Optional(_ATTR_ENTRY_ID): cv.string,
                vol.Required(_ATTR_MEDIA_PLAYER_ENTITY_ID): cv.entity_id,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PLAY_LATEST_VOICE_MEMO,
        _handle_play_latest_voice_memo,
        schema=vol.Schema(
            {
                vol.Optional(_ATTR_ENTRY_ID): cv.string,
                vol.Required(_ATTR_MEDIA_PLAYER_ENTITY_ID): cv.entity_id,
            }
        ),
    )
    domain_data[_BASE_SERVICES_MARKER] = True
    _sync_gui_required_services(hass, delete_handlers)
    _ensure_gui_required_services_listener(hass, delete_handlers)


def _ensure_gui_required_services_listener(
    hass: HomeAssistant,
    handlers: dict[str, _ServiceHandler],
) -> None:
    """Refresh GUI-coupled service registration when the patch status changes."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_GUI_REQUIRED_SERVICES_LISTENER_MARKER):
        return

    def _handle_qml_patch_changed(_entry_id: str) -> None:
        _sync_gui_required_services(hass, handlers)

    domain_data[_GUI_REQUIRED_SERVICES_LISTENER_MARKER] = async_dispatcher_connect(
        hass,
        SIGNAL_QML_PATCH_CHANGED,
        _handle_qml_patch_changed,
    )


def _sync_gui_required_services(
    hass: HomeAssistant,
    handlers: dict[str, _ServiceHandler],
) -> None:
    """Register or remove services that require patched C300X GUI behavior."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    registered = domain_data.setdefault(_GUI_REQUIRED_SERVICES_MARKER, set())
    if not isinstance(registered, set):
        registered = set()
        domain_data[_GUI_REQUIRED_SERVICES_MARKER] = registered

    supports: dict[str, _EntrySupport] = {
        SERVICE_DELETE_LATEST_VIDEO_MESSAGE: _entry_supports_video_message_delete,
        SERVICE_DELETE_LATEST_TEXT_MEMO: _entry_supports_memo_delete,
        SERVICE_DELETE_LATEST_VOICE_MEMO: _entry_supports_memo_delete,
    }
    for service_name in _DELETE_SERVICE_NAMES:
        should_register = _any_entry_supports(hass, supports[service_name])
        is_registered = service_name in registered
        if should_register and not is_registered:
            hass.services.async_register(
                DOMAIN,
                service_name,
                handlers[service_name],
                schema=vol.Schema({vol.Optional(_ATTR_ENTRY_ID): cv.string}),
            )
            registered.add(service_name)
        elif not should_register and is_registered:
            hass.services.async_remove(DOMAIN, service_name)
            registered.remove(service_name)


def _any_entry_supports(hass: HomeAssistant, support: _EntrySupport) -> bool:
    config_entries = getattr(hass, "config_entries", None)
    if config_entries is None:
        return False
    return any(support(entry) for entry in config_entries.async_entries(DOMAIN))


def _entry_supports_video_message_delete(entry: Any) -> bool:
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None:
        return False
    return (
        entry_device_ui_enabled(entry)
        and entry_gui_function_patch_active(entry)
        and answering_machine_message_delete_supported(runtime_data.capabilities)
    )


def _entry_supports_memo_delete(entry: Any) -> bool:
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None:
        return False
    return (
        entry_device_ui_enabled(entry)
        and entry_gui_function_patch_active(entry)
        and memo_delete_supported(runtime_data.capabilities)
    )
