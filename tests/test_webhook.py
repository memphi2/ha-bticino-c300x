from __future__ import annotations

import asyncio
import datetime
import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from homeassistant.components import webhook


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


from custom_components.bticino_c300x import (  # noqa: E402
    agent_diagnostics as agent_diagnostics_module,
)
from custom_components.bticino_c300x import (  # noqa: E402
    call_sync,
    media_watchdog,
)
from custom_components.bticino_c300x import (  # noqa: E402
    webhook as webhook_module,
)
from custom_components.bticino_c300x._api_calls import (  # noqa: E402
    normalize_outdoor_units,
)
from custom_components.bticino_c300x.call_registry import (  # noqa: E402
    C300XCallRegistry,
)
from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_EVENT_WEBHOOK_TOKEN,
    CONF_SHARED_SECRET,
    EVENT_AGENT_EVENT_RECEIVED,
    HEADER_EVENT_TOKEN,
    HEADER_SHARED_SECRET,
    SIGNAL_MEMOS_CHANGED,
    SIGNAL_SETTING_STATE,
    SIGNAL_SYSTEM_METRICS_CHANGED,
    SIGNAL_VIDEO_MESSAGES_CHANGED,
)
from custom_components.bticino_c300x.data import (  # noqa: E402
    C300XEventState,
    C300XRuntimeDiagnostics,
    C300XRuntimeResources,
)
from custom_components.bticino_c300x.webhook import (  # noqa: E402
    _async_handle_agent_event,
    _async_handle_webhook,
    _event_payload,
    _is_snapshot_payload,
    _optional_bool,
    _optional_int,
    async_register_agent_event_webhook,
    async_register_webhook,
)  # pylint: disable=wrong-import-position

_REQUEST_CONTENT_LENGTH_AUTO = object()


@pytest.mark.parametrize("event", [False, True])
@pytest.mark.parametrize(
    ("expected", "supplied"),
    [("secret", ""), ("secret", "wrong"), ("secret", "\u00e4"),
     ("\u00e4", "\u00e4"), (None, "secret"), (123, "secret")],
)
def test_webhook_rejects_malformed_credentials(event, expected, supplied):
    key = CONF_EVENT_WEBHOOK_TOKEN if event else CONF_SHARED_SECRET
    header = HEADER_EVENT_TOKEN if event else HEADER_SHARED_SECRET
    entry = SimpleNamespace(data={key: expected})
    # No body reader: rejected authentication must not read or process the payload.
    request = SimpleNamespace(headers={header: supplied})
    if event:
        response = asyncio.run(_async_handle_agent_event(None, entry, C300XEventState(), request))
    else:
        response = asyncio.run(_async_handle_webhook(None, entry, request))
    assert response.status == 401


@pytest.fixture(autouse=True)
def webhook_ha_boundary(monkeypatch):
    from homeassistant.helpers import dispatcher, event

    from custom_components.bticino_c300x import repair_issues

    monkeypatch.setattr(webhook, "async_generate_url", _webhook_url)
    monkeypatch.setattr(webhook, "async_generate_path", lambda key: f"/webhook/{key}")
    monkeypatch.setattr(webhook, "async_register", lambda *args, **kwargs: None)
    monkeypatch.setattr(webhook, "async_unregister", lambda *args: None)
    monkeypatch.setattr(webhook_module, "async_dispatcher_send", lambda *_: None)
    monkeypatch.setattr(agent_diagnostics_module, "async_dispatcher_send", lambda *_: None)
    monkeypatch.setattr(dispatcher, "async_dispatcher_send", lambda *_: None)
    monkeypatch.setattr(event, "async_call_later", lambda *_: lambda: None)
    monkeypatch.setattr(repair_issues.ir, "async_create_issue", lambda *args, **kwargs: None)
    monkeypatch.setattr(repair_issues.ir, "async_delete_issue", lambda *args, **kwargs: None)
    monkeypatch.setattr(webhook_module.dt_util, "utcnow", _utcnow)


class _FakeRequestContent:
    def __init__(self, raw: bytes, error: Exception | None) -> None:
        self._raw = raw
        self._error = error

    async def read(self, size: int = -1) -> bytes:
        if self._error is not None:
            raise self._error
        if size is None or size < 0:
            return self._raw
        return self._raw[:size]

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        if self._error is not None:
            raise self._error
        step = max(1, len(self._raw))
        for start in range(0, len(self._raw), step):
            yield self._raw[start : start + step]


class _FakeRequest:
    def __init__(
        self,
        token: str,
        payload: object,
        *,
        method: str = "POST",
        extra_headers: dict[str, str] | None = None,
        json_error: Exception | None = None,
        raw: bytes | None = None,
        content_length: object = _REQUEST_CONTENT_LENGTH_AUTO,
    ) -> None:
        self.method = method
        self.headers = {HEADER_EVENT_TOKEN: token, **(extra_headers or {})}
        self._payload = payload
        self._json_error = json_error
        self._raw = raw if raw is not None else json.dumps(payload).encode()
        self._content_length_override = content_length
        self.content = _FakeRequestContent(self._raw, json_error)

    @property
    def content_length(self) -> int | None:
        if self._content_length_override is _REQUEST_CONTENT_LENGTH_AUTO:
            return len(self._raw)
        return self._content_length_override  # type: ignore[return-value]

    async def json(self) -> object:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


def test_event_payload_rejects_oversized_body_via_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "custom_components.bticino_c300x.webhook._MAX_WEBHOOK_BODY_BYTES", 8
    )
    request = _FakeRequest("token", {"type": "status", "pad": "far too long"})

    assert asyncio.run(_event_payload(request)) == {}


def test_event_payload_rejects_oversized_body_via_read_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "custom_components.bticino_c300x.webhook._MAX_WEBHOOK_BODY_BYTES", 8
    )
    # content_length withheld (chunked) -> the bounded read must reject it.
    request = _FakeRequest(
        "token",
        {"type": "status"},
        raw=b'{"type":"status"}',
        content_length=None,
    )

    assert asyncio.run(_event_payload(request)) == {}


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


@pytest.mark.parametrize(
    ("code", "error", "expected"),
    [
        ("1234", "alarm_state_unchanged", "invalid_code"),
        (None, "alarm_state_unchanged", "alarm_state_unchanged"),
        ("1234", "not_ready_to_arm", "not_ready_to_arm"),
        ("1234", "alarm_command_rejected", "alarm_command_rejected"),
    ],
)
def test_display_keypad_keeps_wrong_pin_hint_for_silent_providers(
    monkeypatch, code, error, expected  # noqa: ANN001
) -> None:
    """Only an unchanged state after a typed PIN reads as a wrong PIN."""

    hass = _FakeHass()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_SHARED_SECRET: "shared-secret"},
        options={},
    )

    async def _alarm_command(*args: object, **kwargs: object) -> dict:
        return {"ok": False, "error": error, "command": "disarm", "state": "armed_away"}

    monkeypatch.setattr(webhook_module, "async_execute_alarm_command", _alarm_command)
    payload = {"type": "alarm_command", "command": "disarm"}
    if code is not None:
        payload["code"] = code
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

    body = json.loads(response.text)
    assert body["error"] == expected
    assert body["state"] == "armed_away"


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
            _FakeRequest("bad-token", {"type": "ringer.muted"}),  # type: ignore[arg-type]
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


def test_agent_event_webhook_reads_only_the_agents_dotted_type() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=SimpleNamespace(event_state=event_state),
    )

    for payload in (
        {"type": "ringer_muted"}, {"type": "Ringer Muted"}, {"type": "ringer:muted"},
        {"event": "ringer.muted"}, {"event_type": "ringer.muted"},
        {"event_key": "ringer_muted"}, {"data": {"type": "ringer.muted"}},
    ):
        response = asyncio.run(
            _async_handle_agent_event(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                event_state,
                _FakeRequest("event-token", payload),  # type: ignore[arg-type]
            )
        )
        assert response.status == 400, payload
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
            "type": "doorbell.media.closed",
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
    assert event_state.last_event_data["event_type"] == "doorbell_media_closed"
    assert event_state.last_event_data["doorbell"] == "idle"
    assert hass.bus.events[-1][1]["event_type"] == "doorbell_media_closed"


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
        {"type": "doorbell.pressed", "event_id": "native-boot-42", "data": {"doorbell": "ringing"}},
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
    assert event_state.last_event_data["source_event_id"] == "native-boot-42"


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
    request = _FakeRequest("event-token", {"type": "ringer.muted"})

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
    assert hass.bus.events[-1][1]["event_type"] == "ringer_muted"
    # The stable key only: no label in any language, no duplicate of the key.
    assert not {"event", "event_key", "event_type_key", "event_name", "event_value", "event_label"} & set(
        hass.bus.events[-1][1]
    )
    assert not [key for key in hass.bus.events[-1][1] if key.startswith("event_label_")]


def test_ringer_volume_event_updates_state_and_public_event_data() -> None:
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
        {"type": "ringer.volume_changed", "data": {"volume": 7}},
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
    assert event_state.ringer_volume == 7
    assert event_state.last_event_data["volume"] == 7
    assert hass.bus.events[-1][1]["event_type"] == "ringer_volume_changed"


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
        {"type": "smartphone_forwarding.changed", "data": {"mode": 2}},
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


def test_smartphone_forwarding_event_preserves_unprovisioned_state() -> None:
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
        {"type": "smartphone_forwarding.changed", "data": {"mode": 3}},
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
    assert event_state.smartphone_forwarding_mode == "unprovisioned"
    assert event_state.last_event_data["mode"] == "unprovisioned"


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
        {"type": "door_unlock.started", "data": {"address": "20"}},
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
    assert event_state.last_event_data["data"]["address"] == "20"
    assert "address" not in event_state.last_event_data


def test_stair_light_release_event_keeps_address_in_public_event_data() -> None:
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
        {"type": "stair_light.released", "data": {"address": "21"}},
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
    assert event_state.last_event_data["event_type"] == "stair_light_released"
    assert event_state.last_event_data["data"]["address"] == "21"


def test_call_events_feed_the_call_registry_and_name_the_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    registry = C300XCallRegistry()
    registry.set_units(normalize_outdoor_units({"default_unit": "20", "units": [
        {"id": "20", "where": "20", "name": "Gate", "default": True},
        {"id": "21", "where": "21", "name": "Garden"},
    ]}))
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={},
        runtime_data=SimpleNamespace(event_state=event_state, calls=registry),
    )
    hass.async_create_background_task = lambda coro, name: coro.close()  # type: ignore[attr-defined]
    signals: list[tuple] = []
    monkeypatch.setattr(call_sync, "async_dispatcher_send", lambda *args: signals.append(args))
    monkeypatch.setattr(webhook_module, "resolve_doorbell_camera_entity_id", lambda _hass, _entry: None)
    fired: list[dict] = []
    hass.bus.async_fire = lambda event_type, data: fired.append(data)  # type: ignore[method-assign]

    def send(event: str, data: dict) -> None:
        response = asyncio.run(
            _async_handle_agent_event(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                event_state,
                _FakeRequest("event-token", {"type": event, "data": data}),  # type: ignore[arg-type]
            )
        )
        assert response.status == 200

    send("doorbell.pressed", {"call_id": "0badc0de-1", "unit": None, "attribution": "pending"})
    assert fired[-1]["call_id"] == "0badc0de-1" and fired[-1]["unit"] is None
    send("call.caller_identified", {"call_id": "0badc0de-1", "unit": "21", "attribution": "caller_frame"})
    assert fired[-1]["unit"] == "21" and "unit_name" not in fired[-1]
    assert registry.unit_state("21") == ("ringing", "0badc0de-1")
    # A second unit rings: its own call, which becomes the current one.
    send("doorbell.pressed", {"call_id": "0badc0de-2", "unit": "20", "attribution": "caller_frame"})
    assert registry.current_call_id == "0badc0de-2"
    send("call.answered", {"call_id": "0badc0de-1", "unit": "21", "answered_by": "station"})
    assert registry.current_call_id == "0badc0de-1"
    send("door_unlock.started", {"address": "21", "unit": "21", "call_id": "0badc0de-1"})
    assert (fired[-1]["call_id"], fired[-1]["unit"], fired[-1]["device_id"]) == ("0badc0de-1", "21", "device-unit-21")
    # A door opened outside a call names its unit too.
    send("door_unlock.started", {"address": "20", "unit": "20", "call_id": None})
    assert (fired[-1]["call_id"], fired[-1]["unit"], fired[-1]["device_id"]) == (None, "20", "device-unit-20")
    send("call.ended", {"call_id": "0badc0de-1", "unit": "21", "kind": "ring", "reason": "hangup"})
    assert registry.unit_state("21") == ("idle", None)
    assert registry.current_call_id == "0badc0de-2"

def test_station_call_state_and_door_contact_events_reach_the_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent's new call hub events are station events like any other."""

    hass = _FakeHass()
    event_state = C300XEventState()
    registry = C300XCallRegistry()
    registry.set_units(normalize_outdoor_units({"default_unit": "20", "units": [
        {"id": "20", "where": "20", "name": "Gate", "default": True, "door": {"state": None, "age_ms": None}},
    ]}))
    entry = SimpleNamespace(
        entry_id="entry-1", title="C300X", data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"}, options={},
        runtime_data=SimpleNamespace(event_state=event_state, calls=registry),
    )
    hass.async_create_background_task = lambda coro, name: coro.close()  # type: ignore[attr-defined]
    monkeypatch.setattr(call_sync, "async_dispatcher_send", lambda *args: None)
    fired: list[tuple[str, dict]] = []
    hass.bus.async_fire = lambda event_type, data: fired.append((event_type, data))  # type: ignore[method-assign]

    def send(event: str, data: dict) -> None:
        response = asyncio.run(
            _async_handle_agent_event(
                hass,  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                event_state,
                _FakeRequest("event-token", {"type": event, "data": data}),  # type: ignore[arg-type]
            )
        )
        assert response.status == 200, event

    send("station.call_state", {"code": 2, "state": "ringing"})
    name, data = fired[-1]
    assert name == "bticino_c300x_agent_event_received"
    assert (data["event_type"], data["unit"], data["data"]) == ("station_call_state", None, {"code": 2, "state": "ringing"})
    send("door.opened", {"unit": "20", "where": "20", "raw": "*8*66*20##"})
    assert (fired[-1][1]["event_type"], fired[-1][1]["unit"], fired[-1][1]["device_id"]) == (
        "door_opened", "20", "device-unit-20")
    send("door.closed", {"unit": "20", "where": "20", "raw": "*8*65*20##"})
    assert (fired[-1][1]["event_type"], fired[-1][1]["unit"]) == ("door_closed", "20")


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
            "type": "doorbell.view_requested",
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
            "type": "doorbell.view_requested",
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
            "type": "doorbell.view_requested",
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
            "type": "doorbell.view_requested",
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
            "type": "doorbell.pressed",
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


@pytest.mark.parametrize("snapshot", [None, False, True])
@pytest.mark.parametrize("enabled", [None, False, True])
def test_touch_tone_snapshots_refresh_only_internal_state(monkeypatch, snapshot, enabled):
    hass = _FakeHass()
    event_state = C300XEventState()
    entry = SimpleNamespace(
        entry_id="entry-1", title="C300X", options={},
        data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        runtime_data=SimpleNamespace(event_state=event_state),
    )
    data = {"ok": True, "available": enabled is not None, "enabled": enabled}
    payload = {"type": "display.touch_tone_changed", "data": data}
    if snapshot is not None:
        payload["snapshot"] = snapshot
    signals = []
    monkeypatch.setattr(webhook_module, "async_dispatcher_send",
                        lambda _hass, *args: signals.append(args))
    response = asyncio.run(_async_handle_agent_event(
        hass, entry, event_state, _FakeRequest("event-token", payload),
    ))
    assert response.status == 200
    if snapshot:
        assert signals == [(SIGNAL_SETTING_STATE, entry.entry_id, "display_touch_tone_changed", data)]
        assert hass.bus.events == []
        assert event_state.event_sequence == 0
        assert event_state.last_event is None
        assert event_state.last_event_data == {}
    else:
        assert signals == []
        assert len(hass.bus.events) == 1
        topic, event = hass.bus.events[0]
        assert topic == EVENT_AGENT_EVENT_RECEIVED
        assert event["event_type"] == "display_touch_tone_changed"
        assert event["data"] == data
        assert event_state.event_sequence == 1


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
            "type": "memos.changed",
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
    assert runtime_data.memos["memos"] == []
    assert runtime_data.memos_updated_at is None
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
            "type": "answering_machine.messages_changed",
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
    assert runtime_data.answering_machine_messages["messages"] == []
    assert runtime_data.answering_machine_messages_updated_at is None
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
            "type": "system.metrics_changed",
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


def test_system_metrics_webhook_rejects_invalid_metadata_and_ignores_old_samples() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    runtime = SimpleNamespace(event_state=event_state, system_metrics={}, system_metrics_updated_at=None)
    entry = SimpleNamespace(
        entry_id="entry-1", title="C300X", data={CONF_EVENT_WEBHOOK_TOKEN: "event-token"},
        options={}, runtime_data=runtime,
    )
    metrics = {
        "instance_id": "a" * 32, "sample_sequence": 2,
        "sample_age_ms": 0, "sample_interval_ms": 30000,
        "sample_interval_seconds": 30, "heartbeat_seconds": 600,
        "cpu_usage_percent": 1.0,
    }
    for payload, status in (
        (metrics, 200),
        ({**metrics, "sample_sequence": 1, "cpu_usage_percent": 20.0}, 200),
        ({**metrics, "sample_age_ms": -1}, 400),
    ):
        request = _FakeRequest("event-token", {
            "type": "system.metrics_changed", "data": {"system_metrics": payload},
        })
        response = asyncio.run(_async_handle_agent_event(hass, entry, event_state, request))
        assert response.status == status
        assert runtime.system_metrics["cpu_usage_percent"] == 1.0


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
            resources=C300XRuntimeResources(agent_cpu_watchdog_task=None),
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
                    "type": "system.metrics_changed",
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


def test_metrics_subscribers_see_current_watchdog_before_closing_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from custom_components.bticino_c300x.camera_media.background_tasks import (
        CameraBackgroundTasks,
    )

    async def run() -> None:
        hass = _FakeHass()
        runtime = SimpleNamespace(
            api=None,
            system_metrics={},
            system_metrics_updated_at=None,
            agent_cpu_watchdog=media_watchdog.AgentCpuWatchdog(
                high_since=asyncio.get_running_loop().time() - 301,
            ),
            resources=C300XRuntimeResources(agent_cpu_watchdog_task=None),
        )
        entry = SimpleNamespace(entry_id="entry-1", runtime_data=runtime)
        close_session = AsyncMock()
        camera = SimpleNamespace(
            _entry=entry,
            _runtime_data=runtime,
            _background_tasks=CameraBackgroundTasks(),
            hass=hass,
            _webrtc_session_ids=lambda: ["session"],
            _async_close_webrtc_session=close_session,
            _async_write_ha_state_if_ready=lambda: None,
        )
        observed = []

        def notify(_hass, signal, entry_id):
            assert signal == SIGNAL_SYSTEM_METRICS_CHANGED
            observed.append((
                runtime.system_metrics["cpu_usage_percent"],
                runtime.agent_cpu_watchdog.tripped,
            ))
            media_watchdog.handle_agent_cpu_metrics_changed(camera, entry_id)

        # Cover both the cache's dispatcher and the webhook's dispatcher so a
        # premature or duplicate notification also fails this test.
        monkeypatch.setattr(webhook_module, "async_dispatcher_send", notify)
        monkeypatch.setattr(
            sys.modules["homeassistant.helpers.dispatcher"],
            "async_dispatcher_send", notify,
        )
        monkeypatch.setattr(
            sys.modules["homeassistant.helpers.event"],
            "async_call_later", lambda *_args: lambda: None,
        )
        base = {
            "instance_id": "a" * 32, "sample_sequence": 1,
            "sample_age_ms": 0, "sample_interval_ms": 30000,
            "sample_interval_seconds": 30, "heartbeat_seconds": 600,
            "cpu_usage_percent": 95.0,
        }
        assert webhook_module._apply_system_metrics_event(hass, entry, base)
        await asyncio.gather(*hass.tasks)
        assert observed == [(95.0, True)]
        assert close_session.await_count == 1

        recovery = {**base, "sample_sequence": 2, "cpu_usage_percent": 1.0}
        assert webhook_module._apply_system_metrics_event(hass, entry, recovery)
        assert webhook_module._apply_system_metrics_event(hass, entry, base)
        expired = {**base, "sample_sequence": 3, "sample_age_ms": 700000}
        assert webhook_module._apply_system_metrics_event(hass, entry, expired)
        assert not webhook_module._apply_system_metrics_event(
            hass, entry, {**base, "sample_sequence": 4, "sample_age_ms": -1},
        )
        await asyncio.gather(*hass.tasks)
        assert observed == [(95.0, True), (1.0, False), (95.0, False)]
        assert close_session.await_count == 1
        assert runtime.agent_cpu_watchdog.high_since is None
        assert runtime.agent_cpu_watchdog.trigger_count == 1

    asyncio.run(run())


def test_agent_diagnostics_event_refreshes_cache_without_public_event() -> None:
    hass = _FakeHass()
    event_state = C300XEventState()
    runtime_data = SimpleNamespace(
        event_state=event_state,
        capabilities={"diagnostics": {"supported": True, "writes": True}},
        diagnostics=C300XRuntimeDiagnostics(
            agent_diagnostics={}, agent_diagnostics_updated_at=None
        ),
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
            "type": "agent.diagnostics_changed",
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
    assert runtime_data.diagnostics.agent_diagnostics["agent_write_count"] == 3
    assert runtime_data.diagnostics.agent_diagnostics_updated_at is not None
    assert event_state.last_event is None
    assert hass.bus.events == []


def test_unparseable_forwarding_push_does_not_announce_the_old_mode() -> None:
    """The store deliberately keeps the last known mode when a push cannot be
    parsed. The public event must not hand that old value to automations as if
    it were the new one -- they trigger on "changed"."""

    event_state = C300XEventState(smartphone_forwarding_mode="blocked")
    context = webhook_module._AgentEventContext(
        hass=SimpleNamespace(config=SimpleNamespace(language="en")),
        entry=SimpleNamespace(entry_id="entry-1"),
        event_state=event_state,
        event_type="smartphone_forwarding_changed",
        payload={},
        data={},
    )

    webhook_module._apply_smartphone_forwarding_event(context)
    event_data = webhook_module._event_data(context, "2026-08-23T00:00:00+00:00")

    # Kept as best-known state ...
    assert event_state.smartphone_forwarding_mode == "blocked"
    # ... but not announced as a change.
    assert event_data["mode"] is None


@pytest.mark.parametrize(
    ("event", "key", "task_attr"),
    [
        ("memos.changed", "memos", "memos_refresh_task"),
        ("answering_machine.messages_changed", "voicemail", "answering_machine_messages_refresh_task"),
    ],
)
def test_a_snapshot_schedules_the_read_that_brings_the_items_back(event, key, task_attr) -> None:
    """The snapshot empties the item list; without a read it stays empty."""

    async def run() -> object:
        hass = _FakeHass()
        event_state = C300XEventState()
        runtime_data = SimpleNamespace(
            event_state=event_state,
            memos={"available": True, "memos": [{"id": "text/1", "kind": "text"}]},
            memos_updated_at=None,
            answering_machine_messages={"available": True, "messages": [{"id": "m1"}]},
            answering_machine_messages_updated_at=None,
            resources=C300XRuntimeResources(),
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
            {"type": event, "snapshot": True, "data": {key: {"available": True, "total": 1}}},
        )
        response = await _async_handle_agent_event(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            event_state,
            request,  # type: ignore[arg-type]
        )
        task = getattr(runtime_data.resources, task_attr)
        for pending in hass.tasks:
            pending.cancel()
        assert response.status == 200
        return task

    assert asyncio.run(run()) is not None


def _display_setting_call(hass: object, entry: object, payload: object, secret: str = "shared-secret") -> tuple[int, dict]:
    response = asyncio.run(
        _async_handle_webhook(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            _FakeRequest("", payload, extra_headers={HEADER_SHARED_SECRET: secret} if secret else None),  # type: ignore[arg-type]
        )
    )
    return response.status, json.loads(response.body)


def test_display_bridge_stores_only_the_two_display_settings() -> None:
    """The station's Integration tab may change two options and nothing else."""

    updates: list[dict] = []
    hass = _FakeHass()
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_SHARED_SECRET: "shared-secret", "api_token": "keep", "dashboard_navigation": "tabs"},
        options={"snapshot_width": 640},
    )

    def update_entry(target: object, *, options: dict) -> None:
        assert target is entry
        updates.append(dict(options))
        entry.options = dict(options)

    hass.config_entries = SimpleNamespace(async_update_entry=update_entry)

    def call(key: object, value: object, **more: object) -> tuple[int, dict]:
        return _display_setting_call(hass, entry, {"type": "display_setting", "key": key, "value": value, **more})

    assert call("dashboard_navigation", "pager") == (
        200, {"ok": True, "preventReturnToHomepage": True, "navigation": "pager"}
    )
    assert call("dashboard_prevent_return", "off") == (
        200, {"ok": True, "preventReturnToHomepage": False, "navigation": "pager"}
    )
    assert call("dashboard_prevent_return", "on")[1]["preventReturnToHomepage"] is True
    assert call("dashboard_navigation", "tabs")[1]["navigation"] == "tabs"
    # The stored value is what the options form and the display read.
    assert entry.options == {"snapshot_width": 640, "dashboard_navigation": "tabs", "dashboard_prevent_return": True}
    assert len(updates) == 4
    # A repeated value is confirmed without another write.
    assert call("dashboard_navigation", "tabs")[0] == 200 and len(updates) == 4

    before = (dict(entry.options), dict(entry.data))
    for key, value in [
        ("api_token", "x"), ("shared_secret", "x"), ("snapshot_width", "1"), ("actions", "{}"),
        ("device_ui_enabled", "off"), ("status_page_enabled", "off"), ("dashboard_entities", "light.a"),
        ("dashboard_navigation", "TABS"), ("dashboard_navigation", ""), ("dashboard_navigation", "on"),
        ("dashboard_navigation", ["tabs"]), ("dashboard_prevent_return", True), ("dashboard_prevent_return", "1"),
        ("dashboard_prevent_return", "pager"), ("dashboard_prevent_return", None), (None, "on"),
        (["dashboard_navigation"], "tabs"), ("dashboard_navigation ", "tabs"), ("__class__", "on"),
    ]:
        assert call(key, value) == (400, {"ok": False, "error": "invalid_display_setting"}), (key, value)
    # Extra fields ride along with an allowed pair but are never stored.
    assert call("dashboard_navigation", "pager", options={"api_token": "x"}, api_token="x")[0] == 200
    assert entry.options == {**before[0], "dashboard_navigation": "pager"} and entry.data == before[1]
    writes = len(updates)
    payload = {"type": "display_setting", "key": "dashboard_navigation", "value": "tabs"}
    assert _display_setting_call(hass, entry, payload, secret="")[0] == 401
    assert _display_setting_call(hass, entry, payload, secret="wrong")[0] == 401
    assert len(updates) == writes and entry.options["dashboard_navigation"] == "pager"


def test_display_status_carries_what_the_integration_tab_shows() -> None:
    hass = _FakeHass()
    hass.states = SimpleNamespace(get=lambda _entity_id: None)
    hass.config = SimpleNamespace(language=None, location_name="Zuhause")
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={CONF_SHARED_SECRET: "shared-secret", "api_token": "token-1", "webhook_id": "hook-1"},
        options={"dashboard_navigation": "pager", "dashboard_prevent_return": False},
    )
    status, body = _display_setting_call(hass, entry, {"type": "status"})
    assert status == 200
    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "custom_components/bticino_c300x/manifest.json").read_text()
    )
    assert body["integration_version"] == manifest["version"]
    assert body["instance_name"] == "Zuhause"
    assert body["navigation"] == "pager" and body["preventReturnToHomepage"] is False
    text = json.dumps(body)
    assert "shared-secret" not in text and "token-1" not in text and "hook-1" not in text
