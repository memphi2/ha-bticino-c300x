"""Authenticated HA media proxy for C300X stored media."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import unquote

from aiohttp import web
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import (
    C300XAgentApiError,
    C300XAgentApiResponseError,
    C300XAgentApiUnsupportedError,
    normalize_memo_id,
    normalize_video_message_id,
)
from .const import DOMAIN
from .video_messages import VIDEO_MESSAGE_PLAYBACK_MIME_TYPE

if TYPE_CHECKING:
    from av.audio.frame import AudioFrame
    from av.video.frame import VideoFrame

    class HomeAssistantView:
        """Typed subset of Home Assistant's HTTP view base."""

        url: str
        extra_urls: list[str]
        name: str
        requires_auth: bool
else:
    from homeassistant.components.http import HomeAssistantView

_VIEW_REGISTERED = "video_message_view_registered"
_ORIGINAL_VIDEO_CONTENT_TYPES = {
    "application/octet-stream",
    "video/x-msvideo",
    "video/x-matroska",
}


class C300XMediaDependencyError(RuntimeError):
    """Raised when an optional Home Assistant media dependency is unavailable."""


def async_setup_media_view(hass: HomeAssistant) -> None:
    """Register authenticated media proxy views once."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_VIEW_REGISTERED):
        return
    hass.http.register_view(cast(Any, C300XVideoMessageMediaView()))
    hass.http.register_view(cast(Any, C300XVoiceMemoMediaView()))
    domain_data[_VIEW_REGISTERED] = True


class C300XVideoMessageMediaView(HomeAssistantView):
    """Serve stored C300X answering-machine video through HA auth."""

    url = f"/api/{DOMAIN}/video-messages/{{entry_id}}/{{message_id}}/video"
    extra_urls = [
        f"/api/{DOMAIN}/video-messages/{{entry_id}}/{{message_id}}/video.mp4"
    ]
    name = f"api:{DOMAIN}:video_message"
    requires_auth = True

    async def get(
        self,
        request: web.Request,
        entry_id: str,
        message_id: str,
    ) -> web.Response:
        """Return video-message bytes from the device agent."""

        hass: HomeAssistant = request.app["hass"]
        entry = hass.config_entries.async_get_entry(unquote(entry_id))
        if entry is None or entry.domain != DOMAIN:
            raise web.HTTPNotFound()

        normalized_message_id = _validated_message_id(message_id)
        if normalized_message_id is None:
            raise web.HTTPNotFound()

        transcode_to_mp4 = request.path.endswith("/video.mp4")

        try:
            content, content_type = (
                await entry.runtime_data.api.async_answering_machine_message_video(
                    normalized_message_id
                )
            )
        except C300XAgentApiUnsupportedError as err:
            raise web.HTTPNotFound() from err
        except C300XAgentApiError as err:
            raise web.HTTPBadGateway() from err

        if transcode_to_mp4 and _should_transcode_video_message(content_type):
            try:
                content = await hass.async_add_executor_job(
                    _convert_video_message_to_mp4,
                    content,
                )
            except C300XMediaDependencyError as err:
                raise web.HTTPBadGateway(
                    text="C300X video message could not be converted to MP4"
                ) from err
            except Exception as err:
                raise web.HTTPBadGateway(
                    text="C300X video message could not be converted to MP4"
                ) from err
            content_type = VIDEO_MESSAGE_PLAYBACK_MIME_TYPE

        return web.Response(
            body=content,
            content_type=content_type,
            headers={"Cache-Control": "no-store"},
        )


class C300XVoiceMemoMediaView(HomeAssistantView):
    """Serve stored C300X voice memos through HA auth."""

    url = f"/api/{DOMAIN}/voice-memos/{{entry_id}}/{{memo_name}}/audio"
    name = f"api:{DOMAIN}:voice_memo"
    requires_auth = True

    async def get(
        self,
        request: web.Request,
        entry_id: str,
        memo_name: str,
    ) -> web.Response:
        """Return voice-memo audio bytes from the device agent."""

        hass: HomeAssistant = request.app["hass"]
        entry = runtime_entry(hass, unquote(entry_id))
        if entry is None:
            raise web.HTTPNotFound()

        normalized_memo_id = _validated_voice_memo_id(memo_name)
        if normalized_memo_id is None:
            raise web.HTTPNotFound()

        try:
            content, content_type = await entry.runtime_data.api.async_memo_audio(
                normalized_memo_id
            )
        except C300XAgentApiUnsupportedError as err:
            raise web.HTTPNotFound() from err
        except C300XAgentApiError as err:
            raise web.HTTPBadGateway() from err

        return web.Response(
            body=content,
            content_type=content_type,
            headers={"Cache-Control": "no-store"},
        )


def _validated_message_id(message_id: str) -> str | None:
    try:
        return normalize_video_message_id(unquote(message_id))
    except C300XAgentApiResponseError:
        return None


def _validated_voice_memo_id(memo_name: str) -> str | None:
    try:
        return normalize_memo_id(f"voice/{unquote(memo_name)}")
    except C300XAgentApiResponseError:
        return None


def runtime_entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry[Any] | None:
    """Return a loaded C300X entry by id."""

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        return None
    if not hasattr(entry, "runtime_data"):
        return None
    return entry


def _should_transcode_video_message(content_type: str) -> bool:
    normalized = content_type.split(";", 1)[0].strip().lower()
    return normalized in _ORIGINAL_VIDEO_CONTENT_TYPES


def _convert_video_message_to_mp4(content: bytes) -> bytes:
    """Convert C300X AVI video messages into browser-playable MP4 bytes."""

    try:
        import av
        from av.audio.resampler import AudioResampler
    except ImportError as err:
        raise C300XMediaDependencyError(
            "PyAV is not installed on Home Assistant"
        ) from err

    source = BytesIO(content)
    target = BytesIO()
    with av.open(source, mode="r") as input_container:
        video_stream = next(
            (stream for stream in input_container.streams if stream.type == "video"),
            None,
        )
        if video_stream is None:
            raise ValueError("video message does not contain a video stream")
        audio_stream = next(
            (stream for stream in input_container.streams if stream.type == "audio"),
            None,
        )

        with av.open(target, mode="w", format="mp4") as output_container:
            output_video = output_container.add_stream(
                "h264",
                rate=video_stream.average_rate or 2,
            )
            codec_context = cast(Any, video_stream.codec_context)
            output_video.width = codec_context.width
            output_video.height = codec_context.height
            output_video.pix_fmt = "yuv420p"

            output_audio = None
            resampler = None
            if audio_stream is not None:
                output_audio = output_container.add_stream("aac", rate=44100)
                output_audio.layout = "mono"
                resampler = AudioResampler(format="fltp", layout="mono", rate=44100)

            streams = [video_stream]
            if audio_stream is not None:
                streams.append(audio_stream)
            for packet in input_container.demux(streams):
                if packet.stream.type == "video":
                    for frame in packet.decode():
                        video_frame = cast("VideoFrame", frame)
                        for output_packet in output_video.encode(video_frame):
                            output_container.mux(output_packet)
                elif output_audio is not None and resampler is not None:
                    for frame in packet.decode():
                        audio_frame = cast("AudioFrame", frame)
                        for resampled_frame in resampler.resample(audio_frame):
                            for output_packet in output_audio.encode(resampled_frame):
                                output_container.mux(output_packet)

            for output_packet in output_video.encode():
                output_container.mux(output_packet)
            if output_audio is not None and resampler is not None:
                for resampled_frame in resampler.resample(None):
                    for output_packet in output_audio.encode(resampled_frame):
                        output_container.mux(output_packet)
                for output_packet in output_audio.encode():
                    output_container.mux(output_packet)

    converted = target.getvalue()
    if not converted:
        raise ValueError("video message conversion produced no data")
    return converted
