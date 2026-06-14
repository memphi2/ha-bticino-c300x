from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest
import voluptuous as vol

from custom_components.bticino_c300x.camera_media import home_call_ws
from custom_components.bticino_c300x.camera_media.home_call_ws import (
    async_register_home_call_ws,
    parse_home_call_candidate,
)


def test_parse_home_call_candidate_accepts_frontend_shape() -> None:
    candidate = parse_home_call_candidate(
        {
            "candidate": "candidate:1 1 udp 2122260223 192.0.2.10 5000 typ host",
            "sdpMid": "0",
            "sdpMLineIndex": 0,
        }
    )

    assert candidate.candidate.startswith("candidate:1 1 udp")
    assert candidate.sdpMid == "0"
    assert candidate.sdpMLineIndex == 0


def test_parse_home_call_candidate_defaults_missing_fields() -> None:
    candidate = parse_home_call_candidate({})

    assert candidate.candidate == ""
    assert candidate.sdpMid is None
    assert candidate.sdpMLineIndex is None


def test_parse_home_call_candidate_rejects_non_object() -> None:
    with pytest.raises(vol.Invalid):
        parse_home_call_candidate("candidate")


def test_home_call_ws_get_client_config_and_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    camera = _FakeHomeCallCamera()
    registered = _install_home_call_ws_stubs(monkeypatch, camera)
    hass = object()

    async_register_home_call_ws(hass, _FakeHomeCallCamera)  # type: ignore[arg-type]

    assert len(registered) == 3
    connection = _FakeConnection()
    asyncio.run(
        registered[0](
            hass,
            connection,
            {"id": 1, "entity_id": "camera.c300x"},
        )
    )
    asyncio.run(
        registered[2](
            hass,
            connection,
            {
                "id": 2,
                "entity_id": "camera.c300x",
                "session_id": "session-1",
                "candidate": SimpleNamespace(candidate="candidate"),
            },
        )
    )

    assert connection.results == [(1, {"iceServers": []})]
    assert connection.messages[-1] == {"id": 2, "type": "result", "success": True}
    assert camera.candidates == [("session-1", "candidate")]


def test_home_call_ws_reports_missing_camera(monkeypatch: pytest.MonkeyPatch) -> None:
    registered = _install_home_call_ws_stubs(monkeypatch, None)
    hass = object()

    async_register_home_call_ws(hass, _FakeHomeCallCamera)  # type: ignore[arg-type]
    connection = _FakeConnection()
    asyncio.run(
        registered[0](
            hass,
            connection,
            {"id": 1, "entity_id": "camera.other"},
        )
    )
    asyncio.run(
        registered[2](
            hass,
            connection,
            {
                "id": 2,
                "entity_id": "camera.other",
                "session_id": "session-1",
                "candidate": SimpleNamespace(candidate="candidate"),
            },
        )
    )

    assert connection.errors == [
        (1, "home_call_webrtc_not_found", "C300X doorbell camera entity not found"),
        (2, "home_call_webrtc_not_found", "C300X doorbell camera entity not found"),
    ]


def test_home_call_ws_offer_reports_missing_camera(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered = _install_home_call_ws_stubs(monkeypatch, None)
    hass = object()

    async_register_home_call_ws(hass, _FakeHomeCallCamera)  # type: ignore[arg-type]
    connection = _FakeConnection()
    asyncio.run(
        registered[1](
            hass,
            connection,
            {"id": 3, "entity_id": "camera.other", "offer": "v=0"},
        )
    )

    assert connection.errors == [
        (3, "home_call_webrtc_not_found", "C300X doorbell camera entity not found"),
    ]
    assert connection.subscriptions == {}


def test_home_call_ws_offer_registers_subscription_and_sends_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = _FakeHomeCallCamera()
    registered = _install_home_call_ws_stubs(monkeypatch, camera)
    hass = object()

    async_register_home_call_ws(hass, _FakeHomeCallCamera)  # type: ignore[arg-type]
    connection = _FakeConnection()
    asyncio.run(
        registered[1](
            hass,
            connection,
            {
                "id": 5,
                "entity_id": "camera.c300x",
                "offer": "v=0",
                "duration_seconds": 30,
            },
        )
    )

    assert 5 in connection.subscriptions
    assert connection.messages[0] == {"id": 5, "type": "result", "success": True}
    assert connection.messages[1]["event"]["type"] == "session"
    assert camera.offers == [("v=0", "01TEST", 30)]

    connection.subscriptions[5]()

    assert camera.closed_sessions == ["01TEST"]


def test_home_call_ws_offer_maps_homeassistant_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    camera = _FakeHomeCallCamera(fail_offer=True)
    registered = _install_home_call_ws_stubs(monkeypatch, camera)
    hass = object()

    async_register_home_call_ws(hass, _FakeHomeCallCamera)  # type: ignore[arg-type]
    connection = _FakeConnection()
    asyncio.run(
        registered[1](
            hass,
            connection,
            {"id": 6, "entity_id": "camera.c300x", "offer": "v=0"},
        )
    )

    assert connection.messages[-1]["event"] == {
        "type": "error",
        "code": "home_call_webrtc_offer_failed",
        "message": "offer failed",
    }


class _FakeHomeCallCamera:
    def __init__(self, *, fail_offer: bool = False) -> None:
        self.fail_offer = fail_offer
        self.candidates: list[tuple[str, str]] = []
        self.closed_sessions: list[str] = []
        self.offers: list[tuple[str, str, int | None]] = []

    def async_get_webrtc_client_configuration(self) -> SimpleNamespace:
        return SimpleNamespace(to_frontend_dict=lambda: {"iceServers": []})

    def close_webrtc_session(self, session_id: str) -> None:
        self.closed_sessions.append(session_id)

    async def async_handle_home_call_webrtc_offer(
        self,
        offer: str,
        session_id: str,
        send_message: Any,
        *,
        duration_seconds: int | None,
    ) -> None:
        self.offers.append((offer, session_id, duration_seconds))
        if self.fail_offer:
            raise home_call_ws.HomeAssistantError("offer failed")  # type: ignore[attr-defined]
        send_message({"type": "answer", "sdp": "v=0"})

    async def async_on_webrtc_candidate(
        self,
        session_id: str,
        candidate: Any,
    ) -> None:
        self.candidates.append((session_id, candidate.candidate))


class _FakeConnection:
    def __init__(self) -> None:
        self.subscriptions: dict[int, Any] = {}
        self.results: list[tuple[int, Any]] = []
        self.errors: list[tuple[int, str, str]] = []
        self.messages: list[dict[str, Any]] = []

    def send_result(self, msg_id: int, result: Any) -> None:
        self.results.append((msg_id, result))

    def send_error(self, msg_id: int, code: str, message: str) -> None:
        self.errors.append((msg_id, code, message))

    def send_message(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


def _install_home_call_ws_stubs(
    monkeypatch: pytest.MonkeyPatch,
    camera: _FakeHomeCallCamera | None,
) -> list[Any]:
    registered: list[Any] = []
    components = sys.modules.setdefault(
        "homeassistant.components",
        types.ModuleType("homeassistant.components"),
    )
    websocket_api = types.ModuleType("homeassistant.components.websocket_api")
    camera_module = types.ModuleType("homeassistant.components.camera")
    camera_helper = types.ModuleType("homeassistant.components.camera.helper")
    camera_webrtc = types.ModuleType("homeassistant.components.camera.webrtc")
    core_module = sys.modules.setdefault(
        "homeassistant.core",
        types.ModuleType("homeassistant.core"),
    )
    exceptions_module = sys.modules.setdefault(
        "homeassistant.exceptions",
        types.ModuleType("homeassistant.exceptions"),
    )
    helpers = sys.modules.setdefault(
        "homeassistant.helpers",
        types.ModuleType("homeassistant.helpers"),
    )
    config_validation = sys.modules.setdefault(
        "homeassistant.helpers.config_validation",
        types.ModuleType("homeassistant.helpers.config_validation"),
    )
    util_module = sys.modules.setdefault(
        "homeassistant.util",
        types.ModuleType("homeassistant.util"),
    )
    ulid_module = types.ModuleType("homeassistant.util.ulid")

    class HomeAssistantError(Exception):
        pass

    class WebRTCError:
        def __init__(self, code: str, message: str) -> None:
            self.code = code
            self.message = message

        def as_dict(self) -> dict[str, str]:
            return {"type": "error", "code": self.code, "message": self.message}

    class WebRTCSession:
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id

        def as_dict(self) -> dict[str, str]:
            return {"type": "session", "session_id": self.session_id}

    websocket_api.websocket_command = lambda _schema: (lambda func: func)
    websocket_api.async_response = lambda func: func
    websocket_api.async_register_command = lambda _hass, command: registered.append(
        command
    )
    websocket_api.result_message = lambda msg_id: {
        "id": msg_id,
        "type": "result",
        "success": True,
    }
    websocket_api.event_message = lambda msg_id, event: {
        "id": msg_id,
        "type": "event",
        "event": event,
    }
    camera_module.WebRTCError = WebRTCError
    camera_helper.get_camera_from_entity_id = lambda _hass, _entity_id: camera
    camera_webrtc.WebRTCSession = WebRTCSession
    core_module.callback = lambda func: func
    exceptions_module.HomeAssistantError = HomeAssistantError
    config_validation.entity_id = str
    ulid_module.ulid = lambda: "01TEST"

    monkeypatch.setattr(components, "websocket_api", websocket_api, raising=False)
    monkeypatch.setattr(components, "camera", camera_module, raising=False)
    monkeypatch.setattr(helpers, "config_validation", config_validation, raising=False)
    monkeypatch.setattr(util_module, "ulid", ulid_module, raising=False)
    monkeypatch.setitem(sys.modules, "homeassistant.components.websocket_api", websocket_api)
    monkeypatch.setitem(sys.modules, "homeassistant.components.camera", camera_module)
    monkeypatch.setitem(sys.modules, "homeassistant.components.camera.helper", camera_helper)
    monkeypatch.setitem(sys.modules, "homeassistant.components.camera.webrtc", camera_webrtc)
    monkeypatch.setitem(sys.modules, "homeassistant.util.ulid", ulid_module)
    monkeypatch.setattr(home_call_ws, "HomeAssistantError", HomeAssistantError, raising=False)
    return registered
