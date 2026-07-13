from __future__ import annotations

import asyncio
import logging
import sys
import types
from typing import Any

import pytest

from custom_components.bticino_c300x import debug_ws
from custom_components.bticino_c300x.debug_ws import async_register_debug_ws


def test_debug_ws_uses_camera_debug_logger() -> None:
    assert debug_ws._LOGGER.name == "custom_components.bticino_c300x.camera"


class _FakeConnection:
    def __init__(self) -> None:
        self.results: list[tuple[int, Any]] = []

    def send_result(self, msg_id: int, result: Any) -> None:
        self.results.append((msg_id, result))


def test_debug_ws_reports_backend_debug_status(monkeypatch: pytest.MonkeyPatch) -> None:
    registered = _install_debug_ws_stubs(monkeypatch)
    hass = object()
    monkeypatch.setattr(
        debug_ws._LOGGER,
        "isEnabledFor",
        lambda level: level == logging.DEBUG,
    )

    async_register_debug_ws(hass)  # type: ignore[arg-type]

    assert len(registered) == 2
    connection = _FakeConnection()
    asyncio.run(registered[0](hass, connection, {"id": 1}))

    assert connection.results == [
        (1, {"enabled": True, "webrtc_stats": True}),
    ]


def test_debug_ws_keeps_stats_disabled_without_backend_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered = _install_debug_ws_stubs(monkeypatch)
    hass = object()
    monkeypatch.setattr(debug_ws._LOGGER, "isEnabledFor", lambda _level: False)

    async_register_debug_ws(hass)  # type: ignore[arg-type]

    connection = _FakeConnection()
    asyncio.run(registered[0](hass, connection, {"id": 2}))

    assert connection.results == [
        (2, {"enabled": False, "webrtc_stats": False}),
    ]


def test_debug_ws_logs_client_webrtc_stats_in_backend_debug_mode(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered = _install_debug_ws_stubs(monkeypatch)
    hass = object()
    monkeypatch.setattr(
        debug_ws._LOGGER,
        "isEnabledFor",
        lambda level: level == logging.DEBUG,
    )
    caplog.set_level(logging.DEBUG, logger=debug_ws._LOGGER.name)

    async_register_debug_ws(hass)  # type: ignore[arg-type]

    connection = _FakeConnection()
    asyncio.run(
        registered[1](
            hass,
            connection,
            {
                "id": 3,
                "snapshot": {
                    "connection_state": "connected",
                    "event": "tick",
                    "entity_id": "camera.bticino_c300x_doorbell_camera",
                    "ice_connection_state": "connected",
                    "ice_gathering_state": "complete",
                    "inbound": {
                        "video": {
                            "bytesReceivedPerSecond": 1200.4,
                            "framesPerSecond": 25,
                            "framesDecodedPerSecond": 0,
                        }
                    },
                    "outbound": {
                        "audio": {
                            "bytesSentPerSecond": 320.25,
                            "packetsSentPerSecond": 50,
                        }
                    },
                    "media": {
                        "currentTime": 4.5,
                        "currentTimePerSecond": 0,
                        "playbackQuality": {
                            "totalVideoFramesPerSecond": 24,
                        },
                        "readyState": 4,
                    },
                    "mode": "doorbell",
                    "observation": {
                        "connected": True,
                        "decodingProgressing": False,
                        "inboundProgressing": True,
                        "likelyLayer": "browser_decoder",
                        "mediaProgressing": False,
                    },
                    "sequence": 2,
                    "session_id": "1234567890abcdef",
                    "signaling_state": "stable",
                },
            },
        )
    )

    assert connection.results == [(3, {"ok": True})]
    assert "C300X WebRTC client debug:" in caplog.text
    assert "event=tick" in caplog.text
    assert "entity=camera.bticino_c300x_doorbell_camera" in caplog.text
    assert "session=...90abcdef" in caplog.text
    assert "layer=browser_decoder" in caplog.text
    assert "bytes_rate=1200.400" in caplog.text
    assert "frames_per_second=25" in caplog.text
    assert "total_video_frames_rate=24" in caplog.text
    assert "out_audio_bytes_rate=320.250" in caplog.text


def test_debug_ws_logs_client_debug_setup_failures(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered = _install_debug_ws_stubs(monkeypatch)
    hass = object()
    monkeypatch.setattr(
        debug_ws._LOGGER,
        "isEnabledFor",
        lambda level: level == logging.DEBUG,
    )
    caplog.set_level(logging.DEBUG, logger=debug_ws._LOGGER.name)

    async_register_debug_ws(hass)  # type: ignore[arg-type]

    connection = _FakeConnection()
    asyncio.run(
        registered[1](
            hass,
            connection,
            {
                "id": 5,
                "snapshot": {
                    "debug_state": "enabled",
                    "entity_id": "camera.bticino_c300x_doorbell_camera",
                    "event": "debug_setup_failed",
                    "message": "Failed to fetch dynamically imported module",
                    "reason": "module_import_failed",
                },
            },
        )
    )

    assert connection.results == [(5, {"ok": True})]
    assert "event=debug_setup_failed" in caplog.text
    assert "reason=module_import_failed" in caplog.text
    assert "message=Failed_to_fetch_dynamically_imported_module" in caplog.text


def test_debug_ws_acknowledges_client_stats_without_logging_when_debug_disabled(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered = _install_debug_ws_stubs(monkeypatch)
    hass = object()
    monkeypatch.setattr(debug_ws._LOGGER, "isEnabledFor", lambda _level: False)
    caplog.set_level(logging.DEBUG, logger=debug_ws._LOGGER.name)

    async_register_debug_ws(hass)  # type: ignore[arg-type]

    connection = _FakeConnection()
    asyncio.run(
        registered[1](
            hass,
            connection,
            {"id": 4, "snapshot": {"event": "tick"}},
        )
    )

    assert connection.results == [(4, {"ok": True})]
    assert "C300X WebRTC client debug:" not in caplog.text


def _install_debug_ws_stubs(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    registered: list[Any] = []
    components = sys.modules.setdefault(
        "homeassistant.components",
        types.ModuleType("homeassistant.components"),
    )
    websocket_api = types.ModuleType("homeassistant.components.websocket_api")
    websocket_api.websocket_command = lambda _schema: (lambda func: func)
    websocket_api.async_response = lambda func: func
    websocket_api.async_register_command = lambda _hass, command: registered.append(
        command
    )

    monkeypatch.setattr(components, "websocket_api", websocket_api, raising=False)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.websocket_api",
        websocket_api,
    )
    return registered
