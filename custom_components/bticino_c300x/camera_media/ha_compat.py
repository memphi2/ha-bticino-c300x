"""Camera API locations shared by the supported Home Assistant versions."""

from typing import TYPE_CHECKING, Any

from homeassistant.components import camera as camera_platform
from homeassistant.components.camera import const as camera_const
from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from homeassistant.components.camera.webrtc import WebRTCError, WebRTCSendMessage
else:
    from homeassistant.components.camera import WebRTCError, WebRTCSendMessage

HA_CAMERA_FEATURE_IN_CONST = hasattr(camera_const, "CameraEntityFeature")
if HA_CAMERA_FEATURE_IN_CONST:
    from homeassistant.components.camera.const import CameraEntityFeature
else:
    from homeassistant.components.camera import CameraEntityFeature

# The native microphone capability was added in HA 2026.11.
CameraEntityCapabilities = getattr(camera_platform, "CameraEntityCapabilities", None)

__all__ = (
    "CameraEntityCapabilities",
    "CameraEntityFeature",
    "WebRTCError",
    "WebRTCSendMessage",
    "async_get_supported_webrtc_provider",
)


async def async_get_supported_webrtc_provider(
    hass: HomeAssistant,
    stream_source: str,
) -> Any:
    """Return HA's active WebRTC provider without starting C300X media."""

    try:
        from homeassistant.components.camera.webrtc import (  # noqa: PLC0415
            DATA_WEBRTC_PROVIDERS,
        )
    except ImportError:
        return None

    providers = hass.data.get(DATA_WEBRTC_PROVIDERS)
    if not providers or not stream_source:
        return None
    for provider in providers:
        if provider.async_is_supported(stream_source):
            return provider
    return None
