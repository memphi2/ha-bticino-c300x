from __future__ import annotations

import asyncio
import socket
import struct
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x.camera_media.talkback import (
    TALKBACK_RTP_PAYLOAD_TYPE,
    async_forward_talkback_audio,
    build_talkback_rtp_packet,
)


def test_builds_speex_talkback_rtp_packet() -> None:
    packet = build_talkback_rtp_packet(
        b"speex-payload",
        sequence=7,
        timestamp=8000,
        ssrc=1234,
        marker=True,
    )

    version, marker_payload, sequence, timestamp, ssrc = struct.unpack(
        "!BBHII",
        packet[:12],
    )
    assert version == 0x80
    assert marker_payload == 0x80 | TALKBACK_RTP_PAYLOAD_TYPE
    assert sequence == 7
    assert timestamp == 8000
    assert ssrc == 1234
    assert packet[12:] == b"speex-payload"


def test_talkback_forwarding_reports_missing_agent_host() -> None:
    active: list[bool] = []
    errors: list[str | None] = []

    asyncio.run(
        async_forward_talkback_audio(
            SimpleNamespace(),
            SimpleNamespace(),
            None,
            on_active=active.append,
            on_error=errors.append,
            on_packet=lambda: None,
        )
    )

    assert errors == ["agent_host_missing"]
    assert active == []


def test_talkback_forwarding_encodes_packets_and_flushes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MediaStreamError(Exception):
        pass

    class _Packet:
        def __init__(self, payload: bytes, duration: int | None = 160) -> None:
            self.payload = payload
            self.duration = duration

        def __bytes__(self) -> bytes:
            return self.payload

    class _Encoder:
        def __init__(self) -> None:
            self.sample_rate = None
            self.layout = None
            self.format = None
            self.time_base = None
            self.bit_rate = None
            self.opened = False

        def open(self) -> None:
            self.opened = True

        def encode(self, frame):  # noqa: ANN001
            if frame is None:
                return [_Packet(b"flush", duration=None)]
            return [_Packet(b""), _Packet(b"voice", duration=80)]

    class _CodecContext:
        @staticmethod
        def create(codec: str, mode: str) -> _Encoder:
            assert (codec, mode) == ("libspeex", "w")
            return _Encoder()

    class _Resampler:
        def __init__(self, *, format: str, layout: str, rate: int) -> None:  # noqa: A002
            assert (format, layout, rate) == ("s16", "mono", 8000)

        def resample(self, frame):  # noqa: ANN001
            return [SimpleNamespace(samples=160)]

    class _Track:
        def __init__(self) -> None:
            self.calls = 0

        async def recv(self):  # noqa: ANN201
            self.calls += 1
            if self.calls == 1:
                return object()
            raise _MediaStreamError

    class _Socket:
        def __init__(self, family: int, socktype: int, proto: int) -> None:
            assert family is socket.AF_INET
            assert socktype is socket.SOCK_DGRAM
            assert proto == 0
            self.closed = False

        def setblocking(self, value: bool) -> None:
            assert value is False

        def close(self) -> None:
            self.closed = True

    sent: list[tuple[bytes, tuple[str, int]]] = []
    active: list[bool] = []
    errors: list[str | None] = []
    packet_count = 0

    async def _run() -> None:
        nonlocal packet_count
        loop = asyncio.get_running_loop()

        async def _getaddrinfo(host, port, *, type):  # noqa: ANN001,A002
            assert (host, port, type) == ("doorstation.local", 40004, socket.SOCK_DGRAM)
            return [(socket.AF_INET, socket.SOCK_DGRAM, 0, "", ("127.0.0.1", 40004))]

        async def _sock_sendto(sock, data, target):  # noqa: ANN001
            sent.append((data, target))

        monkeypatch.setattr(loop, "getaddrinfo", _getaddrinfo)
        monkeypatch.setattr(loop, "sock_sendto", _sock_sendto)
        monkeypatch.setattr(socket, "socket", _Socket)

        def _on_packet() -> None:
            nonlocal packet_count
            packet_count += 1

        await async_forward_talkback_audio(
            _Track(),
            SimpleNamespace(
                av=SimpleNamespace(CodecContext=_CodecContext),
                AudioResampler=_Resampler,
                MediaStreamError=_MediaStreamError,
            ),
            "doorstation.local",
            on_active=active.append,
            on_error=errors.append,
            on_packet=_on_packet,
        )

    asyncio.run(_run())

    assert errors == [None]
    assert active == [True, False]
    assert packet_count == 1
    assert [payload[12:] for payload, _target in sent] == [b"voice", b"flush"]
