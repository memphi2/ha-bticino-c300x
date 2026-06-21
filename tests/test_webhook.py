from __future__ import annotations

import asyncio
import datetime
import json
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
        self.tasks: list[asyncio.Task] = []

    def async_create_task(self, coro: object) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task


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

from custom_components.bticino_c300x import (  # noqa: E402
    agent_diagnostics as agent_diagnostics_module,
)
from custom_components.bticino_c300x import (  # noqa: E402
    media_watchdog,
)
from custom_components.bticino_c300x import (  # noqa: E402
    webhook as webhook_module,
)
from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_EVENT_WEBHOOK_TOKEN,
    CONF_SHARED_SECRET,
    EVENT_AGENT_EVENT_RECEIVED,
    HEADER_EVENT_TOKEN,
    HEADER_SHARED_SECRET,
    SIGNAL_MEMOS_CHANGED,
    SIGNAL_VIDEO_MESSAGES_CHANGED,
)
from custom_components.bticino_c300x.data import C300XEventState  # noqa: E402
from custom_components.bticino_c300x.webhook import (  # noqa: E402
    _async_handle_agent_event,
    _async_handle_webhook,
    _event_payload,
    _event_type_value,
    _is_snapshot_payload,
    _normalize_event_type,
    _optional_bool,
    _optional_int,
    async_register_agent_event_webhook,
    async_register_webhook,
)  # pylint: disable=wrong-import-position


class _FakeRequest:
    def __init__(
        self,
        token: str,
        payload: object,
        *,
        method: str = "POST",
        extra_headers: dict[str, str] | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self.method = method
        self.headers = {HEADER_EVENT_TOKEN: token, **(extra_headers or {})}
        self._payload = payload
        self._json_error = json_error

    async def json(self) -> object:
        if self._json_error is not None:
            raise self._json_error
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


def test_event_payload_rejects_non_post_or_invalid_json() -> None:
    assert asyncio.run(_event_payload(_FakeRequest("token", {}, method="GET"))) == {}
    assert (
        asyncio.run(
            _event_payload(
                _FakeRequest("token", {}, json_error=ValueError("invalid json"))
            )
        )
        == {}
    )
    assert asyncio.run(_event_payload(_FakeRequest("token", []))) == {}


def test_snapshot_payload_detects_supported_markers() -> None:
    assert _is_snapshot_payload({"snapshot": True}) is True
    assert _is_snapshot_payload({"replay": "true"}) is True
    assert _is_snapshot_payload({"source": " snapshot "}) is True
    assert _is_snapshot_payload({"source": "live"}) is False


def test_optional_value_helpers_handle_unusable_values() -> None:
    assert _optional_bool(True) is True
    assert _optional_bool("muted") is True
    assert _optional_bool("unmuted") is False
    assert _optional_bool("unknown") is None
    assert _optional_int("12") == 12
    assert _optional_int("bad") is None


def test_display_bridge_webhook_rejects_invalid_requests() -> None:
    hass = _FakeHass()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_SHARED_SECRET: "shared-secret"},
        options={},
    )

    unauthorized = asyncio.run(
        _async_handle_webhook(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            _FakeRequest("", {"type": "status"}),  # type: ignore[arg-type]
        )
    )
    invalid_json = asyncio.run(
        _async_handle_webhook(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            _FakeRequest(
                "",
                {},
                extra_headers={HEADER_SHARED_SECRET: "shared-secret"},
                json_error=ValueError("invalid"),
            ),  # type: ignore[arg-type]
        )
    )
    invalid_payload = asyncio.run(
        _async_handle_webhook(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            _FakeRequest(
                "",
                [],
                extra_headers={HEADER_SHARED_SECRET: "shared-secret"},
            ),  # type: ignore[arg-type]
        )
    )
    unsupported = asyncio.run(
        _async_handle_webhook(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            _FakeRequest(
                "",
                {"type": "unknown"},
                extra_headers={HEADER_SHARED_SECRET: "shared-secret"},
            ),  # type: ignore[arg-type]
        )
    )

    assert unauthorized.status == 401
    assert invalid_json.status == 400
    assert invalid_payload.status == 400
    assert unsupported.status == 400


def test_display_bridge_status_webhook_uses_registered_handler(monkeypatch) -> None:  # noqa: ANN001
    hass = _FakeHass()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_SHARED_SECRET: "shared-secret"},
        options={},
    )

    async def status(hass_arg: object, entry_arg: object) -> dict[str, object]:
        assert hass_arg is hass
        assert entry_arg is entry
        return {"ok": True, "status": "ready"}

    monkeypatch.setattr(webhook_module, "async_status", status)

    response = asyncio.run(
        _async_handle_webhook(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            _FakeRequest(
                "",
                {"type": "status"},
                extra_headers={HEADER_SHARED_SECRET: "shared-secret"},
            ),  # type: ignore[arg-type]
        )
    )

    assert response.status == 200


def test_webhook_registration_uses_entry_ids_and_unregisters(monkeypatch) -> None:  # noqa: ANN001
    hass = _FakeHass()
    event_state = C300XEventState()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={
            "webhook_id": "display-webhook",
            "event_webhook_id": "event-webhook",
        },
    )
    registered: list[tuple[str, str, tuple[str, ...]]] = []
    unregistered: list[str] = []

    def _register(
        hass_arg: object,
        domain: str,
        name: str,
        webhook_id: str,
        handler: object,
        *,
        local_only: bool,
        allowed_methods: tuple[str, ...],
    ) -> None:
        assert hass_arg is hass
        assert callable(handler)
        assert local_only is False
        registered.append((domain, name, webhook_id, allowed_methods))

    monkeypatch.setattr(webhook_module.webhook, "async_register", _register)
    monkeypatch.setattr(
        webhook_module.webhook,
        "async_unregister",
        lambda hass_arg, webhook_id: unregistered.append(webhook_id),
    )

    unregister_display = async_register_webhook(
        hass,  # type: ignore[arg-type]
        entry,  # type: ignore[arg-type]
    )
    unregister_events = async_register_agent_event_webhook(
        hass,  # type: ignore[arg-type]
        entry,  # type: ignore[arg-type]
        event_state,
    )
    unregister_display()
    unregister_events()

    assert registered == [
        (
            "bticino_c300x",
            "C300X",
            "display-webhook",
            ("POST",),
        ),
        (
            "bticino_c300x",
            "C300X device-agent events",
            "event-webhook",
            ("POST",),
        ),
    ]
    assert unregistered == ["display-webhook", "event-webhook"]


def test_display_bridge_command_handlers_forward_payloads(monkeypatch) -> None:  # noqa: ANN001
    hass = _FakeHass()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_SHARED_SECRET: "shared-secret"},
        options={},
    )
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    async def _action(hass_arg: object, entry_arg: object, action_id: str) -> dict:
        calls.append(("action", (hass_arg, entry_arg, action_id), {}))
        return {"ok": True, "kind": "action"}

    async def _dashboard_action(
        hass_arg: object,
        entry_arg: object,
        entity_id: str,
        *,
        option: str | None,
    ) -> dict:
        calls.append(
            (
                "dashboard_action",
                (hass_arg, entry_arg, entity_id),
                {"option": option},
            )
        )
        return {"ok": True, "kind": "dashboard_action"}

    async def _stair_light(
        hass_arg: object,
        entry_arg: object,
        address: str | None,
    ) -> dict:
        calls.append(("stair_light", (hass_arg, entry_arg, address), {}))
        return {"ok": True, "kind": "stair_light"}

    async def _alarm_command(
        hass_arg: object,
        entry_arg: object,
        command: str,
        code: str | None,
        *,
        force: bool,
        check: bool,
    ) -> dict:
        calls.append(
            (
                "alarm_command",
                (hass_arg, entry_arg, command, code),
                {"force": force, "check": check},
            )
        )
        return {"ok": True, "kind": "alarm_command"}

    monkeypatch.setattr(webhook_module, "async_execute_action", _action)
    monkeypatch.setattr(
        webhook_module,
        "async_execute_dashboard_action",
        _dashboard_action,
    )
    monkeypatch.setattr(webhook_module, "async_trigger_stair_light", _stair_light)
    monkeypatch.setattr(webhook_module, "async_execute_alarm_command", _alarm_command)

    for payload in (
        {"type": "action", "action_id": "open"},
        {
            "type": "dashboard_action",
            "entity_id": "select.mode",
            "option": "Home Assistant",
        },
        {"type": "stair_light", "address": "77"},
        {
            "type": "alarm_command",
            "command": "arm_home",
            "code": "1234",
            "force": True,
            "check": True,
        },
    ):
        response = asyncio.run(
            _async_handle_webhook(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                _FakeRequest(
                    "",
                    payload,
                    extra_headers={HEADER_SHARED_SECRET: "shared-secret"},
                ),  # type: ignore[arg-type]
            )
        )
        assert response.status == 200

    assert calls == [
        ("action", (hass, entry, "open"), {}),
        (
            "dashboard_action",
            (hass, entry, "select.mode"),
            {"option": "Home Assistant"},
        ),
        ("stair_light", (hass, entry, "77"), {}),
        (
            "alarm_command",
            (hass, entry, "arm_home", "1234"),
            {"force": True, "check": True},
        ),
    ]


def test_display_bridge_command_errors_are_contained(monkeypatch) -> None:  # noqa: ANN001
    hass = _FakeHass()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_SHARED_SECRET: "shared-secret"},
        options={},
    )

    async def _raise(error: Exception) -> dict:
        raise error

    for error, status, message in (
        (KeyError("missing"), 404, "unknown_action"),
        (ValueError("bad_action"), 400, "bad_action"),
        (RuntimeError("boom"), 500, "command_failed"),
    ):
        monkeypatch.setattr(
            webhook_module,
            "async_execute_action",
            lambda *_args, _error=error: _raise(_error),
        )
        response = asyncio.run(
            _async_handle_webhook(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                _FakeRequest(
                    "",
                    {"type": "action", "action_id": "x"},
                    extra_headers={HEADER_SHARED_SECRET: "shared-secret"},
                ),  # type: ignore[arg-type]
            )
        )
        assert response.status == status
        assert json.loads(response.text) == {"ok": False, "error": message}


def test_display_bridge_dashboard_webhook_returns_revision_and_not_modified(
    monkeypatch,
) -> None:  # noqa: ANN001
    hass = _FakeHass()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_SHARED_SECRET: "shared-secret"},
        options={},
    )

    async def dashboard(hass_arg: object, entry_arg: object) -> dict[str, object]:
        assert hass_arg is hass
        assert entry_arg is entry
        return {"data": {"pages": [{"title": "Main"}]}, "preventReturnToHomepage": False}

    monkeypatch.setattr(webhook_module, "async_dashboard_payload", dashboard)

    response = asyncio.run(
        _async_handle_webhook(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            _FakeRequest(
                "",
                {"type": "dashboard"},
                extra_headers={HEADER_SHARED_SECRET: "shared-secret"},
            ),  # type: ignore[arg-type]
        )
    )
    payload = json.loads(response.text)
    revision = payload["revision"]

    cached = asyncio.run(
        _async_handle_webhook(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            _FakeRequest(
                "",
                {"type": "dashboard", "revision": revision},
                extra_headers={HEADER_SHARED_SECRET: "shared-secret"},
            ),  # type: ignore[arg-type]
        )
    )

    assert response.status == 200
    assert payload["data"]["pages"][0]["title"] == "Main"
    assert cached.status == 200
    assert json.loads(cached.text) == {
        "ok": True,
        "not_modified": True,
        "revision": revision,
    }


def test_agent_event_webhook_rejects_unauthorized_or_unsupported_events() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=SimpleNamespace(event_state=event_state),
    )

    unauthorized = asyncio.run(
        _async_handle_agent_event(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            event_state,
            _FakeRequest("bad-token", {"event": "ringer.muted"}),  # type: ignore[arg-type]
        )
    )
    unsupported = asyncio.run(
        _async_handle_agent_event(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            event_state,
            _FakeRequest("event-token", {}),  # type: ignore[arg-type]
        )
    )

    assert unauthorized.status == 401
    assert unsupported.status == 400
    assert hass.bus.events == []


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


def test_ringer_event_updates_state_and_public_event_data() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=SimpleNamespace(event_state=event_state),
    )
    request = _FakeRequest("event-token", {"event": "ringer.muted"})

    response = asyncio.run(
        _async_handle_agent_event(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            event_state,
            request,  # type: ignore[arg-type]
        )
    )

    assert response.status == 200
    assert event_state.ringer_muted is True
    assert event_state.last_event_data["muted"] is True
    assert hass.bus.events[-1][1]["event_key"] == "ringer_muted"


def test_smartphone_forwarding_event_updates_state_and_public_event_data() -> None:
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
        {"event": "smartphone_forwarding.changed", "data": {"mode": 2}},
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
    assert event_state.smartphone_forwarding_mode == "blocked"
    assert event_state.last_event_data["mode"] == "blocked"


def test_door_unlock_event_keeps_address_in_public_event_data() -> None:
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
        {"event": "door_unlock.started", "data": {"address": "20"}},
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
    assert event_state.door_unlock_state == "door_unlock_started"
    assert event_state.last_event_data["address"] == "20"


def test_call_events_update_call_active_state() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=SimpleNamespace(event_state=event_state),
    )

    for event_name, expected in (("call.started", True), ("call.ended", False)):
        response = asyncio.run(
            _async_handle_agent_event(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                event_state,
                _FakeRequest("event-token", {"event": event_name}),  # type: ignore[arg-type]
            )
        )
        assert response.status == 200
        assert event_state.call_active is expected


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
                    "media_owner": "ring",
                    "bridge": {
                        "media_owner": "ring",
                        "ring_registered": True,
                        "unanswered_ring_call": True,
                    },
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
    assert event_state.last_event_data["media_owner"] == "ring"
    assert event_state.last_event_data["bridge"] == {
        "media_owner": "ring",
        "ring_registered": True,
        "unanswered_ring_call": True,
    }


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


def test_snapshot_voicemail_event_refreshes_message_entities_without_public_event() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    runtime_data = SimpleNamespace(
        event_state=event_state,
        answering_machine_messages={
            "available": True,
            "total": 0,
            "messages": [{"id": "message_1"}],
        },
        answering_machine_messages_updated_at=None,
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
            "event": "answering_machine.messages_changed",
            "source": "snapshot",
            "data": {
                "voicemail": {
                    "available": True,
                    "total": 1,
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
    assert event_state.event_sequence == 0
    assert runtime_data.answering_machine_messages["total"] == 1
    assert runtime_data.answering_machine_messages["messages"][0]["id"] == "message_1"
    assert runtime_data.answering_machine_messages_updated_at is not None
    assert signals == [(SIGNAL_VIDEO_MESSAGES_CHANGED, "entry-1")]


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


def test_system_metrics_event_runtime_watchdog_stops_home_call(
    monkeypatch,
) -> None:  # noqa: ANN001
    monkeypatch.setattr(media_watchdog, "AGENT_CPU_WATCHDOG_SECONDS", 0.01)

    class _Api:
        def __init__(self) -> None:
            self.home_call_stop_calls = 0
            self.stop_calls = 0
            self.hangup_calls = 0

        async def async_doorbell_video_status(self) -> dict[str, object]:
            return {
                "media_owner": "unknown",
                "bridge": {"media_owner": "home_call", "home_call_active": True},
            }

        async def async_stop_home_call(self) -> dict[str, object]:
            self.home_call_stop_calls += 1
            return {"ok": True}

        async def async_stop_doorbell_video(self) -> dict[str, object]:
            self.stop_calls += 1
            return {"ok": True}

        async def async_hangup_doorbell_call(self) -> dict[str, object]:
            self.hangup_calls += 1
            return {"ok": True}

    async def _run() -> _Api:
        hass = _FakeHass()
        event_state = C300XEventState()
        api = _Api()
        runtime_data = SimpleNamespace(
            event_state=event_state,
            api=api,
            system_metrics={},
            system_metrics_updated_at=None,
            agent_cpu_watchdog=media_watchdog.AgentCpuWatchdog(),
            agent_cpu_watchdog_task=None,
        )
        entry = SimpleNamespace(
            entry_id="entry-1",
            title="C300X",
            data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
            options={},
            runtime_data=runtime_data,
        )
        for cpu_percent in (95.0, 96.0):
            request = _FakeRequest(
                "event-token",
                {
                    "event": "system.metrics_changed",
                    "data": {"system_metrics": {"cpu_usage_percent": cpu_percent}},
                },
            )
            response = await _async_handle_agent_event(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                event_state,
                request,  # type: ignore[arg-type]
            )
            assert response.status == 200
            await asyncio.sleep(0.02)
        await asyncio.gather(*hass.tasks)
        return api

    api = asyncio.run(_run())

    assert api.home_call_stop_calls == 1
    assert api.hangup_calls == 0
    assert api.stop_calls == 0


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
    original_dispatcher = agent_diagnostics_module.async_dispatcher_send
    webhook_module.async_refresh_agent_diagnostics = _unexpected_refresh  # type: ignore[assignment]
    agent_diagnostics_module.async_dispatcher_send = lambda *args, **kwargs: None  # type: ignore[assignment]
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
        agent_diagnostics_module.async_dispatcher_send = original_dispatcher

    assert response.status == 200
    assert runtime_data.agent_diagnostics["agent_write_count"] == 3
    assert runtime_data.agent_diagnostics_updated_at is not None
    assert event_state.last_event is None
    assert hass.bus.events == []
