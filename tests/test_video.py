from __future__ import annotations

from types import SimpleNamespace

from custom_components.bticino_c300x import video as video_module
from custom_components.bticino_c300x.const import DEFAULT_VIDEO_STREAM_PATH
from custom_components.bticino_c300x.video import (
    TRANSPARENT_CAMERA_PROXY_IMAGE,
    doorbell_camera_unique_id,
    optional_string,
    resolve_doorbell_camera_entity_id,
    safe_optional_stream_path,
    safe_stream_path,
)


def test_transparent_camera_proxy_image_is_png() -> None:
    assert TRANSPARENT_CAMERA_PROXY_IMAGE.startswith(b"\x89PNG\r\n\x1a\n")


def test_doorbell_camera_unique_id_uses_entry_id_suffix() -> None:
    entry = SimpleNamespace(entry_id="abc123")

    assert doorbell_camera_unique_id(entry) == "abc123_doorbell_camera"


def test_resolve_doorbell_camera_entity_id_uses_entity_registry(monkeypatch) -> None:
    entry = SimpleNamespace(entry_id="abc123")
    calls: list[tuple[str, str, str]] = []

    class _Registry:
        def async_get_entity_id(self, domain: str, platform: str, unique_id: str) -> str:
            calls.append((domain, platform, unique_id))
            return "camera.front_door"

    monkeypatch.setattr(video_module.er, "async_get", lambda _hass: _Registry())

    assert resolve_doorbell_camera_entity_id("hass", entry) == "camera.front_door"
    assert calls == [("camera", "bticino_c300x", "abc123_doorbell_camera")]


def test_resolve_doorbell_camera_entity_id_handles_missing_registry(monkeypatch) -> None:
    monkeypatch.setattr(video_module.er, "async_get", lambda _hass: None)

    assert resolve_doorbell_camera_entity_id(
        "hass",
        SimpleNamespace(entry_id="abc123"),
    ) is None


def test_resolve_doorbell_camera_entity_id_ignores_non_string_results(
    monkeypatch,
) -> None:
    class _Registry:
        def async_get_entity_id(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(video_module.er, "async_get", lambda _hass: _Registry())

    assert resolve_doorbell_camera_entity_id(
        "hass",
        SimpleNamespace(entry_id="abc123"),
    ) is None


def test_optional_string_returns_non_empty_text_only() -> None:
    assert optional_string(None) is None
    assert optional_string("") is None
    assert optional_string(123) == "123"


def test_safe_stream_path_never_exposes_rtsp_url() -> None:
    assert safe_stream_path(None) == DEFAULT_VIDEO_STREAM_PATH
    assert safe_stream_path("/doorbell") == "/doorbell"
    assert safe_stream_path("rtsp://device/doorbell") == DEFAULT_VIDEO_STREAM_PATH


def test_safe_optional_stream_path_never_exposes_rtsp_url() -> None:
    assert safe_optional_stream_path(None) is None
    assert safe_optional_stream_path("") is None
    assert safe_optional_stream_path("/doorbell") == "/doorbell"
    assert safe_optional_stream_path("rtsp://device/doorbell") is None
