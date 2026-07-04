"""Home Assistant services for local testing and automation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
)

from .capabilities import (
    answering_machine_message_delete_supported,
    entry_device_ui_enabled,
    entry_gui_function_patch_active,
    memo_delete_supported,
)
from .const import (
    DATA_RUNTIME_ENTRIES,
    DOMAIN,
    SERVICE_ACTIVATE_DOORBELL_VIDEO,
    SERVICE_ALARM_COMMAND,
    SERVICE_ANSWER_DOORBELL_CALL,
    SERVICE_CAPTURE_DOORBELL_CALL,
    SERVICE_DELETE_LATEST_TEXT_MEMO,
    SERVICE_DELETE_LATEST_VIDEO_MESSAGE,
    SERVICE_DELETE_LATEST_VOICE_MEMO,
    SERVICE_EVALUATE_RING_ANALYSIS,
    SERVICE_HANGUP_DOORBELL_CALL,
    SERVICE_PLAY_LATEST_VIDEO_MESSAGE,
    SERVICE_PLAY_LATEST_VOICE_MEMO,
    SERVICE_REBOOT,
    SERVICE_RELOAD_GUI,
    SERVICE_RUN_ACTION,
    SERVICE_RUN_DEVICE_ACTIVATION,
    SERVICE_RUN_RING_WYOMING_ANALYSIS,
    SERVICE_STAIR_LIGHT,
    SERVICE_START_HOME_CALL,
    SERVICE_STOP_DOORBELL_VIDEO,
    SERVICE_STOP_HOME_CALL,
    SERVICE_UNLOCK_DOOR,
    SERVICE_WRITE_TEXT_MEMO,
    SIGNAL_QML_PATCH_CHANGED,
)
from .exceptions import service_validation_error
from .service_schema import (
    ATTR_ACTION_ID as _ATTR_ACTION_ID,
)
from .service_schema import (
    ATTR_ACTIVATION_ID as _ATTR_ACTIVATION_ID,
)
from .service_schema import (
    ATTR_ADDRESS as _ATTR_ADDRESS,
)
from .service_schema import (
    ATTR_ANNOUNCEMENT_PATH as _ATTR_ANNOUNCEMENT_PATH,
)
from .service_schema import (
    ATTR_AUDIO as _ATTR_AUDIO,
)
from .service_schema import (
    ATTR_CAPTURE_PATH as _ATTR_CAPTURE_PATH,
)
from .service_schema import (
    ATTR_CODE as _ATTR_CODE,
)
from .service_schema import (
    ATTR_COMMAND as _ATTR_COMMAND,
)
from .service_schema import (
    ATTR_DECISION_PATH as _ATTR_DECISION_PATH,
)
from .service_schema import (
    ATTR_DURATION_SECONDS as _ATTR_DURATION_SECONDS,
)
from .service_schema import (
    ATTR_ENTRY_ID as _ATTR_ENTRY_ID,
)
from .service_schema import (
    ATTR_EXPECTED_PHRASE as _ATTR_EXPECTED_PHRASE,
)
from .service_schema import (
    ATTR_FORCE as _ATTR_FORCE,
)
from .service_schema import (
    ATTR_INCLUDE_AUDIO as _ATTR_INCLUDE_AUDIO,
)
from .service_schema import (
    ATTR_LANGUAGE as _ATTR_LANGUAGE,
)
from .service_schema import (
    ATTR_LOCK_ID as _ATTR_LOCK_ID,
)
from .service_schema import (
    ATTR_MEDIA_PLAYER_ENTITY_ID as _ATTR_MEDIA_PLAYER_ENTITY_ID,
)
from .service_schema import (
    ATTR_OUTPUT_PATH as _ATTR_OUTPUT_PATH,
)
from .service_schema import (
    ATTR_READ as _ATTR_READ,
)
from .service_schema import (
    ATTR_RESULT_PATH as _ATTR_RESULT_PATH,
)
from .service_schema import (
    ATTR_TEXT as _ATTR_TEXT,
)
from .service_schema import (
    ATTR_UNLOCK_ON_MATCH as _ATTR_UNLOCK_ON_MATCH,
)
from .service_schema import (
    ATTR_WAV_OUTPUT_DIR as _ATTR_WAV_OUTPUT_DIR,
)
from .service_schema import (
    ATTR_WAV_PATH as _ATTR_WAV_PATH,
)
from .service_schema import (
    ATTR_WYOMING_HOST as _ATTR_WYOMING_HOST,
)
from .service_schema import (
    ATTR_WYOMING_PORT as _ATTR_WYOMING_PORT,
)
from .service_schema import (
    activation_id as _activation_id,
)
from .service_schema import (
    boolean_service_value as _boolean_service_value,
)
from .service_schema import (
    capture_duration_seconds as _capture_duration_seconds,
)
from .service_schema import (
    home_call_duration_seconds as _home_call_duration_seconds,
)
from .service_schema import (
    lock_id as _lock_id,
)
from .service_schema import (
    stair_light_address as _stair_light_address,
)
from .service_schema import (
    text_memo_text as _text_memo_text,
)
from .service_schema import (
    wyoming_port as _wyoming_port,
)
from .use_cases.device_actions import DeviceActionsUseCase
from .use_cases.doorbell_video import DoorbellVideoUseCase
from .use_cases.home_call import HomeCallUseCase
from .use_cases.maintenance import MaintenanceUseCase
from .use_cases.memos import MemosUseCase
from .use_cases.messages import MessagesUseCase
from .use_cases.ring_analysis import RingAnalysisUseCase
from .use_cases.ring_call import RingCallUseCase
from .use_cases.ring_capture import RingCaptureUseCase

_BASE_SERVICES_MARKER = "__services_registered"
_GUI_REQUIRED_SERVICES_MARKER = "__gui_required_services_registered"
_GUI_REQUIRED_SERVICES_LISTENER_MARKER = "__gui_required_services_listener"
_DELETE_SERVICE_NAMES = (
    SERVICE_DELETE_LATEST_VIDEO_MESSAGE,
    SERVICE_DELETE_LATEST_TEXT_MEMO,
    SERVICE_DELETE_LATEST_VOICE_MEMO,
)
type _ServiceHandler = Callable[[ServiceCall], Awaitable[None]]
type _ServiceSpec = tuple[str, _ServiceHandler, vol.Schema]
type _EntrySupport = Callable[[Any], bool]


class _EntryRuntimeProxy:
    """Expose stored runtime data for HA ConfigEntry objects without attributes."""

    def __init__(self, entry: Any, runtime_data: Any) -> None:
        self._entry = entry
        self.runtime_data = runtime_data

    def __getattr__(self, name: str) -> Any:
        return getattr(self._entry, name)


def _entry_for_call(hass: HomeAssistant, call: ServiceCall) -> Any:
    entry_id = call.data.get(_ATTR_ENTRY_ID)
    entries = hass.config_entries.async_entries(DOMAIN)
    if entry_id:
        for entry in entries:
            if entry.entry_id == entry_id:
                return _entry_with_runtime_data(hass, entry)
        raise service_validation_error("unknown_entry")
    if len(entries) != 1:
        raise service_validation_error("entry_id_required")
    return _entry_with_runtime_data(hass, entries[0])


def _entry_with_runtime_data(hass: HomeAssistant, entry: Any) -> Any:
    """Return an entry object with runtime_data or fail as a service error."""

    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is not None:
        return entry

    runtime_entries = hass.data.get(DOMAIN, {}).get(DATA_RUNTIME_ENTRIES, {})
    runtime_data = runtime_entries.get(getattr(entry, "entry_id", None))
    if runtime_data is None:
        raise service_validation_error("agent_command_failed")
    return _EntryRuntimeProxy(entry, runtime_data)


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
        await DeviceActionsUseCase(self._hass, entry).run_action(
            call.data[_ATTR_ACTION_ID]
        )

    async def async_run_device_activation(self, call: ServiceCall) -> None:
        """Run one configured C300X device activation."""

        entry = _entry_for_call(self._hass, call)
        await DeviceActionsUseCase(self._hass, entry).run_device_activation(
            call.data[_ATTR_ACTIVATION_ID]
        )

    async def async_alarm_command(self, call: ServiceCall) -> None:
        """Forward one alarm command to the configured HA alarm entity."""

        entry = _entry_for_call(self._hass, call)
        await DeviceActionsUseCase(self._hass, entry).alarm_command(
            call.data[_ATTR_COMMAND],
            call.data.get(_ATTR_CODE),
            force=bool(call.data.get(_ATTR_FORCE, False)),
        )

    async def async_stair_light(self, call: ServiceCall) -> None:
        """Trigger the configured stair-light command."""

        entry = _entry_for_call(self._hass, call)
        await DeviceActionsUseCase(self._hass, entry).stair_light(
            call.data.get(_ATTR_ADDRESS)
        )

    async def async_unlock_door(self, call: ServiceCall) -> None:
        """Trigger the configured door-unlock command."""

        entry = _entry_for_call(self._hass, call)
        await DeviceActionsUseCase(self._hass, entry).unlock(
            call.data.get(_ATTR_LOCK_ID, "default")
        )

    async def async_activate_doorbell_video(self, call: ServiceCall) -> None:
        """Activate or renew the C300X doorbell video session."""

        entry = _entry_for_call(self._hass, call)
        await DoorbellVideoUseCase(entry).activate(
            audio=bool(call.data.get(_ATTR_AUDIO, True))
        )

    async def async_stop_doorbell_video(self, call: ServiceCall) -> None:
        """Stop the active C300X doorbell video session."""

        entry = _entry_for_call(self._hass, call)
        await DoorbellVideoUseCase(entry).stop()

    async def async_answer_doorbell_call(self, call: ServiceCall) -> None:
        """Answer the active C300X doorbell ring call through the agent."""

        entry = _entry_for_call(self._hass, call)
        await RingCallUseCase(entry).answer()

    async def async_hangup_doorbell_call(self, call: ServiceCall) -> None:
        """Hang up the active C300X doorbell ring call through the agent."""

        entry = _entry_for_call(self._hass, call)
        await RingCallUseCase(entry).hangup()

    async def async_capture_doorbell_call(self, call: ServiceCall) -> None:
        """Capture a short C300X doorbell ring-call clip on Home Assistant."""

        entry = _entry_for_call(self._hass, call)
        await RingCaptureUseCase(self._hass, entry).capture(
            output_path=call.data.get(_ATTR_OUTPUT_PATH),
            wav_output_dir=call.data.get(_ATTR_WAV_OUTPUT_DIR),
            duration_seconds=call.data.get(_ATTR_DURATION_SECONDS, 5),
            include_audio=bool(call.data.get(_ATTR_INCLUDE_AUDIO, True)),
            announcement_path=call.data.get(_ATTR_ANNOUNCEMENT_PATH),
        )

    async def async_run_ring_wyoming_analysis(self, call: ServiceCall) -> None:
        """Transcribe the latest C300X ring raw WAV through Wyoming Whisper."""

        await RingAnalysisUseCase(self._hass).transcribe(
            wyoming_host=call.data[_ATTR_WYOMING_HOST],
            wyoming_port=call.data.get(_ATTR_WYOMING_PORT, 10300),
            capture_path=call.data.get(_ATTR_CAPTURE_PATH),
            wav_path=call.data.get(_ATTR_WAV_PATH),
            result_path=call.data.get(_ATTR_RESULT_PATH),
            language=call.data.get(_ATTR_LANGUAGE),
            expected_phrase=call.data.get(_ATTR_EXPECTED_PHRASE),
        )

    async def async_evaluate_ring_analysis(self, call: ServiceCall) -> None:
        """Evaluate a local C300X ring-analysis result and optionally unlock."""

        unlock_on_match = bool(call.data.get(_ATTR_UNLOCK_ON_MATCH, False))
        await RingAnalysisUseCase(self._hass).evaluate(
            result_path=call.data.get(_ATTR_RESULT_PATH),
            decision_path=call.data.get(_ATTR_DECISION_PATH),
            capture_path=call.data.get(_ATTR_CAPTURE_PATH),
            expected_phrase=call.data.get(_ATTR_EXPECTED_PHRASE),
            unlock_on_match=unlock_on_match,
            unlock_entry_provider=lambda: _entry_for_call(self._hass, call),
            lock_id=call.data.get(_ATTR_LOCK_ID, "default"),
        )

    async def async_start_home_call(self, call: ServiceCall) -> None:
        """Start a local Home Call to the C300X."""

        entry = _entry_for_call(self._hass, call)
        await HomeCallUseCase(entry).start(
            duration_seconds=call.data.get(_ATTR_DURATION_SECONDS)
        )

    async def async_stop_home_call(self, call: ServiceCall) -> None:
        """Stop the local Home Call to the C300X."""

        entry = _entry_for_call(self._hass, call)
        await HomeCallUseCase(entry).stop()

    async def async_reboot(self, call: ServiceCall) -> None:
        """Reboot the C300X through the maintenance API."""

        entry = _entry_for_call(self._hass, call)
        await MaintenanceUseCase(entry).reboot()

    async def async_reload_gui(self, call: ServiceCall) -> None:
        """Reload the device GUI through the maintenance API."""

        entry = _entry_for_call(self._hass, call)
        await MaintenanceUseCase(entry).reload_gui()

    async def async_play_latest_video_message(self, call: ServiceCall) -> None:
        """Play the latest video message on a media player."""

        entry = _entry_for_call(self._hass, call)
        await MessagesUseCase(self._hass, entry).play_latest_video_message(
            call.data[_ATTR_MEDIA_PLAYER_ENTITY_ID]
        )

    async def async_play_latest_voice_memo(self, call: ServiceCall) -> None:
        """Play the latest voice memo on a media player."""

        entry = _entry_for_call(self._hass, call)
        await MemosUseCase(self._hass, entry).play_latest_voice_memo(
            call.data[_ATTR_MEDIA_PLAYER_ENTITY_ID]
        )

    async def async_write_text_memo(self, call: ServiceCall) -> None:
        """Create a local text memo on the C300X."""

        entry = _entry_for_call(self._hass, call)
        await MemosUseCase(self._hass, entry).write_text_memo(
            call.data[_ATTR_TEXT],
            read=bool(call.data.get(_ATTR_READ, False)),
        )

    async def async_delete_latest_video_message(self, call: ServiceCall) -> None:
        """Delete the newest stored video message."""

        entry = _entry_for_call(self._hass, call)
        await MessagesUseCase(self._hass, entry).delete_latest_video_message()

    async def async_delete_latest_text_memo(self, call: ServiceCall) -> None:
        """Delete the newest text memo."""

        entry = _entry_for_call(self._hass, call)
        await MemosUseCase(self._hass, entry).delete_latest_text_memo()

    async def async_delete_latest_voice_memo(self, call: ServiceCall) -> None:
        """Delete the newest voice memo."""

        entry = _entry_for_call(self._hass, call)
        await MemosUseCase(self._hass, entry).delete_latest_voice_memo()


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

    for service_name, handler, schema in _base_service_specs(handlers):
        hass.services.async_register(DOMAIN, service_name, cast(Any, handler), schema=schema)


def _base_service_specs(handlers: _C300XServiceHandlers) -> tuple[_ServiceSpec, ...]:
    """Return service specs that are always part of the integration."""

    return (
        *_device_action_service_specs(handlers),
        *_doorbell_media_service_specs(handlers),
        *_ring_analysis_service_specs(handlers),
        *_maintenance_service_specs(handlers),
        *_message_service_specs(handlers),
    )


def _device_action_service_specs(
    handlers: _C300XServiceHandlers,
) -> tuple[_ServiceSpec, ...]:
    return (
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
    )


def _doorbell_media_service_specs(
    handlers: _C300XServiceHandlers,
) -> tuple[_ServiceSpec, ...]:
    return (
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
            vol.Schema({vol.Optional(_ATTR_ENTRY_ID): cv.string}),
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
                    vol.Optional(_ATTR_WAV_OUTPUT_DIR): cv.string,
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
    )


def _ring_analysis_service_specs(
    handlers: _C300XServiceHandlers,
) -> tuple[_ServiceSpec, ...]:
    return (
        (
            SERVICE_RUN_RING_WYOMING_ANALYSIS,
            handlers.async_run_ring_wyoming_analysis,
            vol.Schema(
                {
                    vol.Required(_ATTR_WYOMING_HOST): cv.string,
                    vol.Optional(_ATTR_WYOMING_PORT, default=10300): _wyoming_port,
                    vol.Optional(_ATTR_CAPTURE_PATH): cv.string,
                    vol.Optional(_ATTR_WAV_PATH): cv.string,
                    vol.Optional(_ATTR_RESULT_PATH): cv.string,
                    vol.Optional(_ATTR_LANGUAGE): cv.string,
                    vol.Optional(_ATTR_EXPECTED_PHRASE): cv.string,
                }
            ),
        ),
        (
            SERVICE_EVALUATE_RING_ANALYSIS,
            handlers.async_evaluate_ring_analysis,
            vol.Schema(
                {
                    vol.Optional(_ATTR_ENTRY_ID): cv.string,
                    vol.Optional(_ATTR_RESULT_PATH): cv.string,
                    vol.Optional(_ATTR_DECISION_PATH): cv.string,
                    vol.Optional(_ATTR_CAPTURE_PATH): cv.string,
                    vol.Optional(_ATTR_EXPECTED_PHRASE): cv.string,
                    vol.Optional(
                        _ATTR_UNLOCK_ON_MATCH,
                        default=False,
                    ): _boolean_service_value,
                    vol.Optional(_ATTR_LOCK_ID, default="default"): _lock_id,
                }
            ),
        ),
    )


def _maintenance_service_specs(
    handlers: _C300XServiceHandlers,
) -> tuple[_ServiceSpec, ...]:
    return (
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
    )


def _message_service_specs(
    handlers: _C300XServiceHandlers,
) -> tuple[_ServiceSpec, ...]:
    return (
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
    )


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
                cast(Any, handlers[service_name]),
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
