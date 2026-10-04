from __future__ import annotations

import pytest

REQUIRED_PROVIDER_METHODS = (
    "async_is_supported",
    "async_handle_async_webrtc_offer",
    "async_on_webrtc_candidate",
)


def _webrtc_module():
    return pytest.importorskip(
        "homeassistant.components.camera.webrtc",
        reason="Home Assistant is not installed in this environment",
    )


def test_webrtc_providers_data_key_still_exists() -> None:
    webrtc = _webrtc_module()

    assert hasattr(webrtc, "DATA_WEBRTC_PROVIDERS"), (
        "Home Assistant no longer exposes DATA_WEBRTC_PROVIDERS; "
        "camera._async_get_supported_webrtc_provider must be reworked"
    )


def test_webrtc_provider_exposes_the_methods_the_camera_calls() -> None:
    webrtc = _webrtc_module()
    provider = getattr(webrtc, "CameraWebRTCProvider", None)

    assert provider is not None, (
        "Home Assistant no longer exposes CameraWebRTCProvider; "
        "the camera's provider delegation must be rechecked"
    )
    missing = [name for name in REQUIRED_PROVIDER_METHODS if not hasattr(provider, name)]
    assert missing == [], (
        f"CameraWebRTCProvider lost methods the camera calls: {missing}"
    )


def test_camera_provider_lookup_degrades_instead_of_raising() -> None:
    import asyncio
    import importlib
    import sys
    from types import SimpleNamespace

    camera_module = importlib.import_module("custom_components.bticino_c300x.camera")
    blocked = "homeassistant.components.camera.webrtc"
    original = sys.modules.get(blocked)
    sys.modules[blocked] = None
    try:
        result = asyncio.run(
            camera_module._async_get_supported_webrtc_provider(
                SimpleNamespace(data={}),
                "rtsp://example.invalid/doorbell",
            )
        )
    finally:
        if original is not None:
            sys.modules[blocked] = original
        else:
            sys.modules.pop(blocked, None)

    assert result is None
