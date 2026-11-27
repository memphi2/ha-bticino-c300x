# ruff: noqa: E402

from __future__ import annotations

import asyncio
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import yaml
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError

pytestmark = pytest.mark.usefixtures("entity_ha_boundary")

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
from custom_components.bticino_c300x.data import C300XRuntimeResources
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


@dataclass
class _FakeRuntimeData:
    capabilities: dict[str, Any] = field(default_factory=dict)
    qml_patch_status: dict[str, Any] = field(default_factory=dict)
    api: Any = None
    resources: C300XRuntimeResources = field(default_factory=C300XRuntimeResources)
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
    state: ConfigEntryState = ConfigEntryState.LOADED
    domain: str = DOMAIN


class _FakeConfigEntries:
    def __init__(self, entries: list[_FakeEntry]) -> None:
        self.entries = entries

    def async_entries(self, domain: str) -> list[_FakeEntry]:
        return self.entries if domain == DOMAIN else []

    def async_get_entry(self, entry_id: str) -> _FakeEntry | None:
        return next((entry for entry in self.entries if entry.entry_id == entry_id), None)

    def async_loaded_entries(self, domain: str) -> list[_FakeEntry]:
        return [
            entry for entry in self.async_entries(domain)
            if getattr(entry, "state", ConfigEntryState.LOADED) is ConfigEntryState.LOADED
        ]


class _FakeServices:
    def __init__(self) -> None:
        self.registered: set[tuple[str, str]] = set()
        self.handlers: dict[tuple[str, str], Any] = {}
        self.schemas: dict[tuple[str, str], Any] = {}
        self.responses: dict[tuple[str, str], Any] = {}
        self.calls: list[tuple[str, str, dict[str, Any], bool]] = []

    def async_register(self, domain: str, service: str, *args: Any, **_kwargs: Any) -> None:
        self.registered.add((domain, service))
        if args:
            self.handlers[(domain, service)] = args[0]
        if "schema" in _kwargs:
            self.schemas[(domain, service)] = _kwargs["schema"]
        self.responses[(domain, service)] = _kwargs.get("supports_response")

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
        context: Any = None,
    ) -> None:
        self.calls.append((domain, service, data, blocking))


class _FakeHass:
    def __init__(self, entries: list[_FakeEntry]) -> None:
        self.data: dict[str, Any] = {}
        self.config_entries = _FakeConfigEntries(entries)
        self.services = _FakeServices()
        self.bus = types.SimpleNamespace(async_listen=lambda *_: lambda: None)


class _FakeApi:
    def __init__(self) -> None:
        self.activate_video_calls: list[bool] = []
        self.activate_video_units: list[str | None] = []
        self.call_ids: list[tuple[str, str | None]] = []
        self.stop_video_calls = 0
        self.doorbell_video_status: dict[str, Any] = {
            "media_owner": "idle",
            "bridge": {"media_owner": "idle", "clients": 0},
        }
        self.doorbell_video_status_calls = 0
        self.answer_doorbell_call_calls: list[bool] = []
        self.hangup_doorbell_call_calls = 0
        self.hangup_doorbell_call_error: Exception | None = None
        self.doorstation_audio_level_calls: list[tuple[int, int]] = []
        self.capture_doorbell_call_calls = 0
        self.activation_calls: list[str] = []
        self.home_call_start_calls: list[int | None] = []
        self.home_call_stop_calls = 0
        self.text_memo_calls: list[dict[str, Any]] = []
        self.reboot_calls = 0
        self.reload_gui_calls = 0
        self.deleted_video_message_ids: list[str] = []
        self.deleted_memo_ids: list[str] = []

    async def async_activate_doorbell_video(self, audio: bool = True, unit: str | None = None) -> dict[str, Any]:
        self.activate_video_calls.append(audio)
        self.activate_video_units.append(unit)
        return {"ok": True, "audio": audio}

    async def async_stop_doorbell_video(self) -> dict[str, Any]:
        self.stop_video_calls += 1
        return {"ok": True}

    async def async_doorbell_video_status(self) -> dict[str, Any]:
        self.doorbell_video_status_calls += 1
        return self.doorbell_video_status

    async def async_answer_doorbell_call(self, call_id: str | None = None, *, unit: str | None = None) -> dict[str, Any]:
        self.answer_doorbell_call_calls.append(True)
        self.call_ids.append(("answer", call_id))
        bridge = dict(self.doorbell_video_status.get("bridge", {}))
        bridge.update(
            {
                "media_owner": "ring",
                "ring_call_active": True,
                "ring_media_active": True,
                "ring_audio_active": True,
                "ring_answer_requested": False,
                "ring_answered": True,
                "ring_hangup_requested": False,
                "unanswered_ring_call": False,
            }
        )
        self.doorbell_video_status = {
            **self.doorbell_video_status,
            "last_media_started_at": "2026-11-14T12:00:00Z",
            "available": True,
            "window_available": True,
            "media_owner": "ring",
            "bridge": bridge,
        }
        return {"ok": True, "audio": True}

    async def async_set_doorstation_audio_level(
        self,
        door_level_db: int,
        fine_gain_db: int,
    ) -> dict[str, Any]:
        self.doorstation_audio_level_calls.append((door_level_db, fine_gain_db))
        return {"ok": True}

    async def async_hangup_doorbell_call(self, call_id: str | None = None, *, unit: str | None = None) -> dict[str, Any]:
        self.hangup_doorbell_call_calls += 1
        self.call_ids.append(("hangup", call_id))
        if self.hangup_doorbell_call_error is not None:
            raise self.hangup_doorbell_call_error
        bridge = dict(self.doorbell_video_status.get("bridge", {}))
        bridge["ring_hangup_requested"] = True
        self.doorbell_video_status = {**self.doorbell_video_status, "bridge": bridge}
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
            "camera_picture": {"control": "brightness", "value": 50},
            "show_display_notification": {"notification_id": "reminder", "title": "Title", "message": "Text"},
            "dismiss_display_notification": {"notification_id": "reminder"},
            SERVICE_RUN_ACTION: {"device_id": "station-device", "action_id": "door_open"},
            SERVICE_ALARM_COMMAND: {
                "command": "disarm",
                "code": "1234",
                "force": "true",
            },
            SERVICE_ACTIVATE_DOORBELL_VIDEO: {"audio": "false"},
            SERVICE_ANSWER_CALL: {"device_id": ["unit-device"], "call_id": "0badc0de-12"},
            SERVICE_HANGUP_CALL: {"entity_id": "camera.door"},
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
            },
            SERVICE_START_HOME_CALL: {"duration_seconds": "0"},
            SERVICE_STOP_HOME_CALL: {"device_id": "station-device"},
            SERVICE_PLAY_LATEST_VIDEO_MESSAGE: {
                "media_player_entity_id": "media_player.living_room",
            },
            SERVICE_PLAY_LATEST_VOICE_MEMO: {
                "media_player_entity_id": "media_player.living_room",
            },
            SERVICE_WRITE_TEXT_MEMO: {"text": "hello", "read": "yes"},
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


def _services_yaml() -> dict[str, Any]:
    return yaml.safe_load(
        (ROOT / "custom_components" / "bticino_c300x" / "services.yaml").read_text(
            encoding="utf-8"
        )
    )


class _Device:
    """A device registry entry: one config entry, as HA 2026.10 has it."""

    def __init__(self, identifiers: set[tuple[str, str]], config_entry_id: str) -> None:
        self.identifiers = identifiers
        self.config_entry_id = config_entry_id

    @property
    def config_entries(self) -> set[str]:
        # Deprecated in HA (warning, removed in 2027.10): reading it is a bug.
        raise AssertionError("DeviceEntry.config_entries is deprecated")


def _targets(monkeypatch: pytest.MonkeyPatch, entities: dict[str, Any] | None = None) -> None:
    """Two stations, "one" with an outdoor unit device, as HA's registries see them."""

    from custom_components.bticino_c300x import service_target

    devices = {
        "station-one": _Device({(DOMAIN, "c300x-000000000001")}, "one"),
        "unit-one-21": _Device({(DOMAIN, "c300x-000000000001:unit:21")}, "one"),
        "station-two": _Device({(DOMAIN, "c300x-000000000002")}, "two"),
        "foreign": _Device({("other", "x")}, "foreign-entry"),
    }
    monkeypatch.setattr(service_target.dr, "async_get", lambda _hass: types.SimpleNamespace(async_get=devices.get))
    monkeypatch.setattr(
        service_target.er, "async_get", lambda _hass: types.SimpleNamespace(async_get=(entities or {}).get),
    )


def test_services_target_a_station_or_outdoor_unit_device_or_entity(monkeypatch) -> None:  # noqa: ANN001
    entities = {
        "camera.two": types.SimpleNamespace(platform=DOMAIN, device_id="station-two"),
        "light.kitchen": types.SimpleNamespace(platform="hue", device_id="foreign"),
    }
    _targets(monkeypatch, entities)
    ran: list[str] = []

    async def _action(_hass: Any, entry: Any, *_args: Any, **_kwargs: Any) -> None:
        ran.append(entry.entry_id)

    monkeypatch.setattr(device_action_use_cases, "async_execute_action", _action)

    async def _run() -> None:
        api_one, api_two = _FakeApi(), _FakeApi()  # noqa: F841
        hass = _FakeHass([
            _FakeEntry(_FakeRuntimeData(api=api_one), entry_id="one"),
            _FakeEntry(_FakeRuntimeData(api=api_two), entry_id="two"),
        ])
        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_RUN_ACTION)]

        async def stop(call: Any) -> None:
            await handler(types.SimpleNamespace(data={**call.data, "action_id": "light"}))

        for data, key in (
            ({}, "entry_id_required"),
            ({"device_id": ["station-one", "station-two"]}, "entry_id_required"),
            ({"device_id": "missing"}, "unknown_entry"),
            ({"device_id": "foreign"}, "unknown_entry"),
            ({"entity_id": "light.kitchen"}, "unknown_entry"),
            ({"entity_id": "camera.missing"}, "unknown_entry"),
            # The target picker offers these too; the error says what to pick.
            ({"area_id": "porch"}, "target_unsupported"),
            ({"floor_id": ["ground"]}, "target_unsupported"),
            ({"label_id": "doors"}, "target_unsupported"),
            ({"entity_id": "all"}, "target_unsupported"),
            ({"device_id": "all"}, "target_unsupported"),
        ):
            with pytest.raises(SERVICE_VALIDATION_ERROR) as err:
                await stop(types.SimpleNamespace(data=data))
            assert err.value.translation_key == key, data
        assert ran == []
        # The service schema lets them through to that error instead of a
        # generic "extra keys not allowed".
        from custom_components.bticino_c300x.schema_compat import vol
        from custom_components.bticino_c300x.service_target import TARGET_FIELDS

        vol.Schema(TARGET_FIELDS)({"area_id": "porch", "floor_id": ["ground"], "label_id": "doors"})

        await stop(types.SimpleNamespace(data={"device_id": "station-two"}))
        await stop(types.SimpleNamespace(data={"entity_id": ["camera.two"]}))
        await stop(types.SimpleNamespace(data={"device_id": ["unit-one-21"]}))
        assert ran == ["two", "two", "one"]

    asyncio.run(_run())


def test_a_unit_target_names_the_unit_and_a_station_target_does_not(monkeypatch) -> None:  # noqa: ANN001
    _targets(monkeypatch)

    async def _run() -> None:
        api = _FakeApi()
        hass = _FakeHass([_FakeEntry(
            _FakeRuntimeData(api=api, capabilities={"doorbell_video": {"supported": True}}),
            entry_id="one", data={CONF_VIDEO_ENABLED: True},
        )])
        await async_setup_services(hass)  # type: ignore[arg-type]
        activate = hass.services.handlers[(DOMAIN, SERVICE_ACTIVATE_DOORBELL_VIDEO)]
        await activate(types.SimpleNamespace(data={"device_id": "unit-one-21", "audio": False}))
        await activate(types.SimpleNamespace(data={"device_id": "station-one", "audio": False}))
        await activate(types.SimpleNamespace(data={"audio": False}))
        assert api.activate_video_units == ["21", None, None]

    asyncio.run(_run())


@pytest.mark.parametrize(
    "state", [ConfigEntryState.NOT_LOADED, ConfigEntryState.SETUP_RETRY, ConfigEntryState.SETUP_ERROR]
)
def test_service_target_ignores_entries_that_are_not_loaded(monkeypatch, state: ConfigEntryState) -> None:  # noqa: ANN001
    """Ignored, disabled or failed entries do not make the call ambiguous."""

    _targets(monkeypatch)
    ran: list[str] = []

    async def _action(_hass: Any, entry: Any, *_args: Any, **_kwargs: Any) -> None:
        ran.append(entry.entry_id)

    monkeypatch.setattr(device_action_use_cases, "async_execute_action", _action)

    async def _run() -> None:
        api = _FakeApi()
        loaded = _FakeEntry(_FakeRuntimeData(api=api), entry_id="one")
        other = _FakeEntry(None, entry_id="two", state=state)  # type: ignore[arg-type]
        hass = _FakeHass([other, loaded])
        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_RUN_ACTION)]

        async def stop(call: Any) -> None:
            await handler(types.SimpleNamespace(data={**call.data, "action_id": "light"}))

        await stop(types.SimpleNamespace(data={}))
        assert ran == ["one"]
        with pytest.raises(SERVICE_VALIDATION_ERROR) as err:
            await stop(types.SimpleNamespace(data={"device_id": "station-two"}))
        assert err.value.translation_key == "entry_not_loaded"
        hass.config_entries.entries.remove(loaded)
        with pytest.raises(SERVICE_VALIDATION_ERROR) as err:
            await stop(types.SimpleNamespace(data={}))
        assert err.value.translation_key == "entry_not_loaded"

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
        assert (DOMAIN, SERVICE_ANSWER_CALL) in hass.services.registered

    asyncio.run(_run())


def test_base_executor_services_call_expected_helpers(monkeypatch) -> None:  # noqa: ANN001
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def _action(*args: Any, **kwargs: Any) -> None:
        calls.append(("action", args, kwargs))

    async def _alarm(*args: Any, **kwargs: Any) -> dict[str, bool]:
        calls.append(("alarm", args, kwargs))
        return {"ok": True}

    monkeypatch.setattr(device_action_use_cases, "async_execute_action", _action)
    monkeypatch.setattr(device_action_use_cases, "async_execute_alarm_command", _alarm)

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

    asyncio.run(_run())

    assert [call[0] for call in calls] == ["action", "alarm"]
    assert calls[0][1][2] == "entry_light"
    assert calls[1][1][2:] == ("disarm", "1234")
    assert calls[0][2] == {"blocking": True, "context": None}
    assert calls[1][2] == {"force": True, "context": None}


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
    monkeypatch.setattr(ring_analysis_use_cases, "async_mark_ring_capture_used", AsyncMock(return_value=True))
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
    # Without a unit target the agent opens the calling unit.
    assert calls[2][1]["args"][2:] == ("current", None)


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


def test_evaluate_ring_analysis_reserves_capture_before_unlock(monkeypatch) -> None:  # noqa: ANN001
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _evaluate(_hass: Any, **kwargs: Any) -> Any:
        calls.append(("evaluate", kwargs))
        return types.SimpleNamespace(matched=True, capture_id="capture-1")

    async def _unlock(*args: Any, **kwargs: Any) -> None:
        calls.append(("unlock", {"args": args, **kwargs}))

    async def _mark(_hass: Any, capture_id: str | None) -> bool:
        calls.append(("mark", {"capture_id": capture_id}))
        return True

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
    assert calls[1] == ("mark", {"capture_id": "capture-1"})
    assert calls[2][0] == "unlock"


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
        handler = hass.services.handlers[(DOMAIN, SERVICE_ANSWER_CALL)]
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
        handler = hass.services.handlers[(DOMAIN, SERVICE_HANGUP_CALL)]
        await handler(types.SimpleNamespace(data={}))

        assert api.hangup_doorbell_call_calls == 1

    asyncio.run(_run())


def test_hangup_doorbell_call_service_prepares_stop_before_agent_hangup() -> None:
    async def _run() -> None:
        calls: list[str] = []

        class _RecordingApi(_FakeApi):
            async def async_hangup_doorbell_call(
                self, call_id: str | None = None, *, unit: str | None = None,
            ) -> dict[str, Any]:
                calls.append("agent_hangup")
                return await super().async_hangup_doorbell_call(call_id, unit=unit)

        api = _RecordingApi()

        async def _prepare_stop() -> None:
            calls.append("prepare_stop")

        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={"doorbell_call": {"supported": True}},
                api=api,
                resources=C300XRuntimeResources(
                    prepare_doorbell_video_stop=_prepare_stop
                ),
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_HANGUP_CALL)]
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

        captured = {"capture_id": "unique-run", "metadata_path": "/config/c300x/captures/unique-run/latest.capture.json"}

        async def _capture(*args: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append({"args": args, "kwargs": kwargs})
            return captured

        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", _capture)

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        result = await handler(
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
                    "capture_mode": "ring",
                    "output_path": "/media/c300x/test.mp4",
                    "wav_output_dir": "/config/c300x",
                    "duration_seconds": 3,
                    "include_audio": True,
                    "announcement_path": "/media/c300x/announce.wav",
                },
            }
        ]
        assert result == captured
        assert hass.services.responses[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)].value == "optional"
        assert api.capture_doorbell_call_calls == 0
        assert api.doorbell_video_status_calls == 5
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
        assert api.doorbell_video_status_calls == 5
        assert api.answer_doorbell_call_calls == [True]
        assert api.hangup_doorbell_call_calls == 1

    asyncio.run(_run())


def test_ring_capture_and_analysis_service_schemas_accept_documented_fields() -> None:
    async def _run() -> None:
        entry = _FakeEntry(_FakeRuntimeData(api=_FakeApi()))
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]

        capture_schema = hass.services.schemas[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        assert capture_schema({})["capture_mode"] == "ring"
        assert capture_schema({"capture_mode": "on_demand"})["capture_mode"] == "on_demand"
        with pytest.raises(service_module.vol.Invalid):
            capture_schema({"capture_mode": "auto"})
        assert capture_schema(
            {
                "output_path": "/media/c300x/test.mp4",
                "duration_seconds": 3,
                "include_audio": "true",
                "wav_output_dir": "/config/c300x",
                "announcement_path": "/config/www/c300x/announce.wav",
            }
        ) == {
            "capture_mode": "ring",
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
            }
        ) == {
            "result_path": "/config/c300x/analysis/result.json",
            "decision_path": "/config/c300x/analysis/decision.json",
            "capture_path": "/config/c300x/latest.capture.json",
            "expected_phrase": "open",
            "unlock_on_match": False,
        }

    asyncio.run(_run())


@pytest.mark.parametrize("include_audio", [False, True])
def test_capture_service_routes_on_demand_without_ring_capability(monkeypatch, include_audio):
    async def run():
        api = _FakeApi()
        entry = _FakeEntry(
            _FakeRuntimeData(api=api, capabilities={"doorbell_video": {"supported": True}}),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])
        capture = AsyncMock(return_value={"capture_id": "on-demand", "capture_mode": "on_demand"})
        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", capture)
        await async_setup_services(hass)
        schema = hass.services.schemas[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        result = await handler(types.SimpleNamespace(data=schema({"capture_mode": "on_demand", "include_audio": include_audio})))
        assert result["capture_mode"] == "on_demand"
        assert capture.await_args.kwargs["capture_mode"] == "on_demand"
        assert api.activate_video_calls == [include_audio]
        assert api.answer_doorbell_call_calls == []
        assert api.hangup_doorbell_call_calls == 0
        assert api.stop_video_calls == 0

    asyncio.run(run())


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


def test_capture_doorbell_call_service_rejects_concurrent_second_capture(monkeypatch) -> None:  # noqa: ANN001
    """Two overlapping capture calls (e.g. duplicate automation triggers) must not both start."""

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
            await asyncio.sleep(0.02)

        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", _capture)

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]

        results = await asyncio.gather(
            handler(types.SimpleNamespace(data={})),
            handler(types.SimpleNamespace(data={})),
            return_exceptions=True,
        )

        errors = [result for result in results if isinstance(result, BaseException)]
        assert len(errors) == 1
        assert getattr(errors[0], "translation_key", None) == "ring_capture_busy"
        assert len(calls) == 1

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
        except HomeAssistantError as err:
            assert not isinstance(err, SERVICE_VALIDATION_ERROR)
            assert _translation_key(err) == "agent_command_failed"
        else:
            raise AssertionError("status failure was not translated")

        assert api.answer_doorbell_call_calls == []

    asyncio.run(_run())


def test_capture_doorbell_call_service_refuses_audio_while_preview_is_watched(
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
        try:
            await handler(types.SimpleNamespace(data={}))
        except SERVICE_VALIDATION_ERROR as err:
            assert getattr(err, "translation_key", None) == "ring_capture_busy"
        else:
            raise AssertionError("the ring was answered under a watching client")

        assert calls == []
        assert api.answer_doorbell_call_calls == []
        assert api.hangup_doorbell_call_calls == 0

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
                    "capture_mode": "ring",
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

        assert api.doorbell_video_status_calls == 5
        assert api.answer_doorbell_call_calls == [True]
        assert api.hangup_doorbell_call_calls == 1

    asyncio.run(_run())


def test_capture_doorbell_call_service_waits_for_answered_ring_before_capture(
    monkeypatch,
) -> None:  # noqa: ANN001
    async def _run() -> None:
        api = _FakeApi()
        statuses = [
            {"bridge": {"media_owner": "idle", "clients": 0}},
            {"bridge": {"media_owner": "ring", "ring_call_active": True}},
            # Final admission check after gain synchronization, before answer.
            {"bridge": {"media_owner": "ring", "ring_call_active": True}},
            {
                "bridge": {
                    "media_owner": "ring",
                    "ring_call_active": True,
                    "ring_media_active": True,
                    "ring_answer_requested": True,
                }
            },
            {
                "bridge": {
                    "media_owner": "ring",
                    "ring_call_active": True,
                    "ring_media_active": True,
                    "ring_audio_active": True,
                    "ring_answered": True,
                    "clients": 0,
                }
            },
        ]
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
        calls: list[str] = []

        async def _status() -> dict[str, Any]:
            if statuses:
                api.doorbell_video_status = {**statuses.pop(0), "last_media_started_at": "2026-11-14T12:00:00Z"}
            return api.doorbell_video_status

        async def _answer() -> dict[str, Any]:
            calls.append("answer")
            api.answer_doorbell_call_calls.append(True)
            return {"ok": True, "audio": True}

        async def _hangup() -> dict[str, Any]:
            calls.append("hangup")
            api.hangup_doorbell_call_calls += 1
            return {"ok": True}

        async def _capture(*_args: Any, **_kwargs: Any) -> None:
            assert statuses == []
            calls.append("capture")

        api.async_doorbell_video_status = _status  # type: ignore[method-assign]
        api.async_answer_doorbell_call = _answer  # type: ignore[method-assign]
        api.async_hangup_doorbell_call = _hangup  # type: ignore[method-assign]
        monkeypatch.setattr(
            ring_capture_use_cases,
            "_RING_CAPTURE_ANSWER_READY_INTERVAL_SECONDS",
            0,
        )
        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", _capture)

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        await handler(types.SimpleNamespace(data={}))

        assert calls == ["answer", "capture", "hangup"]

    asyncio.run(_run())


def test_capture_doorbell_call_service_tolerates_transient_status_gap_after_answer(
    monkeypatch,
) -> None:  # noqa: ANN001
    async def _run() -> None:
        api = _FakeApi()
        statuses = [
            {"bridge": {"media_owner": "idle", "clients": 0}},
            {"bridge": {"media_owner": "idle", "clients": 0}},
            # Final pre-answer read, then a transient idle read after answer.
            {"bridge": {"media_owner": "idle", "clients": 0}},
            {"bridge": {"media_owner": "idle", "clients": 0}},
            {
                "bridge": {
                    "media_owner": "ring",
                    "ring_call_active": True,
                    "ring_media_active": True,
                    "ring_answer_requested": True,
                }
            },
            {
                "bridge": {
                    "media_owner": "ring",
                    "ring_call_active": True,
                    "ring_media_active": True,
                    "ring_audio_active": True,
                    "ring_answered": True,
                    "clients": 0,
                }
            },
        ]
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
        calls: list[str] = []

        async def _status() -> dict[str, Any]:
            if statuses:
                api.doorbell_video_status = {**statuses.pop(0), "last_media_started_at": "2026-11-14T12:00:00Z"}
            return api.doorbell_video_status

        async def _answer() -> dict[str, Any]:
            calls.append("answer")
            api.answer_doorbell_call_calls.append(True)
            return {"ok": True, "audio": True}

        async def _hangup() -> dict[str, Any]:
            calls.append("hangup")
            api.hangup_doorbell_call_calls += 1
            return {"ok": True}

        async def _capture(*_args: Any, **_kwargs: Any) -> None:
            assert statuses == []
            calls.append("capture")

        api.async_doorbell_video_status = _status  # type: ignore[method-assign]
        api.async_answer_doorbell_call = _answer  # type: ignore[method-assign]
        api.async_hangup_doorbell_call = _hangup  # type: ignore[method-assign]
        monkeypatch.setattr(
            ring_capture_use_cases,
            "_RING_CAPTURE_ANSWER_READY_INTERVAL_SECONDS",
            0,
        )
        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", _capture)

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        await handler(types.SimpleNamespace(data={}))

        assert calls == ["answer", "capture", "hangup"]
        assert api.answer_doorbell_call_calls == [True]
        assert api.hangup_doorbell_call_calls == 1

    asyncio.run(_run())


def test_ring_capture_answer_wait_reads_video_status_bridge_fields() -> None:
    assert ring_capture_use_cases._ring_answer_media_ready(
        {"bridge": {"ring_answered": True}}
    )
    assert ring_capture_use_cases._ring_answer_media_ready(
        {"bridge": {"ring_audio_active": True}}
    )
    assert not ring_capture_use_cases._ring_answer_media_ready(
        {"answered": True, "audio_active": True}
    )
    assert not ring_capture_use_cases._ring_call_still_active({"active": True})


def test_capture_doorbell_call_service_uses_ring_hangup_prepare(
    monkeypatch,
) -> None:  # noqa: ANN001
    async def _run() -> None:
        calls: list[str] = []

        class _OrderedApi(_FakeApi):
            async def async_answer_doorbell_call(self) -> dict[str, Any]:
                calls.append("answer")
                return await super().async_answer_doorbell_call()

            async def async_hangup_doorbell_call(self) -> dict[str, Any]:
                calls.append("hangup")
                return await super().async_hangup_doorbell_call()

        api = _OrderedApi()

        async def _prepare_stop() -> None:
            calls.append("prepare")

        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={
                    "doorbell_video": {"supported": True},
                    "doorbell_call": {"supported": True},
                },
                api=api,
                resources=C300XRuntimeResources(
                    prepare_doorbell_video_stop=_prepare_stop
                ),
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])

        async def _capture(*_args: Any, **_kwargs: Any) -> None:
            calls.append("capture")

        monkeypatch.setattr(ring_capture_use_cases, "async_capture_doorbell_ring_call", _capture)

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        await handler(types.SimpleNamespace(data={}))

        assert calls == ["answer", "capture", "prepare", "hangup"]

    asyncio.run(_run())


def test_capture_doorbell_call_service_does_not_hang_up_unconfirmed_call(
    monkeypatch,
) -> None:  # noqa: ANN001
    async def _run() -> None:
        calls: list[str] = []

        class _OrderedApi(_FakeApi):
            async def async_answer_doorbell_call(self) -> dict[str, Any]:
                calls.append("answer")
                self.answer_doorbell_call_calls.append(True)
                return {"ok": True, "audio": True}

            async def async_hangup_doorbell_call(self) -> dict[str, Any]:
                calls.append("hangup")
                self.hangup_doorbell_call_calls += 1
                return {"ok": True}

        api = _OrderedApi()
        statuses = [
            {"bridge": {"media_owner": "idle", "clients": 0}},
            {
                "bridge": {
                    "media_owner": "ring",
                    "ring_call_active": True,
                    "ring_media_active": True,
                    "ring_answer_requested": False,
                }
            },
        ]

        async def _status() -> dict[str, Any]:
            api.doorbell_video_status_calls += 1
            if statuses:
                return statuses.pop(0)
            return {"bridge": {"media_owner": "idle"}}

        async def _prepare_stop() -> None:
            calls.append("prepare")

        async def _capture(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("capture must not start before answered media")

        api.async_doorbell_video_status = _status  # type: ignore[method-assign]
        entry = _FakeEntry(
            _FakeRuntimeData(
                capabilities={
                    "doorbell_video": {"supported": True},
                    "doorbell_call": {"supported": True},
                },
                api=api,
                resources=C300XRuntimeResources(
                    prepare_doorbell_video_stop=_prepare_stop
                ),
            ),
            data={CONF_VIDEO_ENABLED: True},
        )
        hass = _FakeHass([entry])
        monkeypatch.setattr(
            ring_capture_use_cases,
            "_RING_CAPTURE_ANSWER_READY_INTERVAL_SECONDS",
            0,
        )
        monkeypatch.setattr(
            ring_capture_use_cases,
            "async_capture_doorbell_ring_call",
            _capture,
        )

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_CAPTURE_DOORBELL_CALL)]
        try:
            await handler(types.SimpleNamespace(data={}))
        except HomeAssistantError as err:
            assert not isinstance(err, SERVICE_VALIDATION_ERROR)
            assert _translation_key(err) == "agent_command_failed"
        else:
            raise AssertionError("answer wait failure was not translated")

        assert calls == ["answer"]
        assert api.answer_doorbell_call_calls == [True]
        assert api.hangup_doorbell_call_calls == 0

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
                    "capture_mode": "ring",
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
        except HomeAssistantError as err:
            assert not isinstance(err, SERVICE_VALIDATION_ERROR)
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


@pytest.mark.parametrize(
    ("failure", "key"),
    [
        ("busy", "station_busy"),
        ("refused", "agent_command_failed"),
    ],
)
def test_write_text_memo_during_a_call_says_the_station_is_busy(failure: str, key: str) -> None:
    from custom_components.bticino_c300x.api_errors import (
        C300XAgentApiConnectionError,
        C300XStationBusyError,
    )

    errors = {
        "busy": C300XStationBusyError('HTTP 409: {"ok":false,"error":"station_busy"}'),
        "refused": C300XAgentApiConnectionError('HTTP 502: {"ok":false,"error":"memo_create_refused"}'),
    }

    class _BusyApi(_FakeApi):
        async def async_create_text_memo(self, text: str, *, read: bool = False) -> dict[str, Any]:
            raise errors[failure]

    async def _run() -> None:
        entry = _FakeEntry(
            _FakeRuntimeData(
                api=_BusyApi(),
                capabilities={"memos": {"supported": True, "write_text": True}},
            )
        )
        hass = _FakeHass([entry])

        await async_setup_services(hass)  # type: ignore[arg-type]
        handler = hass.services.handlers[(DOMAIN, SERVICE_WRITE_TEXT_MEMO)]
        with pytest.raises(HomeAssistantError) as raised:
            await handler(types.SimpleNamespace(data={"text": "new memo"}))
        # A device-side state, not invalid input.
        assert not isinstance(raised.value, SERVICE_VALIDATION_ERROR)
        assert _translation_key(raised.value) == key
        assert raised.value.__cause__ is errors[failure]
        assert entry.runtime_data.memos == {}

    asyncio.run(_run())


def test_write_text_memo_schedules_a_background_refresh_when_the_refresh_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[str] = []

    async def _failing_refresh(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("agent unreachable")

    async def _diagnostics(*_args: Any) -> None:
        return None

    monkeypatch.setattr(
        "custom_components.bticino_c300x.use_cases.memos.async_memos", _failing_refresh
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.use_cases.memos.schedule_memos_refresh",
        lambda _hass, _entry: scheduled.append("memos"),
    )
    monkeypatch.setattr(common_use_cases, "async_dispatcher_send", lambda *args: None)
    monkeypatch.setattr(common_use_cases, "async_refresh_agent_diagnostics", _diagnostics)

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
        await handler(types.SimpleNamespace(data={"text": "new memo", "read": False}))

        assert api.text_memo_calls == [{"text": "new memo", "read": False}]

    asyncio.run(_run())
    assert scheduled == ["memos"]


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
            await common_use_cases.raise_agent_command_failed(_failing_command(), entry=_FakeEntry(_FakeRuntimeData()))
        except HomeAssistantError as err:
            # A device-side failure, not invalid input.
            assert not isinstance(err, SERVICE_VALIDATION_ERROR)
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
        except HomeAssistantError as err:
            assert not isinstance(err, SERVICE_VALIDATION_ERROR)
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

        assert await common_use_cases.latest_item_id_for_entry(
            entry, cache_attr="cached_payload", refresh=_refresh, latest=latest,
            unavailable_error="missing_item", refresh_before_lookup=True,
        ) == "fresh-id"
        assert refreshes == 1

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
        assert refreshes == 2

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
        except HomeAssistantError as err:
            assert not isinstance(err, SERVICE_VALIDATION_ERROR)
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


def test_common_refresh_after_message_mutation_survives_refresh_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher_calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        common_use_cases,
        "async_dispatcher_send",
        lambda *args: dispatcher_calls.append(args),
    )

    async def _diagnostics(*_args: Any) -> None:
        return None

    monkeypatch.setattr(common_use_cases, "async_refresh_agent_diagnostics", _diagnostics)

    async def _run() -> None:
        hass = _FakeHass([])
        entry = _FakeEntry(_FakeRuntimeData())

        async def _refresh() -> dict[str, Any]:
            raise RuntimeError("agent failed")

        await common_use_cases.async_refresh_after_message_mutation(
            hass,  # type: ignore[arg-type]
            entry,
            refresh=_refresh,
            signal="signal-name",
        )

    asyncio.run(_run())

    assert [call[1:] for call in dispatcher_calls] == [("signal-name", "entry-id")]


def test_common_refresh_after_message_mutation_retries_in_the_background_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(common_use_cases, "async_dispatcher_send", lambda *args: None)

    async def _diagnostics(*_args: Any) -> None:
        return None

    monkeypatch.setattr(common_use_cases, "async_refresh_agent_diagnostics", _diagnostics)
    retries: list[str] = []

    async def _run(fail: bool) -> None:
        async def _refresh() -> dict[str, Any]:
            if fail:
                raise RuntimeError("agent failed")
            return {"ok": True}

        await common_use_cases.async_refresh_after_message_mutation(
            _FakeHass([]),  # type: ignore[arg-type]
            _FakeEntry(_FakeRuntimeData()),
            refresh=_refresh,
            signal="signal-name",
            retry=lambda: retries.append("retry"),
        )

    asyncio.run(_run(False))
    assert retries == []
    asyncio.run(_run(True))
    assert retries == ["retry"]


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
