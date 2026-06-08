"""Home Assistant services for local testing and automation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
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
from .api import C300XAgentApiResponseError, normalize_text_memo_text
from .capabilities import (
    answering_machine_message_delete_supported,
    capability_is_supported,
    entry_device_ui_enabled,
    entry_gui_function_patch_active,
    maintenance_action_is_supported,
    memo_delete_supported,
    memo_text_write_supported,
)
from .const import (
    CONF_MAINTENANCE_TOKEN,
    DOMAIN,
    MAX_HOME_CALL_DURATION_SECONDS,
    SERVICE_ACTIVATE_DOORBELL_VIDEO,
    SERVICE_ALARM_COMMAND,
    SERVICE_ANSWER_DOORBELL_CALL,
    SERVICE_CAPTURE_DOORBELL_CALL,
    SERVICE_DELETE_LATEST_TEXT_MEMO,
    SERVICE_DELETE_LATEST_VIDEO_MESSAGE,
    SERVICE_DELETE_LATEST_VOICE_MEMO,
    SERVICE_HANGUP_DOORBELL_CALL,
    SERVICE_PLAY_LATEST_VIDEO_MESSAGE,
    SERVICE_PLAY_LATEST_VOICE_MEMO,
    SERVICE_REBOOT,
    SERVICE_RELOAD_GUI,
    SERVICE_RUN_ACTION,
    SERVICE_RUN_DEVICE_ACTIVATION,
    SERVICE_STAIR_LIGHT,
    SERVICE_START_HOME_CALL,
    SERVICE_STOP_DOORBELL_VIDEO,
    SERVICE_STOP_HOME_CALL,
    SERVICE_UNLOCK_DOOR,
    SERVICE_WRITE_TEXT_MEMO,
    SIGNAL_MEMOS_CHANGED,
    SIGNAL_QML_PATCH_CHANGED,
    SIGNAL_VIDEO_MESSAGES_CHANGED,
)
from .entity import entry_config_value, entry_video_enabled
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
from .message_refresh import async_answering_machine_messages, async_memos
from .qml_patch import async_refresh_qml_patch_status
from .ring_capture import async_capture_doorbell_ring_call
from .validation_patterns import ACTIVATION_ID_RE, LOCK_ID_RE, STAIR_LIGHT_ADDRESS_RE
from .video_messages import latest_video_message_id, video_message_media_source_id

_ATTR_ACTION_ID = "action_id"
_ATTR_ACTIVATION_ID = "activation_id"
_ATTR_ADDRESS = "address"
_ATTR_AUDIO = "audio"
_ATTR_CODE = "code"
_ATTR_COMMAND = "command"
_ATTR_ENTRY_ID = "entry_id"
_ATTR_FORCE = "force"
_ATTR_DURATION_SECONDS = "duration_seconds"
_ATTR_LOCK_ID = "lock_id"
_ATTR_MEDIA_PLAYER_ENTITY_ID = "media_player_entity_id"
_ATTR_OUTPUT_PATH = "output_path"
_ATTR_INCLUDE_AUDIO = "include_audio"
_ATTR_ANNOUNCEMENT_PATH = "announcement_path"
_ATTR_READ = "read"
_ATTR_TEXT = "text"
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
    if not STAIR_LIGHT_ADDRESS_RE.fullmatch(address):
        raise vol.Invalid("invalid staircase light address")
    return address


def _lock_id(value: str) -> str:
    """Validate service-level C300X lock id input."""

    lock_id = cv.string(value).strip()
    if not LOCK_ID_RE.fullmatch(lock_id):
        raise vol.Invalid("invalid lock id")
    return lock_id


def _activation_id(value: str) -> str:
    """Validate service-level C300X activation id input."""

    activation_id = cv.string(value).strip()
    if not ACTIVATION_ID_RE.fullmatch(activation_id):
        raise vol.Invalid("invalid activation id")
    return activation_id


def _home_call_duration_seconds(value: Any) -> int:
    """Validate optional home-call duration."""

    try:
        duration_seconds = int(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("invalid duration seconds") from err
    if duration_seconds < 0 or duration_seconds > MAX_HOME_CALL_DURATION_SECONDS:
        raise vol.Invalid("invalid duration seconds")
    return duration_seconds


def _capture_duration_seconds(value: Any) -> int:
    """Validate service-level capture duration."""

    try:
        duration_seconds = int(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("invalid duration seconds") from err
    if duration_seconds < 1 or duration_seconds > 15:
        raise vol.Invalid("invalid duration seconds")
    return duration_seconds


def _ensure_maintenance_action(entry, action: str) -> None:
    """Reject maintenance services unless the agent advertises and authorizes them."""

    capabilities = getattr(entry.runtime_data, "capabilities", {})
    if not maintenance_action_is_supported(
        capabilities,
        action,
        entry_config_value(entry, CONF_MAINTENANCE_TOKEN, ""),
    ):
        raise service_validation_error("maintenance_action_not_supported")


def _ensure_doorbell_video_supported(entry: Any) -> None:
    """Reject video activation unless HA and the agent expose doorbell video."""

    runtime_data = getattr(entry, "runtime_data", None)
    capabilities = getattr(runtime_data, "capabilities", {})
    if not (
        entry_video_enabled(entry)
        and capability_is_supported(capabilities, "doorbell_video")
    ):
        raise service_validation_error("doorbell_video_not_available")


def _ensure_doorbell_call_supported(entry: Any) -> None:
    """Reject ring-call control unless HA and the agent expose it."""

    runtime_data = getattr(entry, "runtime_data", None)
    capabilities = getattr(runtime_data, "capabilities", {})
    if not (
        entry_video_enabled(entry)
        and capability_is_supported(capabilities, "doorbell_call")
    ):
        raise service_validation_error("doorbell_video_not_available")


def _ensure_home_call_supported(entry: Any) -> None:
    """Reject in-house home-call actions unless HA and the agent expose them."""

    runtime_data = getattr(entry, "runtime_data", None)
    capabilities = getattr(runtime_data, "capabilities", {})
    if not (
        entry_video_enabled(entry)
        and capability_is_supported(capabilities, "home_call")
    ):
        raise service_validation_error("home_call_not_available")


def _ensure_text_memo_write_supported(entry: Any) -> None:
    """Reject text-memo creation unless the agent exposes it."""

    runtime_data = getattr(entry, "runtime_data", None)
    capabilities = getattr(runtime_data, "capabilities", {})
    if not memo_text_write_supported(capabilities):
        raise service_validation_error("text_memo_write_not_supported")


def _text_memo_text(value: Any) -> str:
    """Validate service-level text memo content."""

    try:
        return normalize_text_memo_text(value)
    except C300XAgentApiResponseError as err:
        raise vol.Invalid(str(err)) from err


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

    return await _latest_item_id_for_entry(
        entry,
        cache_attr="answering_machine_messages",
        refresh=lambda: async_answering_machine_messages(entry, force_refresh=True),
        latest=latest_video_message_id,
        unavailable_error="video_message_not_available",
    )


async def _latest_memo_id_for_entry(entry: Any, kind: str) -> str:
    """Return the newest memo id of one kind, refreshing once if needed."""

    return await _latest_item_id_for_entry(
        entry,
        cache_attr="memos",
        refresh=lambda: async_memos(entry, force_refresh=True),
        latest=lambda memos: latest_memo_id(memos, kind),
        unavailable_error=f"{kind}_memo_not_available",
    )


async def _latest_voice_memo_audio_id_for_entry(entry: Any) -> str:
    """Return the newest playable voice memo id, refreshing once if needed."""

    return await _latest_item_id_for_entry(
        entry,
        cache_attr="memos",
        refresh=lambda: async_memos(entry, force_refresh=True),
        latest=latest_voice_memo_audio_id,
        unavailable_error="voice_memo_not_available",
    )


async def _latest_item_id_for_entry(
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


async def _async_refresh_after_message_mutation(
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


class _C300XServiceHandlers:
    """Bound service handlers for one Home Assistant instance."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    @property
    def delete_handlers(self) -> dict[str, _ServiceHandler]:
        """Return GUI-patch-gated delete handlers."""

        return {
            SERVICE_DELETE_LATEST_VIDEO_MESSAGE: self.async_delete_latest_video_message,
            SERVICE_DELETE_LATEST_TEXT_MEMO: self.async_delete_latest_text_memo,
            SERVICE_DELETE_LATEST_VOICE_MEMO: self.async_delete_latest_voice_memo,
        }

    async def async_run_action(self, call: ServiceCall) -> None:
        """Run one allowlisted Home Assistant action."""

        entry = _entry_for_call(self._hass, call)
        try:
            await async_execute_action(
                self._hass,
                entry,
                call.data[_ATTR_ACTION_ID],
            )
        except ActionValidationError as err:
            raise service_validation_error("invalid_action_id") from err
        except KeyError as err:
            raise service_validation_error(
                "unknown_action",
                {"action_id": str(err.args[0])},
            ) from err

    async def async_run_device_activation(self, call: ServiceCall) -> None:
        """Run one configured C300X device activation."""

        entry = _entry_for_call(self._hass, call)
        await _raise_agent_command_failed(
            entry.runtime_data.api.async_run_device_activation(
                call.data[_ATTR_ACTIVATION_ID]
            )
        )

    async def async_alarm_command(self, call: ServiceCall) -> None:
        """Forward one alarm command to the configured HA alarm entity."""

        entry = _entry_for_call(self._hass, call)
        try:
            await async_execute_alarm_command(
                self._hass,
                entry,
                call.data[_ATTR_COMMAND],
                call.data.get(_ATTR_CODE),
                force=bool(call.data.get(_ATTR_FORCE, False)),
            )
        except ActionValidationError as err:
            raise service_validation_error("invalid_alarm_command") from err
        except ValueError as err:
            raise service_validation_error("alarm_not_configured") from err

    async def async_stair_light(self, call: ServiceCall) -> None:
        """Trigger the configured stair-light command."""

        entry = _entry_for_call(self._hass, call)
        await _raise_agent_command_failed(
            async_trigger_stair_light(self._hass, entry, call.data.get(_ATTR_ADDRESS))
        )

    async def async_unlock_door(self, call: ServiceCall) -> None:
        """Trigger the configured door-unlock command."""

        entry = _entry_for_call(self._hass, call)
        await _raise_agent_command_failed(
            async_unlock_door(self._hass, entry, call.data.get(_ATTR_LOCK_ID, "default"))
        )

    async def async_activate_doorbell_video(self, call: ServiceCall) -> None:
        """Activate or renew the C300X doorbell video session."""

        entry = _entry_for_call(self._hass, call)
        _ensure_doorbell_video_supported(entry)
        await _raise_agent_command_failed(
            entry.runtime_data.api.async_activate_doorbell_video(
                audio=bool(call.data.get(_ATTR_AUDIO, True))
            )
        )

    async def async_stop_doorbell_video(self, call: ServiceCall) -> None:
        """Stop the active C300X doorbell video session."""

        entry = _entry_for_call(self._hass, call)
        _ensure_doorbell_video_supported(entry)
        await _raise_agent_command_failed(
            entry.runtime_data.api.async_stop_doorbell_video()
        )

    async def async_answer_doorbell_call(self, call: ServiceCall) -> None:
        """Answer the active C300X doorbell ring call through the agent."""

        entry = _entry_for_call(self._hass, call)
        _ensure_doorbell_call_supported(entry)
        await _raise_agent_command_failed(
            entry.runtime_data.api.async_answer_doorbell_call(
                audio=bool(call.data.get(_ATTR_AUDIO, True))
            )
        )

    async def async_hangup_doorbell_call(self, call: ServiceCall) -> None:
        """Hang up the active C300X doorbell ring call through the agent."""

        entry = _entry_for_call(self._hass, call)
        _ensure_doorbell_call_supported(entry)
        await _raise_agent_command_failed(
            entry.runtime_data.api.async_hangup_doorbell_call()
        )

    async def async_capture_doorbell_call(self, call: ServiceCall) -> None:
        """Capture a short C300X doorbell ring-call clip on Home Assistant."""

        entry = _entry_for_call(self._hass, call)
        _ensure_doorbell_video_supported(entry)
        announcement_path = call.data.get(_ATTR_ANNOUNCEMENT_PATH)
        if announcement_path:
            await _raise_agent_command_failed(
                entry.runtime_data.api.async_answer_doorbell_call(audio=True)
            )
        try:
            await async_capture_doorbell_ring_call(
                self._hass,
                entry,
                output_path=call.data.get(_ATTR_OUTPUT_PATH),
                duration_seconds=call.data.get(_ATTR_DURATION_SECONDS, 5),
                include_audio=bool(call.data.get(_ATTR_INCLUDE_AUDIO, True)),
                announcement_path=announcement_path,
            )
        finally:
            await _raise_agent_command_failed(
                entry.runtime_data.api.async_hangup_doorbell_call()
            )

    async def async_start_home_call(self, call: ServiceCall) -> None:
        """Start an in-house call to the C300X."""

        entry = _entry_for_call(self._hass, call)
        _ensure_home_call_supported(entry)
        await _raise_agent_command_failed(
            entry.runtime_data.api.async_start_home_call(
                duration_seconds=call.data.get(_ATTR_DURATION_SECONDS)
            )
        )

    async def async_stop_home_call(self, call: ServiceCall) -> None:
        """Stop the in-house call to the C300X."""

        entry = _entry_for_call(self._hass, call)
        _ensure_home_call_supported(entry)
        await _raise_agent_command_failed(
            entry.runtime_data.api.async_stop_home_call()
        )

    async def async_reboot(self, call: ServiceCall) -> None:
        """Reboot the C300X through the maintenance API."""

        entry = _entry_for_call(self._hass, call)
        _ensure_maintenance_action(entry, "reboot")
        await _raise_agent_command_failed(entry.runtime_data.api.async_reboot())

    async def async_reload_gui(self, call: ServiceCall) -> None:
        """Reload the device GUI through the maintenance API."""

        entry = _entry_for_call(self._hass, call)
        _ensure_maintenance_action(entry, "gui_reload")
        await _raise_agent_command_failed(entry.runtime_data.api.async_reload_gui())

    async def async_play_latest_video_message(self, call: ServiceCall) -> None:
        """Play the latest video message on a media player."""

        entry = _entry_for_call(self._hass, call)
        message_id = await _latest_video_message_id_for_entry(entry)
        await self._async_play_media(
            call,
            media_content_id=video_message_media_source_id(entry.entry_id, message_id),
            media_content_type=MediaType.VIDEO,
        )

    async def async_play_latest_voice_memo(self, call: ServiceCall) -> None:
        """Play the latest voice memo on a media player."""

        entry = _entry_for_call(self._hass, call)
        memo_id = await _latest_voice_memo_audio_id_for_entry(entry)
        await self._async_play_media(
            call,
            media_content_id=voice_memo_media_source_id(entry.entry_id, memo_id),
            media_content_type=getattr(MediaType, "MUSIC", "music"),
        )

    async def async_write_text_memo(self, call: ServiceCall) -> None:
        """Create a local text memo on the C300X."""

        entry = _entry_for_call(self._hass, call)
        _ensure_text_memo_write_supported(entry)
        await _raise_agent_command_failed(
            entry.runtime_data.api.async_create_text_memo(
                call.data[_ATTR_TEXT],
                read=bool(call.data.get(_ATTR_READ, False)),
            )
        )
        await _async_refresh_after_message_mutation(
            self._hass,
            entry,
            refresh=lambda: async_memos(entry, force_refresh=True),
            signal=SIGNAL_MEMOS_CHANGED,
        )

    async def async_delete_latest_video_message(self, call: ServiceCall) -> None:
        """Delete the newest stored video message."""

        entry = _entry_for_call(self._hass, call)
        await _async_ensure_gui_function_patch(entry)
        message_id = await _latest_video_message_id_for_entry(entry)
        await _raise_agent_command_failed(
            entry.runtime_data.api.async_delete_answering_machine_message(message_id)
        )
        await _async_refresh_after_message_mutation(
            self._hass,
            entry,
            refresh=lambda: async_answering_machine_messages(
                entry,
                force_refresh=True,
            ),
            signal=SIGNAL_VIDEO_MESSAGES_CHANGED,
        )

    async def async_delete_latest_text_memo(self, call: ServiceCall) -> None:
        """Delete the newest text memo."""

        await self._async_delete_latest_memo(call, "text")

    async def async_delete_latest_voice_memo(self, call: ServiceCall) -> None:
        """Delete the newest voice memo."""

        await self._async_delete_latest_memo(call, "voice")

    async def _async_delete_latest_memo(self, call: ServiceCall, kind: str) -> None:
        entry = _entry_for_call(self._hass, call)
        await _async_ensure_gui_function_patch(entry)
        memo_id = await _latest_memo_id_for_entry(entry, kind)
        await _raise_agent_command_failed(entry.runtime_data.api.async_delete_memo(memo_id))
        await _async_refresh_after_message_mutation(
            self._hass,
            entry,
            refresh=lambda: async_memos(entry, force_refresh=True),
            signal=SIGNAL_MEMOS_CHANGED,
        )

    async def _async_play_media(
        self,
        call: ServiceCall,
        *,
        media_content_id: str,
        media_content_type: str,
    ) -> None:
        await self._hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_PLAY_MEDIA,
            {
                ATTR_ENTITY_ID: call.data[_ATTR_MEDIA_PLAYER_ENTITY_ID],
                "media_content_id": media_content_id,
                "media_content_type": media_content_type,
            },
            blocking=True,
        )


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register domain services."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    handlers = _C300XServiceHandlers(hass)
    delete_handlers = handlers.delete_handlers

    if domain_data.get(_BASE_SERVICES_MARKER):
        _sync_gui_required_services(hass, delete_handlers)
        _ensure_gui_required_services_listener(hass, delete_handlers)
        return

    _register_base_services(hass, handlers)
    domain_data[_BASE_SERVICES_MARKER] = True
    _sync_gui_required_services(hass, delete_handlers)
    _ensure_gui_required_services_listener(hass, delete_handlers)


def _register_base_services(
    hass: HomeAssistant,
    handlers: _C300XServiceHandlers,
) -> None:
    """Register services that are always part of the integration."""

    for service_name, handler, schema in (
        (
            SERVICE_RUN_ACTION,
            handlers.async_run_action,
            vol.Schema(
                {
                    vol.Optional(_ATTR_ENTRY_ID): cv.string,
                    vol.Required(_ATTR_ACTION_ID): cv.string,
                }
            ),
        ),
        (
            SERVICE_RUN_DEVICE_ACTIVATION,
            handlers.async_run_device_activation,
            vol.Schema(
                {
                    vol.Optional(_ATTR_ENTRY_ID): cv.string,
                    vol.Required(_ATTR_ACTIVATION_ID): _activation_id,
                }
            ),
        ),
        (
            SERVICE_ALARM_COMMAND,
            handlers.async_alarm_command,
            vol.Schema(
                {
                    vol.Optional(_ATTR_ENTRY_ID): cv.string,
                    vol.Required(_ATTR_COMMAND): cv.string,
                    vol.Optional(_ATTR_CODE): cv.string,
                    vol.Optional(_ATTR_FORCE, default=False): _boolean_service_value,
                }
            ),
        ),
        (
            SERVICE_STAIR_LIGHT,
            handlers.async_stair_light,
            vol.Schema(
                {
                    vol.Optional(_ATTR_ENTRY_ID): cv.string,
                    vol.Optional(_ATTR_ADDRESS): _stair_light_address,
                }
            ),
        ),
        (
            SERVICE_UNLOCK_DOOR,
            handlers.async_unlock_door,
            vol.Schema(
                {
                    vol.Optional(_ATTR_ENTRY_ID): cv.string,
                    vol.Optional(_ATTR_LOCK_ID, default="default"): _lock_id,
                }
            ),
        ),
        (
            SERVICE_ACTIVATE_DOORBELL_VIDEO,
            handlers.async_activate_doorbell_video,
            vol.Schema(
                {
                    vol.Optional(_ATTR_ENTRY_ID): cv.string,
                    vol.Optional(_ATTR_AUDIO, default=True): _boolean_service_value,
                }
            ),
        ),
        (
            SERVICE_STOP_DOORBELL_VIDEO,
            handlers.async_stop_doorbell_video,
            vol.Schema({vol.Optional(_ATTR_ENTRY_ID): cv.string}),
        ),
        (
            SERVICE_ANSWER_DOORBELL_CALL,
            handlers.async_answer_doorbell_call,
            vol.Schema(
                {
                    vol.Optional(_ATTR_ENTRY_ID): cv.string,
                    vol.Optional(_ATTR_AUDIO, default=True): _boolean_service_value,
                }
            ),
        ),
        (
            SERVICE_HANGUP_DOORBELL_CALL,
            handlers.async_hangup_doorbell_call,
            vol.Schema({vol.Optional(_ATTR_ENTRY_ID): cv.string}),
        ),
        (
            SERVICE_CAPTURE_DOORBELL_CALL,
            handlers.async_capture_doorbell_call,
            vol.Schema(
                {
                    vol.Optional(_ATTR_ENTRY_ID): cv.string,
                    vol.Optional(_ATTR_OUTPUT_PATH): cv.string,
                    vol.Optional(_ATTR_DURATION_SECONDS, default=5): _capture_duration_seconds,
                    vol.Optional(_ATTR_INCLUDE_AUDIO, default=True): _boolean_service_value,
                    vol.Optional(_ATTR_ANNOUNCEMENT_PATH): cv.string,
                }
            ),
        ),
        (
            SERVICE_START_HOME_CALL,
            handlers.async_start_home_call,
            vol.Schema(
                {
                    vol.Optional(_ATTR_ENTRY_ID): cv.string,
                    vol.Optional(_ATTR_DURATION_SECONDS): _home_call_duration_seconds,
                }
            ),
        ),
        (
            SERVICE_STOP_HOME_CALL,
            handlers.async_stop_home_call,
            vol.Schema({vol.Optional(_ATTR_ENTRY_ID): cv.string}),
        ),
        (
            SERVICE_REBOOT,
            handlers.async_reboot,
            vol.Schema({vol.Optional(_ATTR_ENTRY_ID): cv.string}),
        ),
        (
            SERVICE_RELOAD_GUI,
            handlers.async_reload_gui,
            vol.Schema({vol.Optional(_ATTR_ENTRY_ID): cv.string}),
        ),
        (
            SERVICE_PLAY_LATEST_VIDEO_MESSAGE,
            handlers.async_play_latest_video_message,
            _play_media_schema(),
        ),
        (
            SERVICE_PLAY_LATEST_VOICE_MEMO,
            handlers.async_play_latest_voice_memo,
            _play_media_schema(),
        ),
        (
            SERVICE_WRITE_TEXT_MEMO,
            handlers.async_write_text_memo,
            vol.Schema(
                {
                    vol.Optional(_ATTR_ENTRY_ID): cv.string,
                    vol.Required(_ATTR_TEXT): _text_memo_text,
                    vol.Optional(_ATTR_READ, default=False): _boolean_service_value,
                }
            ),
        ),
    ):
        hass.services.async_register(DOMAIN, service_name, handler, schema=schema)


def _play_media_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(_ATTR_ENTRY_ID): cv.string,
            vol.Required(_ATTR_MEDIA_PLAYER_ENTITY_ID): cv.entity_id,
        }
    )


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
