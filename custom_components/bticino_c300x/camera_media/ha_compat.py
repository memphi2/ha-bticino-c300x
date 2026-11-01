"""Camera API locations shared by the supported Home Assistant versions."""

from typing import TYPE_CHECKING

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

__all__ = ("CameraEntityFeature", "WebRTCError", "WebRTCSendMessage")
