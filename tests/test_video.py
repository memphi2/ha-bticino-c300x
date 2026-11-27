from __future__ import annotations

from types import SimpleNamespace

from custom_components.bticino_c300x import video as video_module
from custom_components.bticino_c300x.const import DEFAULT_VIDEO_STREAM_PATH
from custom_components.bticino_c300x.value_parsing import optional_string
from custom_components.bticino_c300x.video import (
    TRANSPARENT_CAMERA_PROXY_IMAGE,
    doorbell_camera_unique_id,
    resolve_doorbell_camera_entity_id,
    safe_stream_path,
)


def test_transparent_camera_proxy_image_is_png() -> None:
    assert TRANSPARENT_CAMERA_PROXY_IMAGE.startswith(b"\x89PNG\r\n\x1a\n")


_ENTRY_DATA = {
    "station_id": "c300x-0123456789ab",
    "outdoor_units": {"default_unit": "20", "units": [{"id": "20", "where": "20", "default": True}]},
}


def test_doorbell_camera_unique_id_is_the_default_units_camera() -> None:
    entry = SimpleNamespace(entry_id="abc123", data=_ENTRY_DATA)

    assert doorbell_camera_unique_id(entry) == "c300x-0123456789ab_unit_20_camera"
    # Before the station named its units there is no media camera.
    assert doorbell_camera_unique_id(SimpleNamespace(entry_id="abc123", data={})) is None


def test_resolve_doorbell_camera_entity_id_uses_entity_registry(monkeypatch) -> None:
    entry = SimpleNamespace(entry_id="abc123", data=_ENTRY_DATA)
    calls: list[tuple[str, str, str]] = []

    class _Registry:
        def async_get_entity_id(self, domain: str, platform: str, unique_id: str) -> str:
            calls.append((domain, platform, unique_id))
            return "camera.front_door"

    monkeypatch.setattr(video_module.er, "async_get", lambda _hass: _Registry())

    assert resolve_doorbell_camera_entity_id("hass", entry) == "camera.front_door"
    assert calls == [("camera", "bticino_c300x", "c300x-0123456789ab_unit_20_camera")]
    assert resolve_doorbell_camera_entity_id("hass", SimpleNamespace(entry_id="abc123", data={})) is None
    assert len(calls) == 1


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


def test_optional_string_strips_and_returns_non_empty_text_only() -> None:
    assert optional_string(None) is None
    assert optional_string("") is None
    assert optional_string("   ") is None
    assert optional_string(" x ") == "x"
    assert optional_string(123) == "123"


def test_safe_stream_path_never_exposes_rtsp_url() -> None:
    assert safe_stream_path(None) == DEFAULT_VIDEO_STREAM_PATH
    assert safe_stream_path("/doorbell") == "/doorbell"
    assert safe_stream_path("rtsp://device/doorbell") == DEFAULT_VIDEO_STREAM_PATH
