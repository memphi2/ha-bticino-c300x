from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field
from typing import Any

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


class _ServiceValidationError(Exception):  # pragma: no cover - import-time stub only
    pass


class _ConfigEntry:  # pragma: no cover - import-time stub only
    pass


class _DeviceInfo(dict):  # pragma: no cover - import-time stub only
    pass


class _Entity:  # pragma: no cover - import-time stub only
    pass


config_entries.ConfigEntry = _ConfigEntry
const.ATTR_ENTITY_ID = "entity_id"
core.HomeAssistant = getattr(core, "HomeAssistant", object)
core.ServiceCall = getattr(core, "ServiceCall", _ServiceCall)
core.callback = getattr(core, "callback", lambda func: func)
exceptions.ServiceValidationError = getattr(
    exceptions,
    "ServiceValidationError",
    _ServiceValidationError,
)
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

from custom_components.bticino_c300x import services as service_module  # noqa: E402
from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_DEVICE_UI_ENABLED,
    DOMAIN,
    SERVICE_DELETE_LATEST_TEXT_MEMO,
    SERVICE_DELETE_LATEST_VIDEO_MESSAGE,
    SERVICE_DELETE_LATEST_VOICE_MEMO,
    SERVICE_PLAY_LATEST_VIDEO_MESSAGE,
    SERVICE_PLAY_LATEST_VOICE_MEMO,
    SIGNAL_QML_PATCH_CHANGED,
)
from custom_components.bticino_c300x.services import async_setup_services  # noqa: E402


@dataclass
class _FakeRuntimeData:
    capabilities: dict[str, Any] = field(default_factory=dict)
    qml_patch_status: dict[str, Any] = field(default_factory=dict)


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

    def async_register(self, domain: str, service: str, *_args: Any, **_kwargs: Any) -> None:
        self.registered.add((domain, service))

    def async_remove(self, domain: str, service: str) -> None:
        self.registered.discard((domain, service))


class _FakeHass:
    def __init__(self, entries: list[_FakeEntry]) -> None:
        self.data: dict[str, Any] = {}
        self.config_entries = _FakeConfigEntries(entries)
        self.services = _FakeServices()


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
        assert (DOMAIN, SERVICE_DELETE_LATEST_VIDEO_MESSAGE) in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_TEXT_MEMO) in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VOICE_MEMO) in hass.services.registered

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
        assert (DOMAIN, SERVICE_DELETE_LATEST_VIDEO_MESSAGE) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_TEXT_MEMO) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VOICE_MEMO) not in hass.services.registered

    asyncio.run(_run())


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
        assert (DOMAIN, SERVICE_DELETE_LATEST_VIDEO_MESSAGE) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_TEXT_MEMO) not in hass.services.registered
        assert (DOMAIN, SERVICE_DELETE_LATEST_VOICE_MEMO) not in hass.services.registered

    asyncio.run(_run())
