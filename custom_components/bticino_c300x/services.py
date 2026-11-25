"""Home Assistant services for local testing and automation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from ._api_calls import valid_call_id
from .camera_picture import PICTURE_SCHEMA, camera_picture
from .const import (
    DATA_RUNTIME_ENTRIES,
    DOMAIN,
    SERVICE_ACTIVATE_DOORBELL_VIDEO,
    SERVICE_ALARM_COMMAND,
    SERVICE_ANSWER_CALL,
    SERVICE_CAPTURE_DOORBELL_CALL,
    SERVICE_EVALUATE_RING_ANALYSIS,
    SERVICE_HANGUP_CALL,
    SERVICE_PLAY_LATEST_VIDEO_MESSAGE,
    SERVICE_PLAY_LATEST_VOICE_MEMO,
    SERVICE_RUN_ACTION,
    SERVICE_RUN_RING_WYOMING_ANALYSIS,
    SERVICE_START_HOME_CALL,
    SERVICE_STOP_HOME_CALL,
    SERVICE_WRITE_TEXT_MEMO,
)
from .display_notifications import (
    DISMISS_SCHEMA,
    SHOW_SCHEMA,
    display_notification_service_error,
    notifications_for_entry,
    show_notification,
)
from .exceptions import service_validation_error
from .schema_compat import vol
from .service_authorization import authorized_service
from .service_schema import (
    ATTR_ACTION_ID as _ATTR_ACTION_ID,
)
from .service_schema import (
    ATTR_ANNOUNCEMENT_PATH as _ATTR_ANNOUNCEMENT_PATH,
)
from .service_schema import (
    ATTR_AUDIO as _ATTR_AUDIO,
)
from .service_schema import (
    ATTR_CALL_ID as _ATTR_CALL_ID,
)
from .service_schema import (
    ATTR_CAPTURE_MODE as _ATTR_CAPTURE_MODE,
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
    boolean_service_value as _boolean_service_value,
)
from .service_schema import (
    capture_duration_seconds as _capture_duration_seconds,
)
from .service_schema import (
    home_call_duration_seconds as _home_call_duration_seconds,
)
from .service_schema import (
    text_memo_text as _text_memo_text,
)
from .service_schema import (
    wyoming_port as _wyoming_port,
)
from .service_target import TARGET_FIELDS, ServiceTarget, resolve_service_target
from .use_cases.device_actions import DeviceActionsUseCase
from .use_cases.doorbell_video import DoorbellVideoUseCase
from .use_cases.home_call import HomeCallUseCase
from .use_cases.memos import MemosUseCase
from .use_cases.messages import MessagesUseCase
from .use_cases.ring_analysis import RingAnalysisUseCase
from .use_cases.ring_call import RingCallUseCase
from .use_cases.ring_capture import RingCaptureUseCase

_BASE_SERVICES_MARKER = "__services_registered"
_RESPONSE_SERVICES = {SERVICE_CAPTURE_DOORBELL_CALL, SERVICE_RUN_RING_WYOMING_ANALYSIS, "camera_picture"}
type _ServiceHandler = Callable[[ServiceCall], Awaitable[dict[str, Any] | None]]
type _ServiceSpec = tuple[str, _ServiceHandler, vol.Schema]


class _EntryRuntimeProxy:
    """Expose stored runtime data for HA ConfigEntry objects without attributes."""

    def __init__(self, entry: Any, runtime_data: Any) -> None:
        self._entry = entry
        self.runtime_data = runtime_data

    def __getattr__(self, name: str) -> Any:
        return getattr(self._entry, name)


def _target_for_call(hass: HomeAssistant, call: ServiceCall) -> ServiceTarget:
    target = resolve_service_target(hass, call)
    return ServiceTarget(_entry_with_runtime_data(hass, target.entry), target.unit_id)


def _entry_for_call(hass: HomeAssistant, call: ServiceCall) -> Any:
    return _target_for_call(hass, call).entry


def _entry_with_runtime_data(hass: HomeAssistant, entry: Any) -> Any:
    """Return an entry object with runtime_data or fail as a service error."""

    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is not None:
        return entry

    runtime_entries = hass.data.get(DOMAIN, {}).get(DATA_RUNTIME_ENTRIES, {})
    runtime_data = runtime_entries.get(getattr(entry, "entry_id", None))
    if runtime_data is None:
        raise service_validation_error("agent_command_failed", entry=entry)
    return _EntryRuntimeProxy(entry, runtime_data)


def _call_id(value: Any) -> str:
    call_id = valid_call_id(value)
    if call_id is None:
        raise vol.Invalid("invalid call id")
    return call_id


def _targeted(fields: dict[Any, Any] | None = None) -> vol.Schema:
    return vol.Schema({**TARGET_FIELDS, **(fields or {})})


class _C300XServiceHandlers:
    """Bound service handlers for one Home Assistant instance."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def async_camera_picture(self, call: ServiceCall) -> dict[str, Any]:
        return await camera_picture(_entry_for_call(self._hass, call).runtime_data.api, call.data)

    async def async_show_display_notification(self, call: ServiceCall) -> None:
        entry = _entry_for_call(self._hass, call)
        try:
            show_notification(self._hass, entry, _without_target(call.data))
        except ValueError as err:
            raise display_notification_service_error(err, entry) from err

    async def async_dismiss_display_notification(self, call: ServiceCall) -> None:
        entry = _entry_for_call(self._hass, call)
        try:
            notifications_for_entry(self._hass, entry).dismiss(call.data["notification_id"])
        except ValueError as err:
            raise display_notification_service_error(err, entry) from err

    async def async_run_action(self, call: ServiceCall) -> None:
        """Run one allowlisted Home Assistant action."""

        entry = _entry_for_call(self._hass, call)
        await DeviceActionsUseCase(self._hass, entry).run_action(
            call.data[_ATTR_ACTION_ID], context=getattr(call, "context", None)
        )

    async def async_alarm_command(self, call: ServiceCall) -> None:
        """Forward one alarm command to the configured HA alarm entity."""

        entry = _entry_for_call(self._hass, call)
        await DeviceActionsUseCase(self._hass, entry).alarm_command(
            call.data[_ATTR_COMMAND],
            call.data.get(_ATTR_CODE),
            force=bool(call.data.get(_ATTR_FORCE, False)),
            context=getattr(call, "context", None),
        )

    async def async_activate_doorbell_video(self, call: ServiceCall) -> None:
        """Activate or renew the doorbell video; a unit target names the unit."""

        target = _target_for_call(self._hass, call)
        await DoorbellVideoUseCase(target.entry).activate(
            audio=bool(call.data.get(_ATTR_AUDIO, True)), unit=target.unit_id,
        )

    async def async_answer_call(self, call: ServiceCall) -> None:
        """Answer a call through the agent: ``call_id``, else the current call."""

        entry = _entry_for_call(self._hass, call)
        await RingCallUseCase(entry).answer(call.data.get(_ATTR_CALL_ID))

    async def async_hangup_call(self, call: ServiceCall) -> None:
        """Hang up a call through the agent: ``call_id``, else the current call."""

        entry = _entry_for_call(self._hass, call)
        await RingCallUseCase(entry).hangup(call.data.get(_ATTR_CALL_ID))

    async def async_capture_doorbell_call(self, call: ServiceCall) -> dict[str, Any]:
        """Capture a short C300X doorbell ring-call clip on Home Assistant."""

        entry = _entry_for_call(self._hass, call)
        return await RingCaptureUseCase(self._hass, entry).capture(
            capture_mode=call.data.get(_ATTR_CAPTURE_MODE, "ring"),
            output_path=call.data.get(_ATTR_OUTPUT_PATH),
            wav_output_dir=call.data.get(_ATTR_WAV_OUTPUT_DIR),
            duration_seconds=call.data.get(_ATTR_DURATION_SECONDS, 5),
            include_audio=bool(call.data.get(_ATTR_INCLUDE_AUDIO, True)),
            announcement_path=call.data.get(_ATTR_ANNOUNCEMENT_PATH),
        )

    async def async_run_ring_wyoming_analysis(self, call: ServiceCall) -> dict[str, Any]:
        """Transcribe the latest C300X ring raw WAV through Wyoming Whisper."""

        result = await RingAnalysisUseCase(self._hass).transcribe(
            wyoming_host=call.data[_ATTR_WYOMING_HOST],
            wyoming_port=call.data.get(_ATTR_WYOMING_PORT, 10300),
            capture_path=call.data.get(_ATTR_CAPTURE_PATH),
            wav_path=call.data.get(_ATTR_WAV_PATH),
            result_path=call.data.get(_ATTR_RESULT_PATH),
            language=call.data.get(_ATTR_LANGUAGE),
            expected_phrase=call.data.get(_ATTR_EXPECTED_PHRASE),
        )
        return {"result_path": str(result)}

    async def async_evaluate_ring_analysis(self, call: ServiceCall) -> None:
        """Evaluate a ring-analysis result and optionally open the calling unit."""

        unlock_on_match = bool(call.data.get(_ATTR_UNLOCK_ON_MATCH, False))

        def unlock_target() -> tuple[Any, str | None]:
            target = _target_for_call(self._hass, call)
            return target.entry, target.unit_id

        await RingAnalysisUseCase(self._hass).evaluate(
            result_path=call.data.get(_ATTR_RESULT_PATH),
            decision_path=call.data.get(_ATTR_DECISION_PATH),
            capture_path=call.data.get(_ATTR_CAPTURE_PATH),
            expected_phrase=call.data.get(_ATTR_EXPECTED_PHRASE),
            unlock_on_match=unlock_on_match,
            unlock_target_provider=unlock_target,
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


def _without_target(data: Any) -> dict[str, Any]:
    return {key: value for key, value in dict(data).items() if key not in {"device_id", "entity_id"}}


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register domain services."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_BASE_SERVICES_MARKER):
        return
    _register_base_services(hass, _C300XServiceHandlers(hass))
    domain_data[_BASE_SERVICES_MARKER] = True


def _register_base_services(hass: HomeAssistant, handlers: _C300XServiceHandlers) -> None:
    from homeassistant.core import SupportsResponse

    for service_name, handler, schema in _base_service_specs(handlers):
        hass.services.async_register(
            DOMAIN, service_name,
            authorized_service(hass, service_name, handler, lambda call: _entry_for_call(hass, call)),
            schema=schema,
            supports_response=(
                SupportsResponse.OPTIONAL if service_name in _RESPONSE_SERVICES else SupportsResponse.NONE
            ),
        )


def _base_service_specs(handlers: _C300XServiceHandlers) -> tuple[_ServiceSpec, ...]:
    """Every service of the integration."""

    return (
        (SERVICE_RUN_ACTION, handlers.async_run_action,
         _targeted({vol.Required(_ATTR_ACTION_ID): cv.string})),
        (SERVICE_ALARM_COMMAND, handlers.async_alarm_command, _targeted({
            vol.Required(_ATTR_COMMAND): cv.string,
            vol.Optional(_ATTR_CODE): cv.string,
            vol.Optional(_ATTR_FORCE, default=False): _boolean_service_value,
        })),
        ("show_display_notification", handlers.async_show_display_notification, SHOW_SCHEMA.extend(TARGET_FIELDS)),
        ("dismiss_display_notification", handlers.async_dismiss_display_notification,
         DISMISS_SCHEMA.extend(TARGET_FIELDS)),
        (SERVICE_ACTIVATE_DOORBELL_VIDEO, handlers.async_activate_doorbell_video,
         _targeted({vol.Optional(_ATTR_AUDIO, default=True): _boolean_service_value})),
        (SERVICE_ANSWER_CALL, handlers.async_answer_call, _targeted({vol.Optional(_ATTR_CALL_ID): _call_id})),
        (SERVICE_HANGUP_CALL, handlers.async_hangup_call, _targeted({vol.Optional(_ATTR_CALL_ID): _call_id})),
        (SERVICE_CAPTURE_DOORBELL_CALL, handlers.async_capture_doorbell_call, _targeted({
            vol.Optional(_ATTR_OUTPUT_PATH): cv.string,
            vol.Optional(_ATTR_CAPTURE_MODE, default="ring"): vol.In(("ring", "on_demand")),
            vol.Optional(_ATTR_DURATION_SECONDS, default=5): _capture_duration_seconds,
            vol.Optional(_ATTR_INCLUDE_AUDIO, default=True): _boolean_service_value,
            vol.Optional(_ATTR_WAV_OUTPUT_DIR): cv.string,
            vol.Optional(_ATTR_ANNOUNCEMENT_PATH): cv.string,
        })),
        (SERVICE_START_HOME_CALL, handlers.async_start_home_call,
         _targeted({vol.Optional(_ATTR_DURATION_SECONDS): _home_call_duration_seconds})),
        (SERVICE_STOP_HOME_CALL, handlers.async_stop_home_call, _targeted()),
        ("camera_picture", handlers.async_camera_picture, PICTURE_SCHEMA.extend(TARGET_FIELDS)),
        (SERVICE_RUN_RING_WYOMING_ANALYSIS, handlers.async_run_ring_wyoming_analysis, vol.Schema({
            vol.Required(_ATTR_WYOMING_HOST): cv.string,
            vol.Optional(_ATTR_WYOMING_PORT, default=10300): _wyoming_port,
            vol.Optional(_ATTR_CAPTURE_PATH): cv.string,
            vol.Optional(_ATTR_WAV_PATH): cv.string,
            vol.Optional(_ATTR_RESULT_PATH): cv.string,
            vol.Optional(_ATTR_LANGUAGE): cv.string,
            vol.Optional(_ATTR_EXPECTED_PHRASE): cv.string,
        })),
        (SERVICE_EVALUATE_RING_ANALYSIS, handlers.async_evaluate_ring_analysis, _targeted({
            vol.Optional(_ATTR_RESULT_PATH): cv.string,
            vol.Optional(_ATTR_DECISION_PATH): cv.string,
            vol.Optional(_ATTR_CAPTURE_PATH): cv.string,
            vol.Optional(_ATTR_EXPECTED_PHRASE): cv.string,
            vol.Optional(_ATTR_UNLOCK_ON_MATCH, default=False): _boolean_service_value,
        })),
        (SERVICE_PLAY_LATEST_VIDEO_MESSAGE, handlers.async_play_latest_video_message, _play_media_schema()),
        (SERVICE_PLAY_LATEST_VOICE_MEMO, handlers.async_play_latest_voice_memo, _play_media_schema()),
        (SERVICE_WRITE_TEXT_MEMO, handlers.async_write_text_memo, _targeted({
            vol.Required(_ATTR_TEXT): _text_memo_text,
            vol.Optional(_ATTR_READ, default=False): _boolean_service_value,
        })),
    )


def _play_media_schema() -> vol.Schema:
    return _targeted({vol.Required(_ATTR_MEDIA_PLAYER_ENTITY_ID): cv.entity_id})
