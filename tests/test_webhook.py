from __future__ import annotations

import asyncio
import datetime
import sys
import types
from types import SimpleNamespace

homeassistant = sys.modules.setdefault(
    "homeassistant",
    types.ModuleType("homeassistant"),
)
components = sys.modules.setdefault(
    "homeassistant.components",
    types.ModuleType("homeassistant.components"),
)
webhook = types.ModuleType("homeassistant.components.webhook")
config_entries = sys.modules.setdefault(
    "homeassistant.config_entries",
    types.ModuleType("homeassistant.config_entries"),
)
core = sys.modules.setdefault("homeassistant.core", types.ModuleType("homeassistant.core"))
helpers = sys.modules.setdefault(
    "homeassistant.helpers",
    types.ModuleType("homeassistant.helpers"),
)
helpers_config_validation = types.ModuleType("homeassistant.helpers.config_validation")
helpers_dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
helpers_event = types.ModuleType("homeassistant.helpers.event")
helpers_entity = types.ModuleType("homeassistant.helpers.entity")
helpers_entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
helpers_issue_registry = types.ModuleType("homeassistant.helpers.issue_registry")
util = sys.modules.setdefault("homeassistant.util", types.ModuleType("homeassistant.util"))
util_dt = types.ModuleType("homeassistant.util.dt")


def _utcnow() -> datetime.datetime:
    return datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)


class _FakeConfig:  # pragma: no cover - import-time stub only
    language = None


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def async_fire(self, event_type: str, event_data: dict[str, object]) -> None:
        self.events.append((event_type, event_data))


class _FakeHass:  # pragma: no cover - import-time stub only
    config = _FakeConfig()

    def __init__(self) -> None:
        self.bus = _FakeBus()


def _webhook_url(_: _FakeHass, webhook_id: str) -> str:
    return f"http://localhost:8123/webhook/{webhook_id}"


webhook.async_generate_url = _webhook_url
webhook.async_register = lambda *args, **kwargs: None
webhook.async_unregister = lambda *args, **kwargs: None

config_entries.ConfigEntry = type("ConfigEntry", (), {})
core.HomeAssistant = type("HomeAssistant", (), {"config": _FakeConfig()})
core.CALLBACK_TYPE = type(_utcnow())
core.callback = lambda func: func
helpers.dispatcher = helpers_dispatcher
helpers.event = helpers_event
helpers.entity = helpers_entity
helpers.entity_registry = helpers_entity_registry
helpers.issue_registry = helpers_issue_registry
helpers.config_validation = helpers_config_validation
helpers_config_validation.config_entry_only_config_schema = lambda domain: None
helpers_entity_registry.async_get = lambda hass: None
helpers_issue_registry.IssueSeverity = types.SimpleNamespace(
    ERROR="error",
    WARNING="warning",
)
helpers_issue_registry.async_create_issue = lambda *args, **kwargs: None
helpers_issue_registry.async_delete_issue = lambda *args, **kwargs: None
helpers_dispatcher.async_dispatcher_send = lambda *args, **kwargs: None
helpers_dispatcher.async_dispatcher_connect = lambda *args, **kwargs: lambda: None
helpers_event.async_call_later = lambda *args, **kwargs: None
helpers_entity.DeviceInfo = lambda **kwargs: kwargs


class _FakeEntity:  # pragma: no cover - import-time stub only
    def __init__(self, *args, **kwargs) -> None:
        self.hass = kwargs.get("hass")


helpers_entity.Entity = _FakeEntity
util_dt.utcnow = _utcnow
util.dt = util_dt

components.webhook = webhook
components.webhook.async_generate_url = _webhook_url
homeassistant.components = components
homeassistant.core = core
homeassistant.config_entries = config_entries
homeassistant.helpers = helpers
homeassistant.util = util
sys.modules["homeassistant.components.webhook"] = webhook
sys.modules["homeassistant.config_entries"] = config_entries
sys.modules["homeassistant.components"] = components
sys.modules["homeassistant.core"] = core
sys.modules["homeassistant.helpers"] = helpers
sys.modules["homeassistant.helpers.config_validation"] = helpers_config_validation
sys.modules["homeassistant.helpers.dispatcher"] = helpers_dispatcher
sys.modules["homeassistant.helpers.event"] = helpers_event
sys.modules["homeassistant.helpers.entity"] = helpers_entity
sys.modules["homeassistant.helpers.entity_registry"] = helpers_entity_registry
sys.modules["homeassistant.helpers.issue_registry"] = helpers_issue_registry
sys.modules["homeassistant.util"] = util
sys.modules["homeassistant.util.dt"] = util_dt

from custom_components.bticino_c300x import webhook as webhook_module  # noqa: E402
from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_EVENT_WEBHOOK_TOKEN,
    EVENT_AGENT_EVENT_RECEIVED,
    HEADER_EVENT_TOKEN,
    SIGNAL_MEMOS_CHANGED,
)
from custom_components.bticino_c300x.data import C300XEventState  # noqa: E402
from custom_components.bticino_c300x.webhook import (  # noqa: E402
    _async_handle_agent_event,
    _event_type_value,
    _normalize_event_type,
)  # pylint: disable=wrong-import-position


class _FakeRequest:
    method = "POST"

    def __init__(self, token: str, payload: dict[str, object]) -> None:
        self.headers = {HEADER_EVENT_TOKEN: token}
        self._payload = payload

    async def json(self) -> dict[str, object]:
        return self._payload


def test_event_type_value_prefers_payload_aliases() -> None:
    payload = {"event": "doorbell.pressed"}

    assert _event_type_value(payload) == "doorbell_pressed"


def test_event_type_value_prefers_nested_alias() -> None:
    payload = {"data": {"event_type": "ringer.unmuted", "mode": "enabled"}}

    assert _event_type_value(payload) == "ringer_unmuted"


def test_event_type_value_handles_stair_light_event_from_namespace() -> None:
    payload = {"event_type": "stair_light.activated"}

    assert _event_type_value(payload) == "stair_light_activated"


def test_normalize_event_type_aliases_do_not_raise() -> None:
    assert _normalize_event_type("agent.restarted") == "agent_restarted"
    assert _normalize_event_type("agent") == ""
    assert _normalize_event_type("") == ""
    assert _normalize_event_type(None) == ""


def test_normalize_event_type_includes_stair_light_activation() -> None:
    assert _normalize_event_type("stair_light.activated") == "stair_light_activated"


def test_doorbell_media_closed_clears_runtime_video_state() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    event_state.video_available = True
    event_state.video_stream_path = "/doorbell-video"
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=SimpleNamespace(event_state=event_state),
    )
    request = _FakeRequest(
        "event-token",
        {
            "event": "doorbell.media.closed",
            "data": {
                "doorbell": "idle",
                "video": {"available": False, "window_available": False},
            },
        },
    )

    original_resolve_camera = webhook_module.resolve_doorbell_camera_entity_id
    webhook_module.resolve_doorbell_camera_entity_id = lambda _hass, _entry: None
    try:
        response = asyncio.run(
            _async_handle_agent_event(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                event_state,
                request,  # type: ignore[arg-type]
            )
        )
    finally:
        webhook_module.resolve_doorbell_camera_entity_id = original_resolve_camera

    assert response.status == 200
    assert event_state.video_available is False
    assert event_state.video_window_available is False
    assert event_state.video_stream_path is None
    assert event_state.last_event_data["event_key"] == "doorbell_media_closed"
    assert event_state.last_event_data["doorbell"] == "idle"
    assert hass.bus.events[-1][1]["event_key"] == "doorbell_media_closed"


def test_real_doorbell_event_fires_public_event() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=SimpleNamespace(event_state=event_state),
    )
    request = _FakeRequest(
        "event-token",
        {"event": "doorbell.pressed", "data": {"doorbell": "ringing"}},
    )

    original_resolve_camera = webhook_module.resolve_doorbell_camera_entity_id
    webhook_module.resolve_doorbell_camera_entity_id = lambda _hass, _entry: None
    try:
        response = asyncio.run(
            _async_handle_agent_event(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                event_state,
                request,  # type: ignore[arg-type]
            )
        )
    finally:
        webhook_module.resolve_doorbell_camera_entity_id = original_resolve_camera

    assert response.status == 200
    assert hass.bus.events == [
        (
            EVENT_AGENT_EVENT_RECEIVED,
            event_state.last_event_data,
        )
    ]


def test_external_doorbell_view_does_not_advertise_ha_video_available() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=SimpleNamespace(event_state=event_state),
    )
    request = _FakeRequest(
        "event-token",
        {
            "event": "doorbell.view_requested",
            "data": {
                "doorbell": "view_requested",
                "video": {"available": False, "window_available": False},
            },
        },
    )

    original_resolve_camera = webhook_module.resolve_doorbell_camera_entity_id
    webhook_module.resolve_doorbell_camera_entity_id = (
        lambda _hass, _entry: "camera.bticino_doorbell"
    )
    try:
        response = asyncio.run(
            _async_handle_agent_event(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                event_state,
                request,  # type: ignore[arg-type]
            )
        )
    finally:
        webhook_module.resolve_doorbell_camera_entity_id = original_resolve_camera

    assert response.status == 200
    assert event_state.video_available is False
    assert event_state.last_event_data["video_available"] is False
    assert event_state.last_event_data["video_window_available"] is False
    assert event_state.last_event_data["doorbell"] == "view_requested"
    assert event_state.last_event_data["camera_entity_id"] == "camera.bticino_doorbell"
    assert hass.bus.events[-1][1]["video_available"] is False


def test_doorbell_view_uses_explicit_ha_video_availability() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=SimpleNamespace(event_state=event_state),
    )
    request = _FakeRequest(
        "event-token",
        {
            "event": "doorbell.view_requested",
            "data": {
                "doorbell": "view_requested",
                "video": {
                    "available": True,
                    "window_available": True,
                    "stream_path": "/doorbell-video",
                },
            },
        },
    )

    original_resolve_camera = webhook_module.resolve_doorbell_camera_entity_id
    webhook_module.resolve_doorbell_camera_entity_id = (
        lambda _hass, _entry: "camera.bticino_doorbell"
    )
    try:
        response = asyncio.run(
            _async_handle_agent_event(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                event_state,
                request,  # type: ignore[arg-type]
            )
        )
    finally:
        webhook_module.resolve_doorbell_camera_entity_id = original_resolve_camera

    assert response.status == 200
    assert event_state.video_available is True
    assert event_state.video_window_available is True
    assert event_state.last_event_data["video_available"] is True
    assert event_state.last_event_data["video_window_available"] is True
    assert event_state.last_event_data["doorbell"] == "view_requested"
    assert event_state.last_event_data["stream_path"] == "/doorbell-video"


def test_doorbell_view_keeps_agent_video_available_without_camera_entity_id() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=SimpleNamespace(event_state=event_state),
    )
    request = _FakeRequest(
        "event-token",
        {
            "event": "doorbell.view_requested",
            "data": {
                "doorbell": "view_requested",
                "video": {
                    "available": True,
                    "window_available": True,
                    "stream_path": "/doorbell-video",
                },
            },
        },
    )

    original_resolve_camera = webhook_module.resolve_doorbell_camera_entity_id
    webhook_module.resolve_doorbell_camera_entity_id = lambda _hass, _entry: None
    try:
        response = asyncio.run(
            _async_handle_agent_event(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                event_state,
                request,  # type: ignore[arg-type]
            )
        )
    finally:
        webhook_module.resolve_doorbell_camera_entity_id = original_resolve_camera

    assert response.status == 200
    assert event_state.last_event_data["video_available"] is True
    assert event_state.last_event_data["video_window_available"] is True
    assert "camera_entity_id" not in event_state.last_event_data


def test_external_media_active_overrides_doorbell_video_availability() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=SimpleNamespace(event_state=event_state),
    )
    request = _FakeRequest(
        "event-token",
        {
            "event": "doorbell.view_requested",
            "data": {
                "video": {
                    "available": True,
                    "window_available": True,
                    "external_media_active": True,
                }
            },
        },
    )

    original_resolve_camera = webhook_module.resolve_doorbell_camera_entity_id
    webhook_module.resolve_doorbell_camera_entity_id = (
        lambda _hass, _entry: "camera.bticino_doorbell"
    )
    try:
        response = asyncio.run(
            _async_handle_agent_event(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                event_state,
                request,  # type: ignore[arg-type]
            )
        )
    finally:
        webhook_module.resolve_doorbell_camera_entity_id = original_resolve_camera

    assert response.status == 200
    assert event_state.video_available is False
    assert event_state.last_event_data["video_available"] is False
    assert event_state.last_event_data["video_window_available"] is False


def test_snapshot_doorbell_event_updates_state_without_public_event() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=SimpleNamespace(event_state=event_state),
    )
    request = _FakeRequest(
        "event-token",
        {
            "event": "doorbell.pressed",
            "snapshot": True,
            "data": {"doorbell": "ringing"},
        },
    )

    original_resolve_camera = webhook_module.resolve_doorbell_camera_entity_id
    webhook_module.resolve_doorbell_camera_entity_id = lambda _hass, _entry: None
    try:
        response = asyncio.run(
            _async_handle_agent_event(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                event_state,
                request,  # type: ignore[arg-type]
            )
        )
    finally:
        webhook_module.resolve_doorbell_camera_entity_id = original_resolve_camera

    assert response.status == 200
    assert event_state.last_event is None
    assert event_state.last_event_time is None
    assert event_state.event_sequence == 0
    assert event_state.last_event_data == {}
    assert hass.bus.events == []


def test_snapshot_memo_event_refreshes_memo_entities_without_public_event() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    runtime_data = SimpleNamespace(
        event_state=event_state,
        memos={
            "available": True,
            "total": 0,
            "memos": [{"id": "memo-1", "kind": "text"}],
        },
        memos_updated_at=None,
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=runtime_data,
    )
    request = _FakeRequest(
        "event-token",
        {
            "event": "memos.changed",
            "snapshot": True,
            "data": {
                "memos": {
                    "available": True,
                    "total": 1,
                    "text_total": 1,
                    "voice_total": 0,
                    "unread": 1,
                    "read": 0,
                    "newest_at": "2026-06-02T10:00:00Z",
                }
            },
        },
    )
    signals: list[tuple[str, str]] = []
    original_dispatcher = webhook_module.async_dispatcher_send
    webhook_module.async_dispatcher_send = lambda _hass, signal, entry_id: signals.append(
        (signal, entry_id)
    )
    try:
        response = asyncio.run(
            _async_handle_agent_event(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                event_state,
                request,  # type: ignore[arg-type]
            )
        )
    finally:
        webhook_module.async_dispatcher_send = original_dispatcher

    assert response.status == 200
    assert hass.bus.events == []
    assert event_state.last_event is None
    assert event_state.last_event_time is None
    assert event_state.event_sequence == 0
    assert event_state.last_event_data == {}
    assert runtime_data.memos["total"] == 1
    assert runtime_data.memos["memos"][0]["id"] == "memo-1"
    assert runtime_data.memos["memos"][0]["kind"] == "text"
    assert runtime_data.memos_updated_at is not None
    assert signals == [(SIGNAL_MEMOS_CHANGED, "entry-1")]


def test_system_metrics_event_updates_cache_without_public_event() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    runtime_data = SimpleNamespace(
        event_state=event_state,
        system_metrics={},
        system_metrics_updated_at=None,
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=runtime_data,
    )
    request = _FakeRequest(
        "event-token",
        {
            "event": "system.metrics_changed",
            "data": {
                "system_metrics": {
                    "cpu_count": 1,
                    "cpu_usage_percent": 3.5,
                    "load_1m": 0.12,
                    "load_5m": 0.1,
                    "load_15m": 0.08,
                    "load_1m_percent": 12.0,
                    "load_5m_percent": 10.0,
                    "load_15m_percent": 8.0,
                    "memory_total_kb": 262144,
                    "memory_available_kb": 196608,
                    "memory_used_kb": 65536,
                    "memory_usage_percent": 25.0,
                    "temperature_c": 41.5,
                    "temperature_source": "sysfs",
                }
            },
        },
    )

    response = asyncio.run(
        _async_handle_agent_event(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            event_state,
            request,  # type: ignore[arg-type]
        )
    )

    assert response.status == 200
    assert runtime_data.system_metrics["cpu_usage_percent"] == 3.5
    assert runtime_data.system_metrics["load_1m_percent"] == 12.0
    assert runtime_data.system_metrics["memory_usage_percent"] == 25.0
    assert runtime_data.system_metrics_updated_at is not None
    assert event_state.last_event is None
    assert hass.bus.events == []


def test_agent_diagnostics_event_refreshes_cache_without_public_event() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    runtime_data = SimpleNamespace(
        event_state=event_state,
        capabilities={"diagnostics": {"supported": True, "writes": True}},
        agent_diagnostics={},
        agent_diagnostics_updated_at=None,
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=runtime_data,
    )
    request = _FakeRequest(
        "event-token",
        {
            "event": "agent.diagnostics_changed",
            "data": {"agent_write_count": 3},
        },
    )

    async def _unexpected_refresh(hass_arg: object, entry_arg: object) -> None:
        raise AssertionError("diagnostics event should not call back into the agent")

    original_refresh = webhook_module.async_refresh_agent_diagnostics
    webhook_module.async_refresh_agent_diagnostics = _unexpected_refresh  # type: ignore[assignment]
    try:
        response = asyncio.run(
            _async_handle_agent_event(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                event_state,
                request,  # type: ignore[arg-type]
            )
        )
    finally:
        webhook_module.async_refresh_agent_diagnostics = original_refresh

    assert response.status == 200
    assert runtime_data.agent_diagnostics["agent_write_count"] == 3
    assert runtime_data.agent_diagnostics_updated_at is not None
    assert event_state.last_event is None
    assert hass.bus.events == []
