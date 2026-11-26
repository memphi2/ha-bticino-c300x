"""Doorbell video, ring/home calls and audio-codec endpoints."""

from __future__ import annotations

import base64
from typing import Any, cast

from ._api_core import _RESTART_WRITE_TIMEOUT, _C300XApiCore
from ._api_normalize import (
    _doorbell_video_has_ring_call,
    _ok_response,
    normalize_doorbell_call,
    normalize_doorbell_video,
    normalize_home_call,
)
from .agent_contracts import (
    DoorbellVideoStatus,
    HomeCallStatus,
    RingCallStatus,
)
from .api_errors import (
    C300XAgentApiConnectionError,
)

# Base64 of one piece and its JSON frame stay below the agent's request size.
_ANNOUNCEMENT_PIECE = 4500


class _ApiMediaMixin(_C300XApiCore):
    """Doorbell video, ring/home calls and audio-codec endpoints."""

    async def async_doorbell_snapshot(self, width: int, height: int) -> tuple[bytes, str]:
        """Read a bounded in-memory video frame without starting or answering media.

        The agent delivers the image in exactly the given size.
        """

        return await self._request_bytes(
            "GET",
            f"/api/v1/video/doorbell/snapshot?width={int(width)}&height={int(height)}",
            max_bytes=1200 * 1024,
        )

    async def async_doorbell_video_status(self) -> DoorbellVideoStatus:
        """Return doorbell video availability and bridge status."""

        data = await self._request_json("GET", "/api/v1/video/doorbell/status")
        return normalize_doorbell_video(data)

    async def async_activate_doorbell_video(self, audio: bool = True) -> dict[str, Any]:
        """Start or renew the native doorbell video call on demand."""

        try:
            data = await self._request_json(
                "POST",
                "/api/v1/video/doorbell/actions/activate",
                json_data={"audio": bool(audio)},
            )
        except C300XAgentApiConnectionError as err:
            if "HTTP 409" not in str(err) or "external_session_active" not in str(err):
                raise
            status = await self.async_doorbell_video_status()
            if not _doorbell_video_has_ring_call(status):
                raise
            return {
                "ok": True,
                "audio": bool(audio),
                "ring_active": True,
                "status": status,
            }
        return _ok_response(data)

    async def async_set_doorstation_audio_level(
        self,
        door_level_db: int,
        fine_gain_db: int,
    ) -> dict[str, Any]:
        """Set the door level and the fine adjustment of the door station's sound."""

        data = await self._request_json(
            "POST",
            "/api/v1/video/doorbell/audio",
            json_data={"door_level_db": int(door_level_db), "fine_gain_db": int(fine_gain_db)},
        )
        return _ok_response(data)

    async def async_stop_doorbell_video(self) -> dict[str, Any]:
        """Stop the native doorbell video call."""

        data = await self._request_json(
            "POST",
            "/api/v1/video/doorbell/actions/stop",
        )
        return _ok_response(data)

    async def async_doorbell_call_status(self) -> RingCallStatus:
        """Return the native doorbell ring-call control status."""

        data = await self._request_json("GET", "/api/v1/calls/doorbell/status")
        return normalize_doorbell_call(data)

    async def async_answer_doorbell_call(self) -> dict[str, Any]:
        """Request local media answering of the active doorbell ring call."""

        data = await self._request_json(
            "POST",
            "/api/v1/calls/doorbell/actions/answer",
        )
        return _ok_response(data)

    async def async_hangup_doorbell_call(self) -> dict[str, Any]:
        """Hang up the active doorbell ring call."""

        data = await self._request_json(
            "POST",
            "/api/v1/calls/doorbell/actions/hangup",
        )
        return _ok_response(data)

    async def async_capture_doorbell_call(self) -> dict[str, Any]:
        """Request a native doorbell ring-call capture."""

        data = await self._request_json(
            "POST",
            "/api/v1/calls/doorbell/actions/capture",
        )
        return _ok_response(data)

    async def async_home_call_status(self) -> HomeCallStatus:
        """Return the local Home Call status."""

        data = await self._request_json("GET", "/api/v1/calls/home/status")
        return normalize_home_call(data)

    async def async_start_home_call(
        self,
        duration_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Start a local SIP/SRTP Home Call to the C300X."""

        payload: dict[str, Any] = {}
        if duration_seconds is not None:
            payload["duration_seconds"] = int(duration_seconds)
        data = await self._request_json(
            "POST",
            "/api/v1/calls/home/actions/start",
            json_data=payload,
        )
        return _ok_response(data)

    async def async_stop_home_call(self) -> dict[str, Any]:
        """Stop the local SIP/SRTP Home Call."""

        data = await self._request_json(
            "POST",
            "/api/v1/calls/home/actions/stop",
        )
        return _ok_response(data)

    async def async_camera_resolution(
        self, *, high_resolution: bool | None = None
    ) -> dict[str, Any]:
        """Read the camera resolution, or set it for the next stream."""

        return cast(
            "dict[str, Any]",
            await self._request_json(
                "GET" if high_resolution is None else "POST",
                "/api/v1/maintenance/camera-resolution",
                json_data=None if high_resolution is None else {"high_resolution": high_resolution},
                extra_headers=self._maintenance_headers(),
            ),
        )

    async def async_camera_quality(
        self, *, bitrate_kbps: int | None = None, fps: int | None = None, size: str | None = None,
        reboot: bool = True,
    ) -> dict[str, Any]:
        """Read bit rate, frame rate and size of the camera stream, or save new ones.

        The device uses saved values after a restart, which the agent starts
        right away unless ``reboot`` is false, as for the audio codec.
        """

        changes = {
            key: value
            for key, value in (("bitrate_kbps", bitrate_kbps), ("fps", fps), ("size", size))
            if value is not None
        }
        return cast(
            "dict[str, Any]",
            await self._request_json(
                "POST" if changes else "GET",
                "/api/v1/maintenance/camera-quality",
                json_data=(
                    {"confirm": "apply_camera_quality", **changes, "reboot": reboot}
                    if changes else None
                ),
                extra_headers=self._maintenance_headers(),
                request_timeout=max(self._timeout, _RESTART_WRITE_TIMEOUT) if changes else None,
            ),
        )

    async def async_audio_codec_status(self) -> dict[str, Any]:
        """Return the device audio-codec state (speex|pcmu|partial)."""

        return cast(
            "dict[str, Any]",
            await self._request_json(
                "GET",
                "/api/v1/maintenance/audio-codec",
                extra_headers=self._maintenance_headers(),
            ),
        )

    async def async_apply_audio_codec(self, *, reboot: bool = True) -> dict[str, Any]:
        """Switch the device to native PCMU (patches config; reboots to apply)."""

        return cast(
            "dict[str, Any]",
            await self._request_json(
                "POST",
                "/api/v1/maintenance/audio-codec/actions/apply",
                json_data={"confirm": "apply_audio_codec_patch", "reboot": reboot},
                extra_headers=self._maintenance_headers(),
                request_timeout=max(self._timeout, _RESTART_WRITE_TIMEOUT),
            ),
        )

    async def async_restore_audio_codec(self, *, reboot: bool = True) -> dict[str, Any]:
        """Switch the device to Speex (patches config; reboots to apply)."""

        return cast(
            "dict[str, Any]",
            await self._request_json(
                "POST",
                "/api/v1/maintenance/audio-codec/actions/restore",
                json_data={"confirm": "restore_audio_codec_patch", "reboot": reboot},
                extra_headers=self._maintenance_headers(),
                request_timeout=max(self._timeout, _RESTART_WRITE_TIMEOUT),
            ),
        )

    async def async_announcement_status(self) -> dict[str, Any]:
        """Return whether a sound is playing and how the last one ended."""

        return cast("dict[str, Any]", await self._request_json("GET", "/api/v1/announcements"))

    async def async_play_announcement(self, sound: bytes, volume: int) -> dict[str, Any]:
        """Send a sound file (WAV, 8000 Hz, 16 bit) and play it over the speaker.

        The agent takes a request body of a few kilobytes, so the file goes
        in pieces, in order.
        """

        for offset in range(0, len(sound), _ANNOUNCEMENT_PIECE):
            piece = base64.b64encode(sound[offset:offset + _ANNOUNCEMENT_PIECE]).decode()
            await self._request_json(
                "POST", "/api/v1/announcements/audio", json_data={"offset": offset, "data": piece},
            )
        return cast(
            "dict[str, Any]",
            await self._request_json(
                "POST", "/api/v1/announcements/actions/play", json_data={"volume": volume},
            ),
        )

    async def async_stop_announcement(self) -> dict[str, Any]:
        """End the sound that is playing."""

        return cast(
            "dict[str, Any]",
            await self._request_json("POST", "/api/v1/announcements/actions/stop", json_data={}),
        )
