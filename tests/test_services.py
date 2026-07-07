# ruff: noqa: E402

from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

homeassistant = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
homeassistant.__path__ = []
components = sys.modules.setdefault(
    "homeassistant.components",
    types.ModuleType("homeassistant.components"),
)
config_entries = sys.modules.setdefault(
    "homeassistant.config_entries",
    types.ModuleType("homeassistant.config_entries"),
)
const = sys.modules.setdefault("homeassistant.const", types.ModuleType("homeassistant.const"))
core = sys.modules.setdefault("homeassistant.core", types.ModuleType("homeassistant.core"))
exceptions = sys.modules.setdefault(
    "homeassistant.exceptions",
    types.ModuleType("homeassistant.exceptions"),
)
helpers = sys.modules.setdefault(
    "homeassistant.helpers",
    types.ModuleType("homeassistant.helpers"),
)
config_validation = types.ModuleType("homeassistant.helpers.config_validation")
dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
entity = types.ModuleType("homeassistant.helpers.entity")
media_player = types.ModuleType("homeassistant.components.media_player")


class _MediaType:
    MUSIC = "music"
    VIDEO = "video"


class _ServiceCall:  # pragma: no cover - import-time stub only
    data: dict[str, Any] = {}


class _HomeAssistantError(Exception):  # pragma: no cover - import-time stub only
    pass


class _ServiceValidationError(_HomeAssistantError):  # pragma: no cover - import-time stub only
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args)
        self.translation_key = kwargs.get("translation_key")


class _Event:  # pragma: no cover - import-time stub only
    pass


class _ConfigEntry:  # pragma: no cover - import-time stub only
    pass


class _DeviceInfo(dict):  # pragma: no cover - import-time stub only
    pass


class _Entity:  # pragma: no cover - import-time stub only
    pass


config_entries.ConfigEntry = _ConfigEntry
const.ATTR_ENTITY_ID = "entity_id"
core.Event = getattr(core, "Event", _Event)
core.HomeAssistant = getattr(core, "HomeAssistant", object)
core.ServiceCall = getattr(core, "ServiceCall", _ServiceCall)
core.callback = getattr(core, "callback", lambda func: func)
exceptions.ServiceValidationError = _ServiceValidationError
exceptions.HomeAssistantError = _HomeAssistantError
config_validation.string = str
config_validation.entity_id = str
config_validation.config_entry_only_config_schema = lambda _domain: None
dispatcher.async_dispatcher_send = lambda *args, **kwargs: None
dispatcher.async_dispatcher_connect = lambda *args, **kwargs: lambda: None
entity.DeviceInfo = _DeviceInfo
entity.Entity = _Entity
helpers.config_validation = config_validation
helpers.dispatcher = dispatcher
helpers.entity = entity
media_player.DOMAIN = "media_player"
media_player.SERVICE_PLAY_MEDIA = "play_media"
media_player.MediaType = _MediaType
components.media_player = media_player
homeassistant.components = components
homeassistant.config_entries = config_entries
homeassistant.const = const
homeassistant.core = core
homeassistant.helpers = helpers
sys.modules["homeassistant.components.media_player"] = media_player
sys.modules["homeassistant.helpers.config_validation"] = config_validation
sys.modules["homeassistant.helpers.dispatcher"] = dispatcher
sys.modules["homeassistant.helpers.entity"] = entity

from custom_components.bticino_c300x import (
    ring_capture as ring_capture_module,  # noqa: E402
)
from custom_components.bticino_c300x import services as service_module  # noqa: E402
from custom_components.bticino_c300x.action import ActionValidationError  # noqa: E402
from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_DEVICE_UI_ENABLED,
    CONF_MAINTENANCE_TOKEN,
    CONF_VIDEO_ENABLED,
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
from custom_components.bticino_c300x.exceptions import (  # noqa: E402
    service_validation_error,
)
from custom_components.bticino_c300x.services import async_setup_services  # noqa: E402
from custom_components.bticino_c300x.use_cases import (
    common as common_use_cases,  # noqa: E402
)
from custom_components.bticino_c300x.use_cases import (
    device_actions as device_action_use_cases,  # noqa: E402
)
from custom_components.bticino_c300x.use_cases import (
    ring_analysis as ring_analysis_use_cases,  # noqa: E402
)
from custom_components.bticino_c300x.use_cases import (
    ring_capture as ring_capture_use_cases,  # noqa: E402
)

ROOT = Path(__file__).resolve().parents[1]
SERVICE_VALIDATION_ERROR = type(service_validation_error("test_error"))
ring_capture_use_cases.HomeAssistantError = ring_capture_module.HomeAssistantError


@dataclass
class _FakeRuntimeData:
    capabilities: dict[str, Any] = field(default_factory=dict)
    qml_patch_status: dict[str, Any] = field(default_factory=dict)
    api: Any = None
    prepare_doorbell_video_stop: Any = None
    answering_machine_messages: dict[str, Any] = field(default_factory=dict)
    answering_machine_messages_updated_at: Any = None
    memos: dict[str, Any] = field(default_factory=dict)
    memos_updated_at: Any = None


@dataclass
class _FakeEntry:
    runtime_data: _FakeRuntimeData
    entry_id: str = "entry-id"
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(
        default_factory=lambda: {CONF_DEVICE_UI_ENABLED: True}
    )


class _FakeConfigEntries:
    def __init__(self, entries: list[_FakeEntry]) -> None:
        self.entries = entries

    def async_entries(self, domain: str) -> list[_FakeEntry]:
        return self.entries if domain == DOMAIN else []


class _FakeServices:
    def __init__(self) -> None:
        self.registered: set[tuple[str, str]] = set()
        self.handlers: dict[tuple[str, str], Any] = {}
        self.schemas: dict[tuple[str, str], Any] = {}
        self.calls: list[tuple[str, str, dict[str, Any], bool]] = []

    def async_register(self, domain: str, service: str, *args: Any, **_kwargs: Any) -> None:
        self.registered.add((domain, service))
        if args:
            self.handlers[(domain, service)] = args[0]
        if "schema" in _kwargs:
            self.schemas[(domain, service)] = _kwargs["schema"]

    def async_remove(self, domain: str, service: str) -> None:
        self.registered.discard((domain, service))
        self.handlers.pop((domain, service), None)
        self.schemas.pop((domain, service), None)

    async def async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
        *,
        blocking: bool,
    ) -> None:
        self.calls.append((domain, service, data, blocking))


class _FakeHass:
    def __init__(self, entries: list[_FakeEntry]) -> None:
        self.data: dict[str, Any] = {}
        self.config_entries = _FakeConfigEntries(entries)
        self.services = _FakeServices()


class _FakeApi:
    def __init__(self) -> None:
        self.activate_video_calls: list[bool] = []
        self.stop_video_calls = 0
        self.doorbell_video_status: dict[str, Any] = {
            "media_owner": "idle",
            "bridge": {"media_owner": "idle", "clients": 0},
        }
        self.doorbell_video_status_calls = 0
        self.answer_doorbell_call_calls: list[bool] = []
        self.hangup_doorbell_call_calls = 0
        self.hangup_doorbell_call_error: Exception | None = None
        self.doorstation_audio_gain_calls: list[float] = []
        self.capture_doorbell_call_calls = 0
        self.activation_calls: list[str] = []
        self.home_call_start_calls: list[int | None] = []
        self.home_call_stop_calls = 0
        self.text_memo_calls: list[dict[str, Any]] = []
        self.reboot_calls = 0
        self.reload_gui_calls = 0
        self.deleted_video_message_ids: list[str] = []
        self.deleted_memo_ids: list[str] = []

    async def async_activate_doorbell_video(self, audio: bool = True) -> dict[str, Any]:
        self.activate_video_calls.append(audio)
        return {"ok": True, "audio": audio}

    async def async_stop_doorbell_video(self) -> dict[str, Any]:
        self.stop_video_calls += 1
        return {"ok": True}

    async def async_doorbell_video_status(self) -> dict[str, Any]:
        self.doorbell_video_status_calls += 1
        return self.doorbell_video_status

    async def async_answer_doorbell_call(self) -> dict[str, Any]:
        self.answer_doorbell_call_calls.append(True)
        return {"ok": True, "audio": True}

    async def async_set_doorstation_audio_gain_db(
        self,
        gain_db: float,
    ) -> dict[str, Any]:
        self.doorstation_audio_gain_calls.append(gain_db)
        return {"ok": True, "doorstation_audio_gain_db": gain_db}

    async def async_hangup_doorbell_call(self) -> dict[str, Any]:
        self.hangup_doorbell_call_calls += 1
        if self.hangup_doorbell_call_error is not None:
            raise self.hangup_doorbell_call_error
        return {"ok": True}

    async def async_capture_doorbell_call(self) -> dict[str, Any]:
        self.capture_doorbell_call_calls += 1
        return {"ok": True}

    async def async_start_home_call(
        self,
        duration_seconds: int | None = None,
    ) -> dict[str, Any]:
        self.home_call_start_calls.append(duration_seconds)
        return {"ok": True, "duration_seconds": duration_seconds or 0}

    async def async_stop_home_call(self) -> dict[str, Any]:
        self.home_call_stop_calls += 1
        return {"ok": True}

    async def async_run_device_activation(
        self,
        activation_id: str,
    ) -> dict[str, Any]:
        self.activation_calls.append(activation_id)
        return {"ok": True, "id": activation_id}

    async def async_create_text_memo(self, text: str, *, read: bool = False) -> dict[str, Any]:
        self.text_memo_calls.append({"text": text, "read": read})
        return {"ok": True, "id": "text/memo_1"}

    async def async_reboot(self) -> dict[str, Any]:
        self.reboot_calls += 1
        return {"ok": True}

    async def async_reload_gui(self) -> dict[str, Any]:
        self.reload_gui_calls += 1
        return {"ok": True}

    async def async_delete_answering_machine_message(
        self,
        message_id: str,
    ) -> dict[str, Any]:
        self.deleted_video_message_ids.append(message_id)
        return {"ok": True}

    async def async_delete_memo(self, memo_id: str) -> dict[str, Any]:
        self.deleted_memo_ids.append(memo_id)
        return {"ok": True}

    async def async_answering_machine_messages(self) -> dict[str, Any]:
        return {
            "available": True,
            "total": 1,
            "messages": [
                {
                    "id": "video_1",
                    "date": 1,
                    "has_video": True,
                }
            ],
        }

    async def async_memos(self) -> dict[str, Any]:
        return {
            "available": True,
            "total": 2,
            "text_total": 1,
            "voice_total": 1,
            "memos": [
                {
                    "id": "text/memo_1",
                    "kind": "text",
                    "read": False,
                    "text": "new memo",
                },
                {
                    "id": "voice/voice_1.wav",
                    "kind": "voice",
                    "read": False,
                    "has_audio": True,
                }
            ],
        }


def test_delete_services_are_registered_when_device_ui_is_enabled() -> None:
    async def _run() -> None:
        capabilities = {
            "answering_machine": {
                "supported": True,
                "messages": {"supported": True, "delete": True},
            },
            "memos": {"supported": True, "delete": True},
        }
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities=capabilities,
                qml_patch_status={"available": True, "patched": True},
            )
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]

        assert (DOMAIN, SERVICE_PLAY_LATEST_VIDEO_MESSAGE) in hass.services.registered
        assert (DOMAIN, SERVICE_PLAY_LATEST_VOICE_MEMO) in hass.services.registered
        assert (DOMAIN, SERVICE_WRITE_TEXT_MEMO) in hass.services.registered
        assert (DOMAIN, SERVICE_ACTIVATE_DOORBELL_VIDEO) in hass.services.registered
        assert (DOMAIN, SERVICE_STOP_DOORBELL_VIDEO) in hass.services.registered
        assert (DOMAIN, SERVICE_START_HOME_CALL) in hass.services.registered
        assert (DOMAIN, SERVICE_STOP_HOME_CALL) in hass.services.registered
        assert (DOMAIN, SERVICE_RUN_DEVICE_ACTIVATION) in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VIDEO_MESSAGE) in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_TEXT_MEMO) in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VOICE_MEMO) in hass.services.registered

    asyncio.run(_run())


def test_all_documented_services_are_registered_when_capabilities_allow_them() -> None:
    async def _run() -> None:
        capabilities = {
            "answering_machine": {
                "supported": True,
                "messages": {"supported": True, "delete": True},
            },
            "memos": {"supported": True, "delete": True},
        }
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities=capabilities,
                qml_patch_status={"available": True, "patched": True},
            )
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]

        documented_services = set(_services_yaml().keys())
        registered_services = {
            service
            for domain, service in hass.services.registered
            if domain == DOMAIN
        }
        assert registered_services == documented_services

    asyncio.run(_run())


def test_all_registered_service_schemas_accept_documented_payload_shapes() -> None:
    async def _run() -> None:
        capabilities = {
            "answering_machine": {
                "supported": True,
                "messages": {"supported": True, "delete": True},
            },
            "memos": {"supported": True, "delete": True},
        }
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities=capabilities,
                qml_patch_status={"available": True, "patched": True},
            )
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]

        samples: dict[str, dict[str, Any]] = {
            SERVICE_RUN_ACTION: {"entry_id": "entry-id", "action_id": "door_open"},
            SERVICE_RUN_DEVICE_ACTIVATION: {"activation_id": "scene_1"},
            SERVICE_ALARM_COMMAND: {
                "command": "disarm",
                "code": "1234",
                "force": "true",
            },
            SERVICE_STAIR_LIGHT: {"address": "20#1"},
            SERVICE_UNLOCK_DOOR: {"lock_id": "default"},
            SERVICE_ACTIVATE_DOORBELL_VIDEO: {"audio": "false"},
            SERVICE_STOP_DOORBELL_VIDEO: {"entry_id": "entry-id"},
            SERVICE_ANSWER_DOORBELL_CALL: {"entry_id": "entry-id"},
            SERVICE_HANGUP_DOORBELL_CALL: {"entry_id": "entry-id"},
            SERVICE_CAPTURE_DOORBELL_CALL: {
                "output_path": "/media/c300x/test.mp4",
                "duration_seconds": "3",
                "include_audio": "true",
                "wav_output_dir": "/config/c300x",
                "announcement_path": "/config/www/c300x/announce.wav",
            },
            SERVICE_RUN_RING_WYOMING_ANALYSIS: {
                "wyoming_host": "core-whisper",
                "wyoming_port": "10300",
                "capture_path": "/config/c300x/latest.capture.json",
                "wav_path": "/config/c300x/latest.raw.wav",
                "result_path": "/config/c300x/analysis/result.json",
                "language": "de",
                "expected_phrase": "open",
            },
            SERVICE_EVALUATE_RING_ANALYSIS: {
                "result_path": "/config/c300x/analysis/result.json",
                "decision_path": "/config/c300x/analysis/decision.json",
                "capture_path": "/config/c300x/latest.capture.json",
                "expected_phrase": "open",
                "unlock_on_match": "false",
                "lock_id": "default",
            },
            SERVICE_START_HOME_CALL: {"duration_seconds": "0"},
            SERVICE_STOP_HOME_CALL: {"entry_id": "entry-id"},
            SERVICE_REBOOT: {"entry_id": "entry-id"},
            SERVICE_RELOAD_GUI: {"entry_id": "entry-id"},
            SERVICE_PLAY_LATEST_VIDEO_MESSAGE: {
                "media_player_entity_id": "media_player.living_room",
            },
            SERVICE_PLAY_LATEST_VOICE_MEMO: {
                "media_player_entity_id": "media_player.living_room",
            },
            SERVICE_WRITE_TEXT_MEMO: {"text": "hello", "read": "yes"},
            SERVICE_DELETE_LATEST_VIDEO_MESSAGE: {"entry_id": "entry-id"},
            SERVICE_DELETE_LATEST_TEXT_MEMO: {"entry_id": "entry-id"},
            SERVICE_DELETE_LATEST_VOICE_MEMO: {"entry_id": "entry-id"},
        }

        documented_services = set(_services_yaml().keys())
        assert set(samples) == documented_services
        for service_name, payload in samples.items():
            schema = hass.services.schemas[(DOMAIN, service_name)]
            validated = schema(payload)
            for field_name in payload:
                assert field_name in validated

        assert hass.services.schemas[(DOMAIN, SERVICE_ALARM_COMMAND)](
            {"command": "disarm", "force": "true"}
        )["force"] is True
        assert hass.services.schemas[(DOMAIN, SERVICE_ACTIVATE_DOORBELL_VIDEO)](
            {"audio": "false"}
        )["audio"] is False
        assert hass.services.schemas[(DOMAIN, SERVICE_WRITE_TEXT_MEMO)](
            {"text": "hello", "read": "yes"}
        )["read"] is True

    asyncio.run(_run())


def test_delete_services_require_enabled_device_ui_option() -> None:
    async def _run() -> None:
        capabilities = {
            "answering_machine": {
                "supported": True,
                "messages": {"supported": True, "delete": True},
            },
            "memos": {"supported": True, "delete": True},
        }
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities=capabilities,
                qml_patch_status={"available": True, "patched": True},
            ),
            options={CONF_DEVICE_UI_ENABLED: False},
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]

        assert (DOMAIN, SERVICE_PLAY_LATEST_VIDEO_MESSAGE) in hass.services.registered
        assert (DOMAIN, SERVICE_PLAY_LATEST_VOICE_MEMO) in hass.services.registered
        assert (DOMAIN, SERVICE_ACTIVATE_DOORBELL_VIDEO) in hass.services.registered
        assert (DOMAIN, SERVICE_STOP_DOORBELL_VIDEO) in hass.services.registered
        assert (DOMAIN, SERVICE_START_HOME_CALL) in hass.services.registered
        assert (DOMAIN, SERVICE_STOP_HOME_CALL) in hass.services.registered
        assert (DOMAIN, SERVICE_RUN_DEVICE_ACTIVATION) in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VIDEO_MESSAGE) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_TEXT_MEMO) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VOICE_MEMO) not in hass.services.registered

    asyncio.run(_run())


def _services_yaml() -> dict[str, Any]:
    return yaml.safe_load(
        (ROOT / "custom_components" / "bticino_c300x" / "services.yaml").read_text(
            encoding="utf-8"
        )
    )


def test_delete_services_require_agent_delete_capabilities() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={
                    "answering_machine": {
                        "supported": True,
                        "messages": {"supported": True, "delete": False},
                    },
                    "memos": {"supported": True, "delete": False},
                },
                qml_patch_status={"available": True, "patched": True},
            )
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]

        assert (DOMAIN, SERVICE_DELETE_LATEST_VIDEO_MESSAGE) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_TEXT_MEMO) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VOICE_MEMO) not in hass.services.registered

    asyncio.run(_run())


def test_delete_services_require_active_gui_patch() -> None:
    async def _run() -> None:
        capabilities = {
            "answering_machine": {
                "supported": True,
                "messages": {"supported": True, "delete": True},
            },
            "memos": {"supported": True, "delete": True},
        }
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities=capabilities,
                qml_patch_status={"available": True, "patched": False},
            )
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]

        assert (DOMAIN, SERVICE_DELETE_LATEST_VIDEO_MESSAGE) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_TEXT_MEMO) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VOICE_MEMO) not in hass.services.registered

    asyncio.run(_run())


def test_delete_services_sync_after_qml_patch_signal(monkeypatch) -> None:  # noqa: ANN001
    captured: dict[str, Any] = {}

    def _connect(_hass: Any, signal: str, callback: Any) -> Any:
        captured["signal"] = signal
        captured["callback"] = callback
        return lambda: None

    monkeypatch.setattr(service_module, "async_dispatcher_connect", _connect)

    async def _run() -> None:
        capabilities = {
            "answering_machine": {
                "supported": True,
                "messages": {"supported": True, "delete": True},
            },
            "memos": {"supported": True, "delete": True},
        }
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities=capabilities,
                qml_patch_status={"available": True, "patched": False},
            )
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]

        assert captured["signal"] == SIGNAL_QML_PATCH_CHANGED
        assert (DOMAIN, SERVICE_DELETE_LATEST_VIDEO_MESSAGE) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_TEXT_MEMO) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VOICE_MEMO) not in hass.services.registered

        entry.runtime_data.qml_patch_status = {"available": True, "patched": True}
        captured["callback"](entry.entry_id)

        assert (DOMAIN, SERVICE_DELETE_LATEST_VIDEO_MESSAGE) in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_TEXT_MEMO) in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VOICE_MEMO) in hass.services.registered

    asyncio.run(_run())


def test_delete_services_are_removed_after_qml_restore_signal(monkeypatch) -> None:  # noqa: ANN001
    captured: dict[str, Any] = {}

    def _connect(_hass: Any, signal: str, callback: Any) -> Any:
        captured["signal"] = signal
        captured["callback"] = callback
        return lambda: None

    monkeypatch.setattr(service_module, "async_dispatcher_connect", _connect)

    async def _run() -> None:
        capabilities = {
            "answering_machine": {
                "supported": True,
                "messages": {"supported": True, "delete": True},
            },
            "memos": {"supported": True, "delete": True},
        }
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities=capabilities,
                qml_patch_status={"available": True, "patched": True},
            )
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]

        assert captured["signal"] == SIGNAL_QML_PATCH_CHANGED
        assert (DOMAIN, SERVICE_DELETE_LATEST_VIDEO_MESSAGE) in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_TEXT_MEMO) in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VOICE_MEMO) in hass.services.registered

        entry.runtime_data.qml_patch_status = {"available": True, "patched": False}
        captured["callback"](entry.entry_id)

        assert (DOMAIN, SERVICE_DELETE_LATEST_VIDEO_MESSAGE) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_TEXT_MEMO) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VOICE_MEMO) not in hass.services.registered

    asyncio.run(_run())


def test_service_setup_tolerates_not_loaded_entries_without_runtime_data() -> None:
    async def _run() -> None:
        hass = _FakeHass([object()])  # type: ignore[list-item]

        await async_setup_services(hass)  # type: ignore[arg-type]

        assert (DOMAIN, SERVICE_PLAY_LATEST_VIDEO_MESSAGE) in hass.services.registered
        assert (DOMAIN, SERVICE_PLAY_LATEST_VOICE_MEMO) in hass.services.registered
        assert (DOMAIN, SERVICE_ACTIVATE_DOORBELL_VIDEO) in hass.services.registered
        assert (DOMAIN, SERVICE_START_HOME_CALL) in hass.services.registered
        assert (DOMAIN, SERVICE_STOP_HOME_CALL) in hass.services.registered
        assert (DOMAIN, SERVICE_RUN_DEVICE_ACTIVATION) in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VIDEO_MESSAGE) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_TEXT_MEMO) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VOICE_MEMO) not in hass.services.registered

    asyncio.run(_run())


def test_service_entry_lookup_requires_entry_id_for_multiple_entries() -> None:
    async def _run() -> None:
        hass = _FakeHass(
            [
                _FakeEntry(_FakeRuntimeData(api=_FakeApi()), entry_id="one"),
                _FakeEntry(_FakeRuntimeData(api=_FakeApi()), entry_id="two"),
            ]
        )

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_RUN_DEVICE_ACTIVATION)]

        try:
            await handler(types.SimpleNamespace(data={"activation_id": "scene_1"}))
        except SERVICE_VALIDATION_ERROR as err:
            assert getattr(err, "translation_key", None) == "entry_id_required"
        else:
            raise AssertionError("missing entry id was accepted")

        try:
            await handler(
                types.SimpleNamespace(
                    data={"entry_id": "missing", "activation_id": "scene_1"}
                )
            )
        except SERVICE_VALIDATION_ERROR as err:
            assert getattr(err, "translation_key", None) == "unknown_entry"
        else:
            raise AssertionError("unknown entry id was accepted")

    asyncio.run(_run())


def test_service_entry_lookup_accepts_explicit_entry_id() -> None:
    async def _run() -> None:
        api_one = _FakeApi()
        api_two = _FakeApi()
        hass = _FakeHass(
            [
                _FakeEntry(_FakeRuntimeData(api=api_one), entry_id="one"),
                _FakeEntry(_FakeRuntimeData(api=api_two), entry_id="two"),
            ]
        )

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_RUN_DEVICE_ACTIVATION)]
        await handler(
            types.SimpleNamespace(
                data={"entry_id": "two", "activation_id": "scene_1"}
            )
        )

        assert api_one.activation_calls == []
        assert api_two.activation_calls == ["scene_1"]

    asyncio.run(_run())


def test_base_executor_services_call_expected_helpers(monkeypatch) -> None:  # noqa: ANN001
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def _action(*args: Any, **kwargs: Any) -> None:
        calls.append(("action", args, kwargs))

    async def _alarm(*args: Any, **kwargs: Any) -> None:
        calls.append(("alarm", args, kwargs))

    async def _stair(*args: Any, **kwargs: Any) -> None:
        calls.append(("stair", args, kwargs))

    async def _unlock(*args: Any, **kwargs: Any) -> None:
        calls.append(("unlock", args, kwargs))

    monkeypatch.setattr(device_action_use_cases, "async_execute_action", _action)
    monkeypatch.setattr(device_action_use_cases, "async_execute_alarm_command", _alarm)
    monkeypatch.setattr(device_action_use_cases, "async_trigger_stair_light", _stair)
    monkeypatch.setattr(device_action_use_cases, "async_unlock_door", _unlock)

    async def _run() -> None:
        entry = _FakeEntry(_FakeRuntimeData(api=_FakeApi()))
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        await hass.services.handlers[(DOMAIN, SERVICE_RUN_ACTION)](
            types.SimpleNamespace(data={"action_id": "entry_light"})
        )
        await hass.services.handlers[(DOMAIN, SERVICE_ALARM_COMMAND)](
            types.SimpleNamespace(data={"command": "disarm", "code": "1234", "force": True})
        )
        await hass.services.handlers[(DOMAIN, SERVICE_STAIR_LIGHT)](
            types.SimpleNamespace(data={"address": "10"})
        )
        await hass.services.handlers[(DOMAIN, SERVICE_UNLOCK_DOOR)](
            types.SimpleNamespace(data={"lock_id": "main"})
        )

    asyncio.run(_run())

    assert [call[0] for call in calls] == ["action", "alarm", "stair", "unlock"]
    assert calls[0][1][2] == "entry_light"
    assert calls[1][1][2:] == ("disarm", "1234")
    assert calls[1][2] == {"force": True}
    assert calls[2][1][2] == "10"
    assert calls[3][1][2] == "main"


def test_action_and_alarm_services_translate_executor_errors(monkeypatch) -> None:  # noqa: ANN001
    action_error: Exception | None = ActionValidationError("bad")
    alarm_error: Exception | None = ActionValidationError("bad")

    async def _action(*_args: Any, **_kwargs: Any) -> None:
        if action_error is not None:
            raise action_error

    async def _alarm(*_args: Any, **_kwargs: Any) -> None:
        if alarm_error is not None:
            raise alarm_error

    monkeypatch.setattr(device_action_use_cases, "async_execute_action", _action)
    monkeypatch.setattr(device_action_use_cases, "async_execute_alarm_command", _alarm)

    async def _run() -> None:
        nonlocal action_error, alarm_error
        entry = _FakeEntry(_FakeRuntimeData(api=_FakeApi()))
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        try:
            await hass.services.handlers[(DOMAIN, SERVICE_RUN_ACTION)](
                types.SimpleNamespace(data={"action_id": "entry_light"})
            )
        except SERVICE_VALIDATION_ERROR as err:
            assert getattr(err, "translation_key", None) == "invalid_action_id"
        else:
            raise AssertionError("action validation error was not translated")

        action_error = KeyError("entry_light")
        try:
            await hass.services.handlers[(DOMAIN, SERVICE_RUN_ACTION)](
                types.SimpleNamespace(data={"action_id": "entry_light"})
            )
        except SERVICE_VALIDATION_ERROR as err:
            assert getattr(err, "translation_key", None) == "unknown_action"
        else:
            raise AssertionError("unknown action was not translated")

        try:
            await hass.services.handlers[(DOMAIN, SERVICE_ALARM_COMMAND)](
                types.SimpleNamespace(data={"command": "bad"})
            )
        except SERVICE_VALIDATION_ERROR as err:
            assert getattr(err, "translation_key", None) == "invalid_alarm_command"
        else:
            raise AssertionError("alarm validation error was not translated")

        alarm_error = ValueError("missing")
        try:
            await hass.services.handlers[(DOMAIN, SERVICE_ALARM_COMMAND)](
                types.SimpleNamespace(data={"command": "disarm"})
            )
        except SERVICE_VALIDATION_ERROR as err:
            assert getattr(err, "translation_key", None) == "alarm_not_configured"
        else:
            raise AssertionError("alarm config error was not translated")

    asyncio.run(_run())


def test_maintenance_services_require_supported_token() -> None:
    async def _run() -> None:
        api = _FakeApi()
        entry = _FakeEntry(
            _FakeRuntimeData(
                api=api,
                capabilities={
                    "maintenance": {
                        "supported": True,
                        "reboot": True,
                        "gui_reload": True,
                    }
                },
            ),
            data={"maintenance_token": "token"},
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        await hass.services.handlers[(DOMAIN, SERVICE_REBOOT)](
            types.SimpleNamespace(data={})
        )
        await hass.services.handlers[(DOMAIN, SERVICE_RELOAD_GUI)](
            types.SimpleNamespace(data={})
        )

        assert api.reboot_calls == 1
        assert api.reload_gui_calls == 1

        entry.data = {}
        try:
            await hass.services.handlers[(DOMAIN, SERVICE_REBOOT)](
                types.SimpleNamespace(data={})
            )
        except SERVICE_VALIDATION_ERROR as err:
            assert (
                getattr(err, "translation_key", None)
                == "maintenance_action_not_supported"
            )
        else:
            raise AssertionError("maintenance command without token was accepted")

    asyncio.run(_run())


def test_latest_media_services_call_media_player() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            _FakeRuntimeData(
                api=_FakeApi(),
                answering_machine_messages={
                    "messages": [
                        {
                            "id": "video_1",
                            "date": 1,
                            "has_video": True,
                        }
                    ]
                },
                memos={
                    "memos": [
                        {
                            "id": "voice/voice_1.wav",
                            "kind": "voice",
                            "date": "2026-01-01T00:00:00",
                            "has_audio": True,
                        }
                    ]
                },
            )
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        await hass.services.handlers[(DOMAIN, SERVICE_PLAY_LATEST_VIDEO_MESSAGE)](
            types.SimpleNamespace(data={"media_player_entity_id": "media_player.room"})
        )
        await hass.services.handlers[(DOMAIN, SERVICE_PLAY_LATEST_VOICE_MEMO)](
            types.SimpleNamespace(data={"media_player_entity_id": "media_player.room"})
        )

        assert len(hass.services.calls) == 2
        assert hass.services.calls[0][0:2] == ("media_player", "play_media")
        assert hass.services.calls[0][2]["media_content_type"] == "video"
        assert hass.services.calls[1][2]["media_content_type"] == "music"

    asyncio.run(_run())


def test_analysis_services_call_helpers(monkeypatch) -> None:  # noqa: ANN001
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _wyoming(_hass: Any, **kwargs: Any) -> None:
        calls.append(("wyoming", kwargs))

    async def _evaluate(_hass: Any, **kwargs: Any) -> Any:
        calls.append(("evaluate", kwargs))
        return types.SimpleNamespace(matched=True)

    async def _unlock(*args: Any, **kwargs: Any) -> None:
        calls.append(("unlock", {"args": args, **kwargs}))

    monkeypatch.setattr(ring_analysis_use_cases, "async_run_wyoming_ring_analysis", _wyoming)
    monkeypatch.setattr(ring_analysis_use_cases, "async_evaluate_ring_analysis", _evaluate)
    monkeypatch.setattr(device_action_use_cases, "async_unlock_door", _unlock)

    async def _run() -> None:
        entry = _FakeEntry(_FakeRuntimeData(api=_FakeApi()))
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        await hass.services.handlers[(DOMAIN, SERVICE_RUN_RING_WYOMING_ANALYSIS)](
            types.SimpleNamespace(
                data={
                    "wyoming_host": "localhost",
                    "wyoming_port": 10300,
                    "capture_path": "/config/c300x/latest.capture.json",
                    "wav_path": "/config/c300x/latest.raw.wav",
                    "result_path": "/config/c300x/result.json",
                    "language": "de",
                    "expected_phrase": "open",
                }
            )
        )
        await hass.services.handlers[(DOMAIN, SERVICE_EVALUATE_RING_ANALYSIS)](
            types.SimpleNamespace(
                data={
                    "result_path": "/config/c300x/result.json",
                    "decision_path": "/config/c300x/decision.json",
                    "capture_path": "/config/c300x/latest.capture.json",
                    "expected_phrase": "open",
                    "unlock_on_match": True,
                    "lock_id": "default",
                }
            )
        )

    asyncio.run(_run())

    assert calls[0] == (
        "wyoming",
        {
            "wyoming_host": "localhost",
            "wyoming_port": 10300,
            "capture_path": "/config/c300x/latest.capture.json",
            "wav_path": "/config/c300x/latest.raw.wav",
            "result_path": "/config/c300x/result.json",
            "language": "de",
            "expected_phrase": "open",
        },
    )
    assert calls[1] == (
        "evaluate",
        {
            "result_path": "/config/c300x/result.json",
            "decision_path": "/config/c300x/decision.json",
            "capture_path": "/config/c300x/latest.capture.json",
            "expected_phrase": "open",
            "require_capture": True,
        },
    )
    assert calls[2][0] == "unlock"
    assert calls[2][1]["args"][2] == "default"


def test_evaluate_ring_analysis_does_not_unlock_without_match(monkeypatch) -> None:  # noqa: ANN001
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _evaluate(_hass: Any, **kwargs: Any) -> Any:
        calls.append(("evaluate", kwargs))
        return types.SimpleNamespace(matched=False)

    async def _unlock(*args: Any, **kwargs: Any) -> None:
        calls.append(("unlock", {"args": args, **kwargs}))

    monkeypatch.setattr(ring_analysis_use_cases, "async_evaluate_ring_analysis", _evaluate)
    monkeypatch.setattr(device_action_use_cases, "async_unlock_door", _unlock)

    async def _run() -> None:
        entry = _FakeEntry(_FakeRuntimeData(api=_FakeApi()))
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        await hass.services.handlers[(DOMAIN, SERVICE_EVALUATE_RING_ANALYSIS)](
            types.SimpleNamespace(
                data={
                    "result_path": "/config/c300x/result.json",
                    "decision_path": "/config/c300x/decision.json",
                    "capture_path": "/config/c300x/latest.capture.json",
                    "expected_phrase": "open",
                    "unlock_on_match": True,
                    "lock_id": "default",
                }
            )
        )

    asyncio.run(_run())

    assert calls == [
        (
            "evaluate",
            {
                "result_path": "/config/c300x/result.json",
                "decision_path": "/config/c300x/decision.json",
                "capture_path": "/config/c300x/latest.capture.json",
                "expected_phrase": "open",
                "require_capture": True,
            },
        )
    ]


def test_evaluate_ring_analysis_resolves_entry_only_after_match(monkeypatch) -> None:  # noqa: ANN001
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _evaluate(_hass: Any, **kwargs: Any) -> Any:
        calls.append(("evaluate", kwargs))
        return types.SimpleNamespace(matched=False)

    async def _unlock(*args: Any, **kwargs: Any) -> None:
        calls.append(("unlock", {"args": args, **kwargs}))

    monkeypatch.setattr(ring_analysis_use_cases, "async_evaluate_ring_analysis", _evaluate)
    monkeypatch.setattr(device_action_use_cases, "async_unlock_door", _unlock)

    async def _run() -> None:
        hass = _FakeHass(
            [
                _FakeEntry(_FakeRuntimeData(api=_FakeApi()), entry_id="one"),
                _FakeEntry(_FakeRuntimeData(api=_FakeApi()), entry_id="two"),
            ]
        )

        await async_setup_services(hass)  # type: ignore[arg-type]
        await hass.services.handlers[(DOMAIN, SERVICE_EVALUATE_RING_ANALYSIS)](
            types.SimpleNamespace(
                data={
                    "result_path": "/config/c300x/result.json",
                    "decision_path": "/config/c300x/decision.json",
                    "capture_path": "/config/c300x/latest.capture.json",
                    "expected_phrase": "open",
                    "unlock_on_match": True,
                    "lock_id": "default",
                }
            )
        )

    asyncio.run(_run())

    assert calls == [
        (
            "evaluate",
            {
                "result_path": "/config/c300x/result.json",
                "decision_path": "/config/c300x/decision.json",
                "capture_path": "/config/c300x/latest.capture.json",
                "expected_phrase": "open",
                "require_capture": True,
            },
        )
    ]


def test_evaluate_ring_analysis_marks_capture_after_successful_unlock(monkeypatch) -> None:  # noqa: ANN001
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _evaluate(_hass: Any, **kwargs: Any) -> Any:
        calls.append(("evaluate", kwargs))
        return types.SimpleNamespace(matched=True, capture_id="capture-1")

    async def _unlock(*args: Any, **kwargs: Any) -> None:
        calls.append(("unlock", {"args": args, **kwargs}))

    async def _mark(_hass: Any, capture_id: str | None) -> None:
        calls.append(("mark", {"capture_id": capture_id}))

    monkeypatch.setattr(ring_analysis_use_cases, "async_evaluate_ring_analysis", _evaluate)
    monkeypatch.setattr(device_action_use_cases, "async_unlock_door", _unlock)
    monkeypatch.setattr(ring_analysis_use_cases, "async_mark_ring_capture_used", _mark)

    async def _run() -> None:
        entry = _FakeEntry(_FakeRuntimeData(api=_FakeApi()))
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        await hass.services.handlers[(DOMAIN, SERVICE_EVALUATE_RING_ANALYSIS)](
            types.SimpleNamespace(
                data={
                    "result_path": "/config/c300x/result.json",
                    "decision_path": "/config/c300x/decision.json",
                    "capture_path": "/config/c300x/latest.capture.json",
                    "expected_phrase": "open",
                    "unlock_on_match": True,
                    "lock_id": "default",
                }
            )
        )

    asyncio.run(_run())

    assert calls[0] == (
        "evaluate",
        {
            "result_path": "/config/c300x/result.json",
            "decision_path": "/config/c300x/decision.json",
            "capture_path": "/config/c300x/latest.capture.json",
            "expected_phrase": "open",
            "require_capture": True,
        },
    )
    assert calls[1][0] == "unlock"
    assert calls[2] == ("mark", {"capture_id": "capture-1"})


def test_evaluate_ring_analysis_does_not_consume_capture_when_entry_is_missing(
    monkeypatch,
) -> None:  # noqa: ANN001
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _evaluate(_hass: Any, **kwargs: Any) -> Any:
        calls.append(("evaluate", kwargs))
        return types.SimpleNamespace(matched=True, capture_id="capture-1")

    async def _unlock(*args: Any, **kwargs: Any) -> None:
        calls.append(("unlock", {"args": args, **kwargs}))

    async def _mark(_hass: Any, capture_id: str | None) -> None:
        calls.append(("mark", {"capture_id": capture_id}))

    monkeypatch.setattr(ring_analysis_use_cases, "async_evaluate_ring_analysis", _evaluate)
    monkeypatch.setattr(device_action_use_cases, "async_unlock_door", _unlock)
    monkeypatch.setattr(ring_analysis_use_cases, "async_mark_ring_capture_used", _mark)

    async def _run() -> None:
        hass = _FakeHass(
            [
                _FakeEntry(_FakeRuntimeData(api=_FakeApi()), entry_id="one"),
                _FakeEntry(_FakeRuntimeData(api=_FakeApi()), entry_id="two"),
            ]
        )

        await async_setup_services(hass)  # type: ignore[arg-type]
        try:
            await hass.services.handlers[(DOMAIN, SERVICE_EVALUATE_RING_ANALYSIS)](
                types.SimpleNamespace(
                    data={
                        "result_path": "/config/c300x/result.json",
                        "decision_path": "/config/c300x/decision.json",
                        "capture_path": "/config/c300x/latest.capture.json",
                        "expected_phrase": "open",
                        "unlock_on_match": True,
                        "lock_id": "default",
                    }
                )
            )
        except Exception as err:
            assert getattr(err, "translation_key", None) == "entry_id_required"
        else:
            raise AssertionError("entry_id_required was not raised")

    asyncio.run(_run())

    assert calls == [
        (
            "evaluate",
            {
                "result_path": "/config/c300x/result.json",
                "decision_path": "/config/c300x/decision.json",
                "capture_path": "/config/c300x/latest.capture.json",
                "expected_phrase": "open",
                "require_capture": True,
            },
        )
    ]


def test_ring_analysis_use_case_requires_entry_for_matching_unlock(monkeypatch) -> None:  # noqa: ANN001
    async def _evaluate(_hass: Any, **_kwargs: Any) -> Any:
        return types.SimpleNamespace(matched=True, capture_id="capture-1")

    monkeypatch.setattr(ring_analysis_use_cases, "async_evaluate_ring_analysis", _evaluate)

    async def _run() -> None:
        try:
            await ring_analysis_use_cases.RingAnalysisUseCase(_FakeHass([])).evaluate(
                unlock_on_match=True,
            )
        except SERVICE_VALIDATION_ERROR as err:
            assert _translation_key(err) == "entry_id_required"
        else:
            raise AssertionError("entry_id_required was not raised")

    asyncio.run(_run())


def test_delete_services_call_agent_and_refresh_cache(monkeypatch) -> None:  # noqa: ANN001
    dispatcher_calls: list[tuple[Any, ...]] = []
    diagnostics_refreshes: list[str] = []

    monkeypatch.setattr(
        common_use_cases,
        "async_dispatcher_send",
        lambda *args: dispatcher_calls.append(args),
    )

    async def _refresh_diagnostics(_hass: Any, entry: Any) -> None:
        diagnostics_refreshes.append(entry.entry_id)

    monkeypatch.setattr(
        common_use_cases,
        "async_refresh_agent_diagnostics",
        _refresh_diagnostics,
    )

    async def _run() -> None:
        api = _FakeApi()
        entry = _FakeEntry(
            _FakeRuntimeData(
                api=api,
                capabilities={
                    "answering_machine": {
                        "supported": True,
                        "messages": {
                            "supported": True,
                            "delete": True,
                        },
                    },
                    "memos": {
                        "supported": True,
                        "delete": True,
                    },
                },
                qml_patch_status={"available": True, "patched": True},
                answering_machine_messages={
                    "messages": [
                        {
                            "id": "video_1",
                            "date": 1,
                            "has_video": True,
                        }
                    ]
                },
                memos={
                    "memos": [
                        {
                            "id": "text/memo_1",
                            "kind": "text",
                            "date": "2026-01-01T00:00:00",
                        },
                        {
                            "id": "voice/voice_1.wav",
                            "kind": "voice",
                            "date": "2026-01-01T00:00:00",
                            "has_audio": True,
                        },
                    ]
                },
            )
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        await hass.services.handlers[(DOMAIN, SERVICE_DELETE_LATEST_VIDEO_MESSAGE)](
            types.SimpleNamespace(data={})
        )
        await hass.services.handlers[(DOMAIN, SERVICE_DELETE_LATEST_TEXT_MEMO)](
            types.SimpleNamespace(data={})
        )
        await hass.services.handlers[(DOMAIN, SERVICE_DELETE_LATEST_VOICE_MEMO)](
            types.SimpleNamespace(data={})
        )

        assert api.deleted_video_message_ids == ["video_1"]
        assert api.deleted_memo_ids == ["text/memo_1", "voice/voice_1.wav"]

    asyncio.run(_run())

    assert len(dispatcher_calls) == 3
    assert diagnostics_refreshes == ["entry-id", "entry-id", "entry-id"]


def test_activate_doorbell_video_service_calls_agent_api() -> None:
    async def _run() -> None:
        api = _FakeApi()
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={"doorbell_video": {"supported": True}},
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_ACTIVATE_DOORBELL_VIDEO)]
        await handler(types.SimpleNamespace(data={"audio": False}))

        assert api.activate_video_calls == [False]

    asyncio.run(_run())


def test_stop_doorbell_video_service_calls_agent_api() -> None:
    async def _run() -> None:
        api = _FakeApi()
        api.doorbell_video_status = {
            "media_owner": "agent",
            "window_available": True,
            "bridge": {
                "media_owner": "agent",
                "clients": 0,
                "media_active": True,
            },
        }
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={"doorbell_video": {"supported": True}},
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_STOP_DOORBELL_VIDEO)]
        await handler(types.SimpleNamespace(data={}))

        assert api.stop_video_calls == 1

    asyncio.run(_run())


def test_stop_doorbell_video_service_stops_agent_after_prepare_reaches_idle() -> None:
    async def _run() -> None:
        calls: list[str] = []

        class _RecordingApi(_FakeApi):
            async def async_doorbell_video_status(self) -> dict[str, Any]:
                calls.append("status")
                return await super().async_doorbell_video_status()

            async def async_stop_doorbell_video(self) -> dict[str, Any]:
                calls.append("agent_stop")
                return await super().async_stop_doorbell_video()

        api = _RecordingApi()
        api.doorbell_video_status = {
            "media_owner": "agent",
            "window_available": True,
            "bridge": {
                "media_owner": "agent",
                "clients": 1,
                "media_active": True,
            },
        }

        async def _prepare_stop() -> None:
            calls.append("prepare_stop")
            api.doorbell_video_status = {
                "media_owner": "idle",
                "window_available": False,
                "bridge": {
                    "media_owner": "idle",
                    "clients": 0,
                },
            }

        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={"doorbell_video": {"supported": True}},
                api=api,
                prepare_doorbell_video_stop=_prepare_stop,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_STOP_DOORBELL_VIDEO)]
        await handler(types.SimpleNamespace(data={}))

        assert calls == ["status", "prepare_stop", "agent_stop"]
        assert api.doorbell_video_status_calls == 1
        assert api.stop_video_calls == 1

    asyncio.run(_run())


def test_answer_doorbell_call_service_calls_agent_api() -> None:
    async def _run() -> None:
        api = _FakeApi()
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={"doorbell_call": {"supported": True}},
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_ANSWER_DOORBELL_CALL)]
        await handler(types.SimpleNamespace(data={}))

        assert api.answer_doorbell_call_calls == [True]

    asyncio.run(_run())


def test_hangup_doorbell_call_service_calls_agent_api() -> None:
    async def _run() -> None:
        api = _FakeApi()
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={"doorbell_call": {"supported": True}},
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_HANGUP_DOORBELL_CALL)]
        await handler(types.SimpleNamespace(data={}))

        assert api.hangup_doorbell_call_calls == 1

    asyncio.run(_run())


def test_hangup_doorbell_call_service_prepares_stop_before_agent_hangup() -> None:
    async def _run() -> None:
        calls: list[str] = []

        class _RecordingApi(_FakeApi):
            async def async_hangup_doorbell_call(self) -> dict[str, Any]:
                calls.append("agent_hangup")
                return await super().async_hangup_doorbell_call()

        api = _RecordingApi()

        async def _prepare_stop() -> None:
            calls.append("prepare_stop")

        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={"doorbell_call": {"supported": True}},
                api=api,
                prepare_doorbell_video_stop=_prepare_stop,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_HANGUP_DOORBELL_CALL)]
        await handler(types.SimpleNamespace(data={}))

        assert calls == ["prepare_stop", "agent_hangup"]
        assert api.hangup_doorbell_call_calls == 1

    asyncio.run(_run())


def test_capture_doorbell_call_service_records_on_home_assistant(monkeypatch) -> None:  # noqa: ANN001
    async def _run() -> None:
        api = _FakeApi()
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={
                    "doorbell_video": {"supported": True},
                    "doorbell_call": {"supported": True},
                },
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])
        calls: list[dict[str, Any]] = []

        async def _capture(*args: Any, **kwargs: Any) -> None:
            calls.append({"args": args, "kwargs": kwargs})

        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", _capture)

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        await handler(
            types.SimpleNamespace(
                data={
                    "output_path": "/media/c300x/test.mp4",
                    "duration_seconds": 3,
                    "include_audio": True,
                    "wav_output_dir": "/config/c300x",
                    "announcement_path": "/media/c300x/announce.wav",
                }
            )
        )

        assert calls == [
            {
                "args": (hass, entry),
                "kwargs": {
                    "output_path": "/media/c300x/test.mp4",
                    "wav_output_dir": "/config/c300x",
                    "duration_seconds": 3,
                    "include_audio": True,
                    "announcement_path": "/media/c300x/announce.wav",
                },
            }
        ]
        assert api.capture_doorbell_call_calls == 0
        assert api.doorbell_video_status_calls == 1
        assert api.answer_doorbell_call_calls == [True]
        assert api.hangup_doorbell_call_calls == 1

    asyncio.run(_run())


def test_capture_doorbell_call_service_uses_stored_runtime_data(monkeypatch) -> None:  # noqa: ANN001
    async def _run() -> None:
        api = _FakeApi()
        runtime_data = _FakeRuntimeData(
            capabilities={
                "doorbell_video": {"supported": True},
                "doorbell_call": {"supported": True},
            },
            api=api,
        )
        entry = types.SimpleNamespace(
            entry_id="entry-id",
            data={CONF_VIDEO_ENABLED: True},
            options={CONF_DEVICE_UI_ENABLED: True},
        )
        hass = _FakeHass([entry])  # type: ignore[list-item]
        hass.data.setdefault(DOMAIN, {})[DATA_RUNTIME_ENTRIES] = {
            entry.entry_id: runtime_data
        }
        calls: list[dict[str, Any]] = []

        async def _capture(*args: Any, **kwargs: Any) -> None:
            calls.append({"args": args, "kwargs": kwargs})

        monkeypatch.setattr(
            ring_capture_use_cases,
            "async_capture_doorbell_ring_call",
            _capture,
        )

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        await handler(types.SimpleNamespace(data={"include_audio": True}))

        assert len(calls) == 1
        captured_entry = calls[0]["args"][1]
        assert captured_entry.entry_id == "entry-id"
        assert captured_entry.runtime_data is runtime_data
        assert api.doorbell_video_status_calls == 1
        assert api.answer_doorbell_call_calls == [True]
        assert api.hangup_doorbell_call_calls == 1

    asyncio.run(_run())


def test_ring_capture_and_analysis_service_schemas_accept_documented_fields() -> None:
    async def _run() -> None:
        entry = _FakeEntry(_FakeRuntimeData(api=_FakeApi()))
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]

        capture_schema = hass.services.schemas[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        assert capture_schema(
            {
                "output_path": "/media/c300x/test.mp4",
                "duration_seconds": 3,
                "include_audio": "true",
                "wav_output_dir": "/config/c300x",
                "announcement_path": "/config/www/c300x/announce.wav",
            }
        ) == {
            "output_path": "/media/c300x/test.mp4",
            "duration_seconds": 3,
            "include_audio": True,
            "wav_output_dir": "/config/c300x",
            "announcement_path": "/config/www/c300x/announce.wav",
        }

        wyoming_schema = hass.services.schemas[(DOMAIN, SERVICE_RUN_RING_WYOMING_ANALYSIS)]
        assert wyoming_schema(
            {
                "wyoming_host": "core-whisper",
                "wyoming_port": "10300",
                "capture_path": "/config/c300x/latest.capture.json",
                "wav_path": "/config/c300x/latest.raw.wav",
                "result_path": "/config/c300x/analysis/result.json",
                "language": "de",
                "expected_phrase": "open",
            }
        ) == {
            "wyoming_host": "core-whisper",
            "wyoming_port": 10300,
            "capture_path": "/config/c300x/latest.capture.json",
            "wav_path": "/config/c300x/latest.raw.wav",
            "result_path": "/config/c300x/analysis/result.json",
            "language": "de",
            "expected_phrase": "open",
        }

        evaluate_schema = hass.services.schemas[(DOMAIN, SERVICE_EVALUATE_RING_ANALYSIS)]
        assert evaluate_schema(
            {
                "result_path": "/config/c300x/analysis/result.json",
                "decision_path": "/config/c300x/analysis/decision.json",
                "capture_path": "/config/c300x/latest.capture.json",
                "expected_phrase": "open",
                "unlock_on_match": "false",
                "lock_id": "default",
            }
        ) == {
            "result_path": "/config/c300x/analysis/result.json",
            "decision_path": "/config/c300x/analysis/decision.json",
            "capture_path": "/config/c300x/latest.capture.json",
            "expected_phrase": "open",
            "unlock_on_match": False,
            "lock_id": "default",
        }

    asyncio.run(_run())


def test_capture_doorbell_call_service_rejects_busy_rtsp_client(monkeypatch) -> None:  # noqa: ANN001
    async def _run() -> None:
        api = _FakeApi()
        api.doorbell_video_status = {"bridge": {"clients": 1}}
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={
                    "doorbell_video": {"supported": True},
                    "doorbell_call": {"supported": True},
                },
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])
        calls: list[dict[str, Any]] = []

        async def _capture(*args: Any, **kwargs: Any) -> None:
            calls.append({"args": args, "kwargs": kwargs})

        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", _capture)

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        try:
            await handler(types.SimpleNamespace(data={}))
        except SERVICE_VALIDATION_ERROR as err:
            assert getattr(err, "translation_key", None) == "ring_capture_busy"
        else:
            raise AssertionError("busy ring capture was not rejected")

        assert calls == []
        assert api.doorbell_video_status_calls == 1
        assert api.answer_doorbell_call_calls == []
        assert api.hangup_doorbell_call_calls == 0

    asyncio.run(_run())


def test_capture_doorbell_call_service_translates_status_failures(monkeypatch) -> None:  # noqa: ANN001
    async def _run() -> None:
        api = _FakeApi()
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={
                    "doorbell_video": {"supported": True},
                    "doorbell_call": {"supported": True},
                },
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])

        async def _status() -> dict[str, Any]:
            raise RuntimeError("status failed")

        async def _capture(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("capture should not start")

        api.async_doorbell_video_status = _status  # type: ignore[method-assign]
        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", _capture)

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        try:
            await handler(types.SimpleNamespace(data={}))
        except SERVICE_VALIDATION_ERROR as err:
            assert _translation_key(err) == "agent_command_failed"
        else:
            raise AssertionError("status failure was not translated")

        assert api.answer_doorbell_call_calls == []

    asyncio.run(_run())


def test_capture_doorbell_call_service_allows_shared_ring_preview(
    monkeypatch,
) -> None:  # noqa: ANN001
    async def _run() -> None:
        api = _FakeApi()
        api.doorbell_video_status = {
            "bridge": {
                "media_owner": "ring",
                "ring_call_active": True,
                "ring_media_active": True,
                "clients": 1,
                "max_clients": 2,
                "ring_preview_sharing": True,
            }
        }
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={
                    "doorbell_video": {"supported": True},
                    "doorbell_call": {"supported": True},
                },
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])
        calls: list[dict[str, Any]] = []

        async def _capture(*args: Any, **kwargs: Any) -> None:
            calls.append({"args": args, "kwargs": kwargs})

        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", _capture)

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        await handler(types.SimpleNamespace(data={}))

        assert len(calls) == 1
        assert api.doorbell_video_status_calls == 1
        assert api.answer_doorbell_call_calls == [True]
        assert api.hangup_doorbell_call_calls == 1

    asyncio.run(_run())


def test_capture_doorbell_call_service_video_only_keeps_ring_available(
    monkeypatch,
) -> None:  # noqa: ANN001
    async def _run() -> None:
        api = _FakeApi()
        api.doorbell_video_status = {
            "bridge": {
                "media_owner": "ring",
                "ring_call_active": True,
                "ring_media_active": True,
                "clients": 1,
                "max_clients": 2,
                "ring_preview_sharing": True,
            }
        }
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={
                    "doorbell_video": {"supported": True},
                    "doorbell_call": {"supported": True},
                },
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])
        calls: list[dict[str, Any]] = []

        async def _capture(*args: Any, **kwargs: Any) -> None:
            calls.append({"args": args, "kwargs": kwargs})

        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", _capture)

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        await handler(types.SimpleNamespace(data={"include_audio": False}))

        assert calls == [
            {
                "args": (hass, entry),
                "kwargs": {
                    "output_path": None,
                    "wav_output_dir": None,
                    "duration_seconds": 5,
                    "include_audio": False,
                    "announcement_path": None,
                },
            }
        ]
        assert api.doorbell_video_status_calls == 1
        assert api.answer_doorbell_call_calls == []
        assert api.hangup_doorbell_call_calls == 0

    asyncio.run(_run())


def test_capture_doorbell_call_service_answers_audio_capture_without_announcement(
    monkeypatch,
) -> None:  # noqa: ANN001
    async def _run() -> None:
        api = _FakeApi()
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={
                    "doorbell_video": {"supported": True},
                    "doorbell_call": {"supported": True},
                },
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])

        async def _capture(*_args: Any, **_kwargs: Any) -> None:
            return None

        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", _capture)

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        await handler(types.SimpleNamespace(data={}))

        assert api.doorbell_video_status_calls == 1
        assert api.answer_doorbell_call_calls == [True]
        assert api.hangup_doorbell_call_calls == 1

    asyncio.run(_run())


def test_capture_doorbell_call_service_answers_announcement_without_capture_audio(
    monkeypatch,
) -> None:  # noqa: ANN001
    async def _run() -> None:
        api = _FakeApi()
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={
                    "doorbell_video": {"supported": True},
                    "doorbell_call": {"supported": True},
                },
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])
        calls: list[dict[str, Any]] = []

        async def _capture(*args: Any, **kwargs: Any) -> None:
            calls.append({"args": args, "kwargs": kwargs})

        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", _capture)

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        await handler(
            types.SimpleNamespace(
                data={
                    "include_audio": False,
                    "announcement_path": "/media/c300x/announce.wav",
                }
            )
        )

        assert calls == [
            {
                "args": (hass, entry),
                "kwargs": {
                    "output_path": None,
                    "wav_output_dir": None,
                    "duration_seconds": 5,
                    "include_audio": False,
                    "announcement_path": "/media/c300x/announce.wav",
                },
            }
        ]
        assert api.answer_doorbell_call_calls == [True]
        assert api.hangup_doorbell_call_calls == 1

    asyncio.run(_run())


def test_capture_doorbell_call_preserves_capture_error_when_hangup_fails(
    monkeypatch,
) -> None:  # noqa: ANN001
    async def _run() -> None:
        api = _FakeApi()
        api.hangup_doorbell_call_error = RuntimeError("hangup failed")
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={
                    "doorbell_video": {"supported": True},
                    "doorbell_call": {"supported": True},
                },
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])
        capture_error = RuntimeError("capture failed")

        async def _capture(*_args: Any, **_kwargs: Any) -> None:
            raise capture_error

        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", _capture)

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        try:
            await handler(types.SimpleNamespace(data={}))
        except RuntimeError as err:
            assert err is capture_error
        else:
            raise AssertionError("capture failure was swallowed")

        assert api.hangup_doorbell_call_calls == 1

    asyncio.run(_run())


def test_capture_doorbell_call_translates_hangup_failure_after_successful_capture(
    monkeypatch,
) -> None:  # noqa: ANN001
    async def _run() -> None:
        api = _FakeApi()
        api.hangup_doorbell_call_error = RuntimeError("hangup failed")
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={
                    "doorbell_video": {"supported": True},
                    "doorbell_call": {"supported": True},
                },
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])

        async def _capture(*_args: Any, **_kwargs: Any) -> None:
            return None

        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", _capture)

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        try:
            await handler(types.SimpleNamespace(data={}))
        except SERVICE_VALIDATION_ERROR as err:
            assert _translation_key(err) == "agent_command_failed"
        else:
            raise AssertionError("hangup failure was not translated")

        assert api.hangup_doorbell_call_calls == 1

    asyncio.run(_run())


def test_start_home_call_service_calls_agent_api() -> None:
    async def _run() -> None:
        api = _FakeApi()
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={"home_call": {"supported": True}},
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_START_HOME_CALL)]
        await handler(types.SimpleNamespace(data={"duration_seconds": 30}))

        assert api.home_call_start_calls == [30]

    asyncio.run(_run())


def test_stop_home_call_service_calls_agent_api() -> None:
    async def _run() -> None:
        api = _FakeApi()
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={"home_call": {"supported": True}},
                api=api,
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_STOP_HOME_CALL)]
        await handler(types.SimpleNamespace(data={}))

        assert api.home_call_stop_calls == 1

    asyncio.run(_run())


def test_run_device_activation_service_calls_agent_api() -> None:
    async def _run() -> None:
        api = _FakeApi()
        entry = _FakeEntry(_FakeRuntimeData(api=api))
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_RUN_DEVICE_ACTIVATION)]
        await handler(types.SimpleNamespace(data={"activation_id": "scene_1"}))

        assert api.activation_calls == ["scene_1"]

    asyncio.run(_run())


def test_write_text_memo_service_calls_agent_api_and_refreshes_memos() -> None:
    async def _run() -> None:
        api = _FakeApi()
        entry = _FakeEntry(
            _FakeRuntimeData(
                api=api,
                capabilities={"memos": {"supported": True, "write_text": True}},
            )
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_WRITE_TEXT_MEMO)]
        await handler(types.SimpleNamespace(data={"text": "new memo", "read": True}))

        assert api.text_memo_calls == [{"text": "new memo", "read": True}]
        assert entry.runtime_data.memos["text_total"] == 1
        assert entry.runtime_data.memos_updated_at is not None

    asyncio.run(_run())


def _translation_key(err: Exception) -> str | None:
    return getattr(err, "translation_key", None)


def test_common_use_case_guards_accept_supported_capabilities() -> None:
    entry = _FakeEntry(
        _FakeRuntimeData(
            capabilities={
                "doorbell_video": {"supported": True},
                "doorbell_call": {"supported": True},
                "home_call": {"supported": True},
                "memos": {"supported": True, "write_text": True},
                "maintenance": {"supported": True, "reboot": True},
            },
            qml_patch_status={"patched": True},
        ),
        data={CONF_VIDEO_ENABLED: True, CONF_MAINTENANCE_TOKEN: "token"},
    )

    common_use_cases.ensure_doorbell_video_supported(entry)
    common_use_cases.ensure_doorbell_call_supported(entry)
    common_use_cases.ensure_home_call_supported(entry)
    common_use_cases.ensure_text_memo_write_supported(entry)
    common_use_cases.ensure_maintenance_action(entry, "reboot")


def test_common_use_case_guards_reject_missing_capabilities() -> None:
    entry = _FakeEntry(_FakeRuntimeData(capabilities={}), data={CONF_VIDEO_ENABLED: True})
    cases = [
        (
            common_use_cases.ensure_doorbell_video_supported,
            "doorbell_video_not_available",
        ),
        (
            common_use_cases.ensure_doorbell_call_supported,
            "doorbell_video_not_available",
        ),
        (common_use_cases.ensure_home_call_supported, "home_call_not_available"),
        (
            common_use_cases.ensure_text_memo_write_supported,
            "text_memo_write_not_supported",
        ),
    ]

    for guard, expected_key in cases:
        try:
            guard(entry)
        except SERVICE_VALIDATION_ERROR as err:
            assert _translation_key(err) == expected_key
        else:
            raise AssertionError(f"{expected_key} guard accepted missing capability")

    try:
        common_use_cases.ensure_maintenance_action(entry, "reboot")
    except SERVICE_VALIDATION_ERROR as err:
        assert _translation_key(err) == "maintenance_action_not_supported"
    else:
        raise AssertionError("maintenance guard accepted missing token/capability")


def test_common_use_case_guards_reject_disabled_video() -> None:
    entry = _FakeEntry(
        _FakeRuntimeData(
            capabilities={
                "doorbell_video": {"supported": True},
                "doorbell_call": {"supported": True},
                "home_call": {"supported": True},
            },
        ),
        data={CONF_VIDEO_ENABLED: False},
    )

    for guard, expected_key in [
        (
            common_use_cases.ensure_doorbell_video_supported,
            "doorbell_video_not_available",
        ),
        (
            common_use_cases.ensure_doorbell_call_supported,
            "doorbell_video_not_available",
        ),
        (common_use_cases.ensure_home_call_supported, "home_call_not_available"),
    ]:
        try:
            guard(entry)
        except SERVICE_VALIDATION_ERROR as err:
            assert _translation_key(err) == expected_key
        else:
            raise AssertionError(f"{expected_key} guard accepted disabled video")


def test_common_agent_command_failures_are_translated() -> None:
    async def _failing_command() -> None:
        raise RuntimeError("agent failed")

    async def _run() -> None:
        try:
            await common_use_cases.raise_agent_command_failed(_failing_command())
        except SERVICE_VALIDATION_ERROR as err:
            assert _translation_key(err) == "agent_command_failed"
        else:
            raise AssertionError("agent failure was not translated")

    asyncio.run(_run())


def test_common_gui_patch_refresh_is_required_when_inactive(monkeypatch) -> None:  # noqa: ANN001
    async def _run() -> None:
        entry = _FakeEntry(_FakeRuntimeData(qml_patch_status={"patched": False}))
        refreshes = 0

        async def _refresh(entry_arg: Any) -> None:
            nonlocal refreshes
            assert entry_arg is entry
            refreshes += 1
            entry.runtime_data.qml_patch_status = {"patched": True}

        monkeypatch.setattr(common_use_cases, "async_refresh_qml_patch_status", _refresh)

        await common_use_cases.async_ensure_gui_function_patch(entry)

        assert refreshes == 1

    asyncio.run(_run())


def test_common_gui_patch_refresh_failures_are_translated(monkeypatch) -> None:  # noqa: ANN001
    async def _run() -> None:
        entry = _FakeEntry(_FakeRuntimeData(qml_patch_status={"patched": False}))

        async def _refresh(_entry: Any) -> None:
            raise RuntimeError("agent unavailable")

        monkeypatch.setattr(common_use_cases, "async_refresh_qml_patch_status", _refresh)

        try:
            await common_use_cases.async_ensure_gui_function_patch(entry)
        except SERVICE_VALIDATION_ERROR as err:
            assert _translation_key(err) == "agent_command_failed"
        else:
            raise AssertionError("failed GUI patch refresh was not translated")

    asyncio.run(_run())


def test_common_gui_patch_still_inactive_after_refresh_is_rejected(monkeypatch) -> None:  # noqa: ANN001
    async def _run() -> None:
        entry = _FakeEntry(_FakeRuntimeData(qml_patch_status={"patched": False}))

        async def _refresh(_entry: Any) -> None:
            entry.runtime_data.qml_patch_status = {"patched": False}

        monkeypatch.setattr(common_use_cases, "async_refresh_qml_patch_status", _refresh)

        try:
            await common_use_cases.async_ensure_gui_function_patch(entry)
        except SERVICE_VALIDATION_ERROR as err:
            assert _translation_key(err) == "gui_function_patch_required"
        else:
            raise AssertionError("inactive GUI patch was accepted after refresh")

    asyncio.run(_run())


def test_common_latest_item_id_uses_cache_then_refreshes() -> None:
    async def _run() -> None:
        entry = _FakeEntry(_FakeRuntimeData())
        entry.runtime_data.cached_payload = {"latest": "cached-id"}
        refreshes = 0

        async def _refresh() -> dict[str, Any]:
            nonlocal refreshes
            refreshes += 1
            return {"latest": "fresh-id"}

        def latest(payload: dict[str, Any]) -> str | None:
            return payload.get("latest")

        assert (
            await common_use_cases.latest_item_id_for_entry(
                entry,
                cache_attr="cached_payload",
                refresh=_refresh,
                latest=latest,
                unavailable_error="missing_item",
            )
            == "cached-id"
        )
        assert refreshes == 0

        entry.runtime_data.cached_payload = {}
        assert (
            await common_use_cases.latest_item_id_for_entry(
                entry,
                cache_attr="cached_payload",
                refresh=_refresh,
                latest=latest,
                unavailable_error="missing_item",
            )
            == "fresh-id"
        )
        assert refreshes == 1

    asyncio.run(_run())


def test_common_latest_item_id_translates_refresh_and_empty_results() -> None:
    async def _run() -> None:
        entry = _FakeEntry(_FakeRuntimeData())

        async def _failing_refresh() -> dict[str, Any]:
            raise RuntimeError("agent failed")

        try:
            await common_use_cases.latest_item_id_for_entry(
                entry,
                cache_attr="missing_cache",
                refresh=_failing_refresh,
                latest=lambda payload: payload.get("latest"),
                unavailable_error="missing_item",
            )
        except SERVICE_VALIDATION_ERROR as err:
            assert _translation_key(err) == "agent_command_failed"
        else:
            raise AssertionError("refresh failure was not translated")

        async def _empty_refresh() -> dict[str, Any]:
            return {}

        try:
            await common_use_cases.latest_item_id_for_entry(
                entry,
                cache_attr="missing_cache",
                refresh=_empty_refresh,
                latest=lambda payload: payload.get("latest"),
                unavailable_error="missing_item",
            )
        except SERVICE_VALIDATION_ERROR as err:
            assert _translation_key(err) == "missing_item"
        else:
            raise AssertionError("missing item was accepted")

    asyncio.run(_run())


def test_common_refresh_after_message_mutation_notifies_listeners(monkeypatch) -> None:  # noqa: ANN001
    dispatcher_calls: list[tuple[Any, ...]] = []
    diagnostics_refreshes: list[str] = []

    monkeypatch.setattr(
        common_use_cases,
        "async_dispatcher_send",
        lambda *args: dispatcher_calls.append(args),
    )

    async def _refresh_diagnostics(_hass: Any, entry: Any) -> None:
        diagnostics_refreshes.append(entry.entry_id)

    monkeypatch.setattr(
        common_use_cases,
        "async_refresh_agent_diagnostics",
        _refresh_diagnostics,
    )

    async def _run() -> None:
        hass = _FakeHass([])
        entry = _FakeEntry(_FakeRuntimeData())
        refreshes = 0

        async def _refresh() -> dict[str, Any]:
            nonlocal refreshes
            refreshes += 1
            return {"ok": True}

        await common_use_cases.async_refresh_after_message_mutation(
            hass,  # type: ignore[arg-type]
            entry,
            refresh=_refresh,
            signal="signal-name",
        )

        assert refreshes == 1

    asyncio.run(_run())

    assert dispatcher_calls == [(dispatcher_calls[0][0], "signal-name", "entry-id")]
    assert diagnostics_refreshes == ["entry-id"]


def test_common_refresh_after_message_mutation_translates_refresh_failures() -> None:
    async def _run() -> None:
        hass = _FakeHass([])
        entry = _FakeEntry(_FakeRuntimeData())

        async def _refresh() -> dict[str, Any]:
            raise RuntimeError("agent failed")

        try:
            await common_use_cases.async_refresh_after_message_mutation(
                hass,  # type: ignore[arg-type]
                entry,
                refresh=_refresh,
                signal="signal-name",
            )
        except SERVICE_VALIDATION_ERROR as err:
            assert _translation_key(err) == "agent_command_failed"
        else:
            raise AssertionError("refresh failure was not translated")

    asyncio.run(_run())


def test_common_play_media_calls_home_assistant_media_player() -> None:
    async def _run() -> None:
        hass = _FakeHass([])

        await common_use_cases.async_play_media(
            hass,  # type: ignore[arg-type]
            "media_player.room",
            media_content_id="media-source://c300x/latest",
            media_content_type="music",
        )

        assert hass.services.calls == [
            (
                "media_player",
                "play_media",
                {
                    "entity_id": "media_player.room",
                    "media_content_id": "media-source://c300x/latest",
                    "media_content_type": "music",
                },
                True,
            )
        ]

    asyncio.run(_run())
