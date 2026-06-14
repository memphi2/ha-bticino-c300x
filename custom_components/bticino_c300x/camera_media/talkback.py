"""Talkback RTP helpers for C300X WebRTC microphone forwarding."""

from __future__ import annotations

import asyncio
import random
import socket
import struct
from collections.abc import Callable
from contextlib import suppress
from fractions import Fraction
from types import SimpleNamespace
from typing import Any

TALKBACK_RTP_PORT = 40004
TALKBACK_RTP_PAYLOAD_TYPE = 97
TALKBACK_SAMPLE_RATE = 8000
TALKBACK_CODEC = "speex/8000"


def build_talkback_rtp_packet(
    payload: bytes,
    sequence: int,
    timestamp: int,
    ssrc: int,
    marker: bool,
) -> bytes:
    """Build one Speex/8k RTP packet for the C300X talkback socket."""

    marker_payload = TALKBACK_RTP_PAYLOAD_TYPE | (0x80 if marker else 0)
    header = struct.pack("!BBHII", 0x80, marker_payload, sequence, timestamp, ssrc)
    return header + payload


async def async_forward_talkback_audio(
    track: Any,
    aiortc_modules: SimpleNamespace,
    host: str | None,
    *,
    on_active: Callable[[bool], None],
    on_error: Callable[[str | None], None],
    on_packet: Callable[[], None],
) -> None:
    """Encode browser microphone audio as Speex/8k RTP for C300X talkback."""

    loop = asyncio.get_running_loop()
    if not host:
        on_error("agent_host_missing")
        return

    sock: socket.socket | None = None
    target: tuple[Any, ...] | None = None
    encoder: Any | None = None
    sequence = random.randrange(0, 65536)
    timestamp = random.randrange(0, 2**32)
    ssrc = random.randrange(1, 2**32)
    marker = True

    try:
        infos = await loop.getaddrinfo(
            host,
            TALKBACK_RTP_PORT,
            type=socket.SOCK_DGRAM,
        )
        family, socktype, proto, _canonname, target = infos[0]
        sock = socket.socket(family, socktype, proto)
        sock.setblocking(False)
        on_error(None)
        on_active(True)

        encoder = aiortc_modules.av.CodecContext.create("libspeex", "w")
        encoder.sample_rate = TALKBACK_SAMPLE_RATE
        encoder.layout = "mono"
        encoder.format = "s16"
        encoder.time_base = Fraction(1, TALKBACK_SAMPLE_RATE)
        encoder.bit_rate = 15000
        encoder.open()
        resampler = aiortc_modules.AudioResampler(
            format="s16",
            layout="mono",
            rate=TALKBACK_SAMPLE_RATE,
        )

        while True:
            frame = await track.recv()
            for resampled in resampler.resample(frame):
                samples = max(1, int(getattr(resampled, "samples", 160) or 160))
                for packet in encoder.encode(resampled):
                    payload = bytes(packet)
                    if not payload:
                        continue
                    rtp = build_talkback_rtp_packet(
                        payload,
                        sequence,
                        timestamp,
                        ssrc,
                        marker,
                    )
                    await loop.sock_sendto(sock, rtp, target)
                    on_packet()
                    sequence = (sequence + 1) & 0xFFFF
                    timestamp = (
                        timestamp
                        + max(1, int(getattr(packet, "duration", None) or samples))
                    ) & 0xFFFFFFFF
                    marker = False
    except asyncio.CancelledError:
        raise
    except Exception as err:
        media_stream_error = getattr(aiortc_modules, "MediaStreamError", None)
        if media_stream_error is None or not isinstance(err, media_stream_error):
            on_error(type(err).__name__)
        return
    finally:
        if encoder is not None and sock is not None and target is not None:
            with suppress(Exception):
                for packet in encoder.encode(None):
                    payload = bytes(packet)
                    if not payload:
                        continue
                    rtp = build_talkback_rtp_packet(
                        payload,
                        sequence,
                        timestamp,
                        ssrc,
                        marker,
                    )
                    await loop.sock_sendto(sock, rtp, target)
                    sequence = (sequence + 1) & 0xFFFF
                    timestamp = (
                        timestamp
                        + max(1, int(getattr(packet, "duration", None) or 160))
                    ) & 0xFFFFFFFF
                    marker = False
        if sock is not None:
            sock.close()
        on_active(False)
