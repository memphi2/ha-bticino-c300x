"""RTSP and call-media orchestration for the C300X camera entity."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol, cast

from homeassistant.exceptions import HomeAssistantError

from ..const import CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT
from ..doorstation_audio import async_ensure_doorstation_audio_gain
from ..entry_config import entry_config_value
from .rtsp_policy import (
    RtspAdmissionKind,
    RtspConsumer,
    decide_rtsp_admission,
    rtsp_resource_snapshot_from_status,
)
from .rtsp_probe import async_probe_rtsp_url
from .state_machine import MediaState, MediaStateOutput

CALL_MEDIA_STATES = {
    MediaState.RING_PENDING,
    MediaState.RING_PREVIEW_ACTIVE,
    MediaState.RING_ANSWERING,
    MediaState.RING_ACTIVE,
    MediaState.HOME_CALL_STARTING,
    MediaState.HOME_CALL_RINGING,
    MediaState.HOME_CALL_ACTIVE,
}
UNANSWERED_RING_STATES = {
    MediaState.RING_PENDING,
    MediaState.RING_PREVIEW_ACTIVE,
}
HOME_CALL_STATES = {
    MediaState.HOME_CALL_STARTING,
    MediaState.HOME_CALL_RINGING,
    MediaState.HOME_CALL_ACTIVE,
    MediaState.HOME_CALL_STOPPING,
}


@dataclass(frozen=True)
class CameraRtspOrchestratorSettings:
    """Timing settings for RTSP and call-media orchestration."""

    rtsp_ready_connect_timeout_seconds: float
    rtsp_ready_interval_seconds: float
    rtsp_ready_timeout_seconds: float
    rtsp_failure_cooldown_seconds: float
    ring_call_wait_interval_seconds: float
    ring_call_wait_timeout_seconds: float


class CameraRtspOwner(Protocol):
    """Camera surface needed by the RTSP orchestrator."""

    _entry: Any
    _rtsp_prepare_lock: asyncio.Lock
    _rtsp_ready_lock: asyncio.Lock
    _rtsp_unavailable_until: float
    _last_rtsp_error: str | None
    _last_video_block_reason: str | None
    _rtsp_cooldown_scope: str | None

    def _build_stream_url(self, *, audio: bool = False) -> str:
        """Build the RTSP URL for the current media paths."""

    def _agent_host_for_socket(self) -> str:
        """Return the agent host for socket APIs."""

    async def _async_refresh_video_status(
        self,
        *,
        apply_status: bool = True,
    ) -> dict[str, Any]:
        """Refresh native-agent doorbell video status."""

    async def _async_refresh_video_status_or_none(
        self,
        *,
        apply_status: bool = True,
    ) -> dict[str, Any] | None:
        """Refresh native-agent doorbell video status, suppressing failures."""

    def _derive_media_decision(
        self,
        status: dict[str, Any] | None = None,
    ) -> MediaStateOutput:
        """Derive current media state from status and local session facts."""

    def _active_local_media_sessions(self) -> int:
        """Return active HA-side media sessions."""

    def _refresh_derived_media_state(self) -> None:
        """Refresh cached media state."""

    def _apply_home_call_status(self, status: Mapping[str, Any]) -> None:
        """Mirror Home Call status into camera state."""

    def _async_write_ha_state_if_ready(self) -> None:
        """Publish entity state when available."""

    def _rtsp_event_revision(self) -> int:
        """Return the current RTSP-relevant agent-event revision."""

    async def _async_wait_for_rtsp_event(
        self,
        *,
        revision: int,
        wait_seconds: float,
    ) -> None:
        """Wait until an RTSP-relevant agent event arrives or timeout expires."""


def media_decision_is_call_media(decision: MediaStateOutput) -> bool:
    """Return true for ring/home-call media states."""

    return decision.state in CALL_MEDIA_STATES


def rtsp_consumer_for_media_decision(decision: MediaStateOutput) -> RtspConsumer:
    """Map media state to the RTSP admission-policy consumer."""

    if decision.state in UNANSWERED_RING_STATES:
        return RtspConsumer.RING_PREVIEW
    if decision.state in {
        MediaState.RING_ANSWERING,
        MediaState.RING_ACTIVE,
        MediaState.RING_HANGING_UP,
    }:
        return RtspConsumer.RING_ANSWERED
    if decision.state in HOME_CALL_STATES:
        return RtspConsumer.HOME_CALL
    return RtspConsumer.DOORBELL_CARD


def rtsp_consumer_for_doorbell_request(decision: MediaStateOutput) -> RtspConsumer:
    """Map media state to the requested consumer for a doorbell WebRTC request."""

    consumer = rtsp_consumer_for_media_decision(decision)
    if consumer is RtspConsumer.HOME_CALL:
        return RtspConsumer.DOORBELL_CARD
    return consumer


class CameraRtspOrchestrator:
    """Coordinate RTSP warmup, admission, readiness, and call-media waits."""

    def __init__(
        self,
        owner: CameraRtspOwner,
        *,
        settings: CameraRtspOrchestratorSettings,
    ) -> None:
        self._owner = owner
        self._settings = settings

    async def async_warmup_video(
        self,
        *,
        audio: bool = False,
        status: Mapping[str, Any] | None = None,
    ) -> None:
        """Mark the video window and refresh bridge metadata before RTSP opens."""

        try:
            if audio:
                await async_ensure_doorstation_audio_gain(
                    self._owner._entry,
                    status=status,
                )
            await self._owner._entry.runtime_data.api.async_activate_doorbell_video(
                audio=audio
            )
        except Exception:  # noqa: BLE001 - refresh status before re-raising API failure
            with suppress(Exception):
                await self._owner._async_refresh_video_status()
                self._owner._async_write_ha_state_if_ready()
            raise
        with suppress(Exception):
            await self._owner._async_refresh_video_status()

    async def async_restart_video_reader(self, *, audio: bool = False) -> None:
        """Restart the on-demand RTSP reader without stealing call media."""

        async with self._owner._rtsp_prepare_lock:
            status = await self._owner._async_refresh_video_status_or_none()
            decision = (
                self._owner._derive_media_decision(status)
                if status is not None
                else None
            )
            if decision is not None and media_decision_is_call_media(decision):
                await self.async_wait_for_rtsp_ready(
                    self._owner._build_stream_url(audio=audio)
                )
                return
            if (
                status is not None
                and decision is not None
                and decision.external_owner_blocks
            ):
                status = await self.async_wait_for_call_media_after_external_event(status)
                decision = (
                    self._owner._derive_media_decision(status)
                    if status is not None
                    else None
                )
                if decision is not None and media_decision_is_call_media(decision):
                    await self.async_wait_for_rtsp_ready(
                        self._owner._build_stream_url(audio=audio)
                    )
                    return
            await self.async_warmup_video(audio=audio)
            await self.async_wait_for_rtsp_ready(
                self._owner._build_stream_url(audio=audio)
            )

    async def async_restart_home_call_reader(self) -> None:
        """Restart Home Call audio-only RTSP after the call is active."""

        async with self._owner._rtsp_prepare_lock:
            await self.async_wait_for_home_call_active()
            await self.async_wait_for_rtsp_ready(
                self._owner._build_stream_url(audio=True),
                cooldown_scope="home_call",
            )

    async def async_prepare_rtsp_stream(self, *, audio: bool = False) -> str:
        """Activate video and return a URL only after RTSP answers."""

        async with self._owner._rtsp_prepare_lock:
            self.raise_if_rtsp_cooling_down(cooldown_scope="doorbell")
            status = await self._owner._async_refresh_video_status_or_none()
            decision = (
                self._owner._derive_media_decision(status)
                if status is not None
                else None
            )
            if (
                status is not None
                and decision is not None
                and decision.external_owner_blocks
            ):
                status = await self.async_wait_for_call_media_after_external_event(status)
                decision = (
                    self._owner._derive_media_decision(status)
                    if status is not None
                    else None
                )
            if decision is not None and decision.state in HOME_CALL_STATES:
                self._owner._last_video_block_reason = "home_call_active"
                self._owner._refresh_derived_media_state()
                raise HomeAssistantError("C300X RTSP busy: home_call_active")
            if decision is None or not media_decision_is_call_media(decision):
                if status is not None and decision is not None:
                    self.raise_if_rtsp_admission_denied(
                        status,
                        decision,
                        consumer=RtspConsumer.DOORBELL_CARD,
                    )
                await self.async_warmup_video(audio=audio, status=status)
            elif status is not None:
                self.raise_if_rtsp_admission_denied(
                    status,
                    decision,
                    consumer=rtsp_consumer_for_doorbell_request(decision),
                )
                if audio:
                    await async_ensure_doorstation_audio_gain(
                        self._owner._entry,
                        status=status,
                    )
            stream_url = self._owner._build_stream_url(audio=audio)
            await self.async_wait_for_rtsp_ready(stream_url, cooldown_scope="doorbell")
            return stream_url

    async def async_wait_for_call_media_after_external_event(
        self,
        status: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Wait for real SIP call media after an external doorbell event."""

        decision = self._owner._derive_media_decision(status)
        if media_decision_is_call_media(decision) or not decision.external_owner_blocks:
            return status

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._settings.ring_call_wait_timeout_seconds
        current: dict[str, Any] | None = status
        while loop.time() < deadline:
            await asyncio.sleep(self._settings.ring_call_wait_interval_seconds)
            refreshed = await self._owner._async_refresh_video_status_or_none()
            if refreshed is None:
                continue
            current = refreshed
            decision = self._owner._derive_media_decision(refreshed)
            if media_decision_is_call_media(decision) or not decision.external_owner_blocks:
                return refreshed
        return current

    async def async_prepare_home_call_rtsp_stream(self) -> str:
        """Return the audio-only RTSP source for an active Home Call."""

        async with self._owner._rtsp_prepare_lock:
            self.raise_if_rtsp_cooling_down(cooldown_scope="home_call")
            await self.async_wait_for_home_call_active()
            stream_url = self._owner._build_stream_url(audio=True)
            await self.async_wait_for_rtsp_ready(stream_url, cooldown_scope="home_call")
            return stream_url

    async def async_wait_for_home_call_active(
        self,
        *,
        apply_status: bool = True,
    ) -> Mapping[str, Any]:
        """Wait until the native agent reports Home Call media as active."""

        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(
            self._settings.rtsp_ready_timeout_seconds,
            20.0,
        )
        last_status: Mapping[str, Any] = {}
        while True:
            with suppress(Exception):
                status = cast(
                    Mapping[str, Any],
                    await self._owner._entry.runtime_data.api.async_home_call_status(),
                )
                last_status = status
                if (
                    status.get("answered")
                    or status.get("rtp_proxy")
                    or status.get("target_audio_port")
                ):
                    if apply_status:
                        self._owner._apply_home_call_status(status)
                    return status
            if loop.time() >= deadline:
                last_error = last_status.get("last_error") if last_status else None
                raise HomeAssistantError(
                    f"C300X Home Call did not become active: {last_error or last_status}"
                )
            await asyncio.sleep(self._settings.rtsp_ready_interval_seconds)

    async def async_wait_for_rtsp_ready(
        self,
        stream_url: str,
        *,
        cooldown_scope: str = "doorbell",
    ) -> None:
        """Wait briefly for the native RTSP bridge to accept RTSP requests."""

        self.raise_if_rtsp_cooling_down(cooldown_scope=cooldown_scope)
        async with self._owner._rtsp_ready_lock:
            self.raise_if_rtsp_cooling_down(cooldown_scope=cooldown_scope)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._settings.rtsp_ready_timeout_seconds
            last_error: Exception | None = None
            event_revision = self._owner._rtsp_event_revision()
            while True:
                block_reason = await self._async_rtsp_start_block_reason()
                if block_reason is not None:
                    last_error = HomeAssistantError(f"native bridge {block_reason}")
                else:
                    try:
                        await self.async_probe_rtsp(stream_url)
                    except Exception as err:  # noqa: BLE001 - probe errors become HA errors
                        last_error = err
                    else:
                        self._owner._last_rtsp_error = None
                        self._owner._rtsp_unavailable_until = 0.0
                        self._owner._rtsp_cooldown_scope = None
                        return

                remaining = deadline - loop.time()
                if remaining <= 0:
                    self._owner._last_rtsp_error = (
                        type(last_error).__name__ if last_error else "timeout"
                    )
                    self._owner._rtsp_unavailable_until = 0.0
                    self._owner._rtsp_cooldown_scope = None
                    raise HomeAssistantError(
                        f"C300X RTSP bridge did not become ready: {last_error}"
                    ) from last_error
                await self._async_wait_for_rtsp_state_change(
                    event_revision,
                    remaining=remaining,
                    prefer_event=block_reason is not None,
                )
                event_revision = self._owner._rtsp_event_revision()

    async def _async_wait_for_rtsp_state_change(
        self,
        revision: int,
        *,
        remaining: float,
        prefer_event: bool,
    ) -> None:
        """Wait for a native media event, falling back to a bounded retry delay."""

        if remaining <= 0:
            return
        if prefer_event:
            wait_seconds = remaining
        else:
            wait_seconds = min(
                remaining,
                max(self._settings.rtsp_ready_interval_seconds, 1.0),
            )
        await self._owner._async_wait_for_rtsp_event(
            revision=revision,
            wait_seconds=wait_seconds,
        )

    async def _async_rtsp_start_block_reason(self) -> str | None:
        """Return the native bridge state that would make RTSP PLAY fail."""

        status = await self._owner._async_refresh_video_status_or_none()
        if status is None:
            return None
        bridge_data = status.get("bridge")
        bridge = bridge_data if isinstance(bridge_data, Mapping) else {}
        if bool(bridge.get("stop_in_progress")) or bool(
            status.get("video_bridge_stop_in_progress")
        ):
            return "stop_in_progress"
        return None

    def raise_if_rtsp_cooling_down(self, *, cooldown_scope: str = "doorbell") -> None:
        """Clear stale RTSP readiness cooldown markers before a new attempt."""

        loop = asyncio.get_running_loop()
        if (
            self._owner._rtsp_unavailable_until > loop.time()
            and self._owner._rtsp_cooldown_scope in {None, cooldown_scope}
        ):
            self._owner._rtsp_unavailable_until = 0.0
            self._owner._rtsp_cooldown_scope = None

    async def async_probe_rtsp(self, stream_url: str) -> None:
        """Open a lightweight RTSP DESCRIBE request against the native bridge."""

        host = self._owner._agent_host_for_socket()
        port = int(
            entry_config_value(self._owner._entry, CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT)
        )
        await async_probe_rtsp_url(
            stream_url,
            method="DESCRIBE",
            socket_host=host,
            socket_port=port,
            timeout_seconds=self._settings.rtsp_ready_connect_timeout_seconds,
            read_size=64,
            user_agent="HomeAssistant-BTicino-C300X",
            accept_sdp=True,
            reject_status_from=300,
        )

    def raise_if_rtsp_admission_denied(
        self,
        status: Mapping[str, Any],
        decision: MediaStateOutput,
        *,
        consumer: RtspConsumer,
    ) -> None:
        """Apply the central RTSP admission policy before starting a consumer."""

        admission = decide_rtsp_admission(
            consumer,
            rtsp_resource_snapshot_from_status(
                status,
                local_sessions=self._owner._active_local_media_sessions(),
            ),
        )
        if admission.allowed or admission.kind is RtspAdmissionKind.REFRESH_STATUS_REQUIRED:
            return
        self._owner._last_video_block_reason = admission.reason
        self._owner._refresh_derived_media_state()
        raise HomeAssistantError(f"C300X RTSP busy: {admission.reason}")
