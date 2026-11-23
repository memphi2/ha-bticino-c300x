"""Camera API locations shared by the supported Home Assistant versions."""

from typing import TYPE_CHECKING, Any

from homeassistant.components import camera as camera_platform
from homeassistant.components.camera import const as camera_const
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.core import HomeAssistant

from ..value_parsing import freeze_state_value

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
HA_SUPPORTS_NATIVE_CAMERA_TWO_WAY_AUDIO = (
    (MAJOR_VERSION, MINOR_VERSION) >= (2026, 11)
    and CameraEntityCapabilities is not None
)

__all__ = (
    "CameraEntityCapabilities",
    "HA_SUPPORTS_NATIVE_CAMERA_TWO_WAY_AUDIO",
    "CameraEntityFeature",
    "WebRTCError",
    "WebRTCSendMessage",
    "async_get_supported_webrtc_provider",
    "camera_state_snapshot",
    "native_camera_capabilities",
)


def camera_state_snapshot(camera: Any) -> tuple[Any, Any, Any]:
    """Return HA-visible camera state for write deduplication."""

    return (
        getattr(camera, "_attr_is_streaming", False),
        getattr(camera, "_attr_available", True),
        freeze_state_value(camera.extra_state_attributes),
    )


def native_camera_capabilities(*, enabled: bool, supported: bool, audio_path: bool) -> Any:
    """Build native microphone capabilities only on supported HA versions."""

    if not HA_SUPPORTS_NATIVE_CAMERA_TWO_WAY_AUDIO or CameraEntityCapabilities is None:
        return None
    return CameraEntityCapabilities(two_way_audio=enabled and supported and audio_path)


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
