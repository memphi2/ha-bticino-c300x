"""HA-side C300X ring-call talkback helpers."""

from __future__ import annotations

import asyncio
import random
import socket
import struct
import threading
import time
from collections.abc import Mapping
from fractions import Fraction
from pathlib import Path
from typing import Any

from homeassistant.exceptions import HomeAssistantError

_TALKBACK_RTP_PORT = 40004
_TALKBACK_READY_TIMEOUT_SECONDS = 5.0
_TALKBACK_SAMPLE_RATE = 8000
_TALKBACK_FRAME_SAMPLES = 160
_ANNOUNCEMENT_PREROLL_SECONDS = 1.0


async def async_play_announcement_when_ready(
    entry: Any,
    host: str,
    source: Path,
) -> None:
    """Wait for ring-call talkback and play one HA-local announcement file."""

    await _async_wait_talkback_ready(entry)
    await _async_play_announcement(host, source)


async def async_keep_talkback_alive_when_ready(
    entry: Any,
    host: str,
    source: Path | None,
    stop_event: threading.Event,
) -> None:
    """Wait for ring-call talkback, optionally play an announcement, then keep it alive."""

    await _async_wait_talkback_ready(entry)
    try:
        await asyncio.to_thread(_keep_talkback_alive_sync, host, source, stop_event)
    except HomeAssistantError:
        raise
    except Exception as err:
        raise HomeAssistantError("C300X talkback keepalive failed") from err


async def _async_wait_talkback_ready(entry: Any) -> None:
    deadline = asyncio.get_running_loop().time() + _TALKBACK_READY_TIMEOUT_SECONDS
    last_status: Mapping[str, Any] | None = None
    while asyncio.get_running_loop().time() < deadline:
        status = await entry.runtime_data.api.async_doorbell_call_status()
        last_status = status if isinstance(status, Mapping) else None
        if (
            last_status is not None
            and last_status.get("answered") is True
            and last_status.get("audio_active") is True
        ):
            return
        await asyncio.sleep(0.2)
    raise HomeAssistantError(
        "C300X talkback was not ready for announcement playback"
    )


async def _async_play_announcement(host: str, source: Path) -> None:
    """Play one HA-local announcement file into the C300X talkback RTP port."""

    try:
        await asyncio.to_thread(_play_announcement_sync, host, source)
    except HomeAssistantError:
        raise
    except Exception as err:
        raise HomeAssistantError("C300X announcement playback failed") from err


def _play_announcement_sync(host: str, source: Path) -> None:
    stop_event = threading.Event()
    stop_event.set()
    _keep_talkback_alive_sync(host, source, stop_event)


def _keep_talkback_alive_sync(
    host: str,
    source: Path | None,
    stop_event: threading.Event,
) -> None:
    try:
        import av
        from av.audio.fifo import AudioFifo
        from av.audio.resampler import AudioResampler
    except ImportError as err:
        raise HomeAssistantError("PyAV is not installed on Home Assistant") from err

    sequence = random.randrange(0, 65536)
    timestamp = random.randrange(0, 2**32)
    ssrc = random.randrange(1, 2**32)
    marker = True
    sock, target = _open_talkback_socket(host)
    encoder = _create_speex_encoder(av)
    encoder.sample_rate = _TALKBACK_SAMPLE_RATE
    encoder.layout = "mono"
    encoder.format = "s16"
    encoder.time_base = Fraction(1, _TALKBACK_SAMPLE_RATE)
    encoder.options = {"vbr": "on"}
    encoder.open()
    fifo = AudioFifo()
    resampler = AudioResampler(
        format="s16",
        layout="mono",
        rate=_TALKBACK_SAMPLE_RATE,
    )
    try:
        sequence, timestamp, marker = _send_talkback_silence_preroll(
            av,
            encoder,
            sock,
            target,
            sequence,
            timestamp,
            ssrc,
            marker,
        )
        if source is not None:
            with av.open(str(source)) as container:
                audio_stream = next(
                    (stream for stream in container.streams if stream.type == "audio"),
                    None,
                )
                if audio_stream is None:
                    raise HomeAssistantError("C300X announcement file has no audio stream")
                for frame in container.decode(audio_stream):
                    for resampled in resampler.resample(frame):
                        fifo.write(resampled)
                        sequence, timestamp, marker = _send_ready_talkback_frames(
                            encoder,
                            fifo,
                            sock,
                            target,
                            sequence,
                            timestamp,
                            ssrc,
                            marker,
                        )
                while fifo.samples:
                    frame = fifo.read(min(_TALKBACK_FRAME_SAMPLES, fifo.samples))
                    if frame is None:
                        break
                    sequence, timestamp, marker = _send_encoded_talkback_frame(
                        encoder,
                        frame,
                        sock,
                        target,
                        sequence,
                        timestamp,
                        ssrc,
                        marker,
                    )
        while not stop_event.is_set():
            frame = _new_silence_frame(av)
            sequence, timestamp, marker = _send_encoded_talkback_frame(
                encoder,
                frame,
                sock,
                target,
                sequence,
                timestamp,
                ssrc,
                marker,
            )
        for packet in encoder.encode(None):
            payload = bytes(packet)
            if not payload:
                continue
            rtp = _build_talkback_rtp_packet(payload, sequence, timestamp, ssrc, marker)
            sock.sendto(rtp, target)
            sequence = (sequence + 1) & 0xFFFF
            timestamp = (
                timestamp + max(1, int(getattr(packet, "duration", None) or _TALKBACK_FRAME_SAMPLES))
            ) & 0xFFFFFFFF
            marker = False
    finally:
        sock.close()


def _new_silence_frame(av_module: Any) -> Any:
    frame = av_module.AudioFrame(
        format="s16",
        layout="mono",
        samples=_TALKBACK_FRAME_SAMPLES,
    )
    frame.sample_rate = _TALKBACK_SAMPLE_RATE
    frame.planes[0].update(bytes(frame.planes[0].buffer_size))
    return frame


def _send_talkback_silence_preroll(
    av_module: Any,
    encoder: Any,
    sock: socket.socket,
    target: tuple[Any, ...],
    sequence: int,
    timestamp: int,
    ssrc: int,
    marker: bool,
) -> tuple[int, int, bool]:
    frames = int(_ANNOUNCEMENT_PREROLL_SECONDS * _TALKBACK_SAMPLE_RATE / _TALKBACK_FRAME_SAMPLES)
    for _ in range(frames):
        frame = _new_silence_frame(av_module)
        sequence, timestamp, marker = _send_encoded_talkback_frame(
            encoder,
            frame,
            sock,
            target,
            sequence,
            timestamp,
            ssrc,
            marker,
        )
    return sequence, timestamp, marker


def _talkback_host_for_socket(host: str) -> str:
    """Return the agent host in a form accepted by socket APIs."""

    host = str(host or "").strip()
    if host.startswith("[") and "]" in host:
        host = host[1 : host.index("]")]
    return host.replace("%25", "%")


def _open_talkback_socket(host: str) -> tuple[socket.socket, tuple[Any, ...]]:
    """Open a UDP talkback socket for IPv4 or IPv6 agent hosts."""

    try:
        infos = socket.getaddrinfo(
            _talkback_host_for_socket(host),
            _TALKBACK_RTP_PORT,
            type=socket.SOCK_DGRAM,
        )
    except OSError as err:
        raise HomeAssistantError("C300X talkback target could not be resolved") from err

    last_error: Exception | None = None
    for family, socktype, proto, _canonname, target in infos:
        try:
            return socket.socket(family, socktype, proto), target
        except OSError as err:
            last_error = err
    raise HomeAssistantError("C300X talkback socket could not be opened") from last_error


def _send_ready_talkback_frames(
    encoder: Any,
    fifo: Any,
    sock: socket.socket,
    target: tuple[Any, ...],
    sequence: int,
    timestamp: int,
    ssrc: int,
    marker: bool,
) -> tuple[int, int, bool]:
    while fifo.samples >= _TALKBACK_FRAME_SAMPLES:
        frame = fifo.read(_TALKBACK_FRAME_SAMPLES)
        if frame is None:
            break
        sequence, timestamp, marker = _send_encoded_talkback_frame(
            encoder,
            frame,
            sock,
            target,
            sequence,
            timestamp,
            ssrc,
            marker,
        )
    return sequence, timestamp, marker


def _send_encoded_talkback_frame(
    encoder: Any,
    frame: Any,
    sock: socket.socket,
    target: tuple[Any, ...],
    sequence: int,
    timestamp: int,
    ssrc: int,
    marker: bool,
) -> tuple[int, int, bool]:
    samples = max(1, int(getattr(frame, "samples", _TALKBACK_FRAME_SAMPLES) or _TALKBACK_FRAME_SAMPLES))
    for packet in encoder.encode(frame):
        payload = bytes(packet)
        if not payload:
            continue
        rtp = _build_talkback_rtp_packet(payload, sequence, timestamp, ssrc, marker)
        sock.sendto(rtp, target)
        sequence = (sequence + 1) & 0xFFFF
        timestamp = (
            timestamp + max(1, int(getattr(packet, "duration", None) or samples))
        ) & 0xFFFFFFFF
        marker = False
        time.sleep(samples / _TALKBACK_SAMPLE_RATE)
    return sequence, timestamp, marker


def _create_speex_encoder(av_module: Any) -> Any:
    """Return a Speex encoder using the codec name available in this runtime."""

    last_error: Exception | None = None
    for codec_name in ("speex", "libspeex"):
        try:
            return av_module.CodecContext.create(codec_name, "w")
        except Exception as err:  # noqa: BLE001
            last_error = err
    raise HomeAssistantError("Speex encoding is not available on Home Assistant") from last_error


def _build_talkback_rtp_packet(
    payload: bytes,
    sequence: int,
    timestamp: int,
    ssrc: int,
    marker: bool,
) -> bytes:
    marker_payload = 97 | (0x80 if marker else 0)
    header = struct.pack("!BBHII", 0x80, marker_payload, sequence, timestamp, ssrc)
    return header + payload
