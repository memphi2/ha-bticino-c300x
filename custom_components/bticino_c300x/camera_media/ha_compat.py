"""Camera API locations shared by the supported Home Assistant versions."""

from typing import TYPE_CHECKING

from homeassistant.components import camera as camera_platform
from homeassistant.components.camera import const as camera_const

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
)
