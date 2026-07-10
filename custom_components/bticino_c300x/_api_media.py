"""Doorbell video, ring/home calls and audio-codec endpoints."""

from __future__ import annotations

from typing import Any, cast

from ._api_core import _C300XApiCore
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


class _ApiMediaMixin(_C300XApiCore):
    """Doorbell video, ring/home calls and audio-codec endpoints."""

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

    async def async_set_doorstation_audio_gain_db(
        self,
        gain_db: float,
    ) -> dict[str, Any]:
        """Set the native agent's runtime doorstation downstream audio gain."""

        data = await self._request_json(
            "POST",
            "/api/v1/video/doorbell/audio",
            json_data={"doorstation_audio_gain_tenths": round(float(gain_db) * 10)},
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
            ),
        )

    async def async_restore_audio_codec(self, *, reboot: bool = True) -> dict[str, Any]:
        """Restore the device to stock speex (patches config; reboots to apply)."""

        return cast(
            "dict[str, Any]",
            await self._request_json(
                "POST",
                "/api/v1/maintenance/audio-codec/actions/restore",
                json_data={"confirm": "restore_audio_codec_patch", "reboot": reboot},
                extra_headers=self._maintenance_headers(),
            ),
        )
