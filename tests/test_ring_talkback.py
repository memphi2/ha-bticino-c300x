from __future__ import annotations

import asyncio
import importlib.util
import socket
import sys
import threading
import types
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_ring_talkback() -> Any:
    if (
        "homeassistant" in sys.modules
        and "homeassistant.exceptions" not in sys.modules
    ):
        exceptions = types.ModuleType("homeassistant.exceptions")

        class HomeAssistantError(Exception):  # pragma: no cover - import-time stub only
            pass

        exceptions.HomeAssistantError = HomeAssistantError
        sys.modules["homeassistant.exceptions"] = exceptions
        sys.modules["homeassistant"].exceptions = exceptions

    path = ROOT / "custom_components" / "bticino_c300x" / "ring_talkback.py"
    spec = importlib.util.spec_from_file_location("c300x_ring_talkback_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ring_talkback = _load_ring_talkback()


async def _to_thread_inline(func, /, *args, **kwargs):  # noqa: ANN001
    return func(*args, **kwargs)


def test_build_talkback_rtp_packet_sets_marker_payload_and_header() -> None:
    packet = ring_talkback._build_talkback_rtp_packet(
        b"payload",
        sequence=0x1234,
        timestamp=0x01020304,
        ssrc=0x05060708,
        marker=True,
    )

    assert packet == (
        b"\x80\xe1\x12\x34\x01\x02\x03\x04\x05\x06\x07\x08payload"
    )


def test_build_talkback_rtp_packet_uses_pcmu_payload_type() -> None:
    packet = ring_talkback._build_talkback_rtp_packet(
        b"payload",
        sequence=0x1234,
        timestamp=0x01020304,
        ssrc=0x05060708,
        marker=True,
        payload_type=ring_talkback._TALKBACK_PCMU_PAYLOAD_TYPE,
    )

    # PT 0 (PCMU) with the marker bit set -> 0x80; speex default would be 0xe1.
    assert packet[1] == 0x80
    assert packet[1] & 0x7F == ring_talkback._TALKBACK_PCMU_PAYLOAD_TYPE


def test_create_talkback_encoder_selects_codec_and_options_by_mode() -> None:
    pcmu = ring_talkback._create_talkback_encoder(
        SimpleNamespace(CodecContext=_FakeCodecContext(["pcm_mulaw"])),
        codec_pcmu=True,
    )
    assert pcmu.name == "pcm_mulaw"
    assert pcmu.opened is True
    # pcm_mulaw has no VBR and rejects unknown options.
    assert getattr(pcmu, "options", None) is None

    speex = ring_talkback._create_talkback_encoder(
        SimpleNamespace(CodecContext=_FakeCodecContext(["speex"])),
        codec_pcmu=False,
    )
    assert speex.name == "speex"
    assert speex.opened is True
    assert speex.options == {"vbr": "on"}


def test_create_pcmu_encoder_reports_missing_codec() -> None:
    with pytest.raises(
        ring_talkback.HomeAssistantError, match="PCMU encoding is not available"
    ):
        ring_talkback._create_pcmu_encoder(
            SimpleNamespace(CodecContext=_FakeCodecContext([]))
        )


def test_keep_talkback_alive_sync_pcmu_emits_payload_type_0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_av(monkeypatch, with_audio=False)
    monkeypatch.setattr(ring_talkback.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(ring_talkback, "_ANNOUNCEMENT_PREROLL_SECONDS", 0.04)
    sys.modules["av"].CodecContext = _FakeCodecContext(["pcm_mulaw"])
    sock = _FakeSocket()
    monkeypatch.setattr(
        ring_talkback,
        "_open_talkback_socket",
        lambda _host: (sock, ("192.0.2.10", 40004)),
    )
    monkeypatch.setattr(ring_talkback.random, "randrange", lambda *_args: 1)
    stop_event = threading.Event()
    stop_event.set()

    ring_talkback._keep_talkback_alive_sync(
        "192.0.2.10", None, stop_event, codec_pcmu=True
    )

    assert sock.closed is True
    # 2 preroll frames + 1 flush packet, all carrying PT 0; marker only on the first.
    assert len(sock.sent) == 3
    assert sock.sent[0][0][1] == 0x80
    for data, _target in sock.sent:
        assert data[1] & 0x7F == ring_talkback._TALKBACK_PCMU_PAYLOAD_TYPE


def test_talkback_host_for_socket_strips_ipv6_brackets_and_zone_encoding() -> None:
    assert ring_talkback._talkback_host_for_socket("[fe80::1%25eth0]") == "fe80::1%eth0"
    assert ring_talkback._talkback_host_for_socket(" 192.0.2.10 ") == "192.0.2.10"


def test_open_talkback_socket_supports_resolved_udp_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    target = ("192.0.2.10", 40004)
    sockets: list[_FakeSocket] = []

    monkeypatch.setattr(
        ring_talkback.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", target)
        ],
    )

    def socket_factory(*_args: Any) -> _FakeSocket:
        sock = _FakeSocket()
        sockets.append(sock)
        return sock

    monkeypatch.setattr(ring_talkback.socket, "socket", socket_factory)

    sock, resolved = ring_talkback._open_talkback_socket("192.0.2.10")

    assert sock is sockets[0]
    assert resolved == target


def test_open_talkback_socket_maps_resolution_and_socket_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ring_talkback.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("dns")),
    )
    with pytest.raises(ring_talkback.HomeAssistantError, match="could not be resolved"):
        ring_talkback._open_talkback_socket("bad")

    monkeypatch.setattr(
        ring_talkback.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.0.2.10", 40004))
        ],
    )
    monkeypatch.setattr(
        ring_talkback.socket,
        "socket",
        lambda *_args: (_ for _ in ()).throw(OSError("socket")),
    )
    with pytest.raises(ring_talkback.HomeAssistantError, match="could not be opened"):
        ring_talkback._open_talkback_socket("192.0.2.10")


def test_create_speex_encoder_tries_native_name_before_libspeex() -> None:
    av_module = SimpleNamespace(CodecContext=_FakeCodecContext(["speex"]))

    encoder = ring_talkback._create_speex_encoder(av_module)

    assert encoder.name == "speex"


def test_create_speex_encoder_falls_back_to_libspeex_and_reports_missing() -> None:
    av_module = SimpleNamespace(CodecContext=_FakeCodecContext(["libspeex"]))

    encoder = ring_talkback._create_speex_encoder(av_module)

    assert encoder.name == "libspeex"

    with pytest.raises(
        ring_talkback.HomeAssistantError, match="Speex encoding is not available"
    ):
        ring_talkback._create_speex_encoder(SimpleNamespace(CodecContext=_FakeCodecContext([])))


def test_send_encoded_talkback_frame_updates_rtp_sequence_and_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ring_talkback.time, "sleep", lambda *_args: None)
    sock = _FakeSocket()
    encoder = _FakeEncoder(packet_payloads=[b"one", b"", b"two"])

    sequence, timestamp, marker = ring_talkback._send_encoded_talkback_frame(
        encoder,
        _FakeAudioFrame(samples=160),
        sock,
        ("192.0.2.10", 40004),
        sequence=65535,
        timestamp=100,
        ssrc=1,
        marker=True,
    )

    assert sequence == 1
    assert timestamp == 420
    assert marker is False
    assert len(sock.sent) == 2
    assert sock.sent[0][0][1] == 0xE1
    assert sock.sent[1][0][1] == 0x61


def test_send_ready_talkback_frames_drains_complete_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ring_talkback.time, "sleep", lambda *_args: None)
    fifo = _FakeFifo(samples=400)
    sock = _FakeSocket()

    sequence, timestamp, marker = ring_talkback._send_ready_talkback_frames(
        _FakeEncoder(packet_payloads=[b"a"]),
        fifo,
        sock,
        ("192.0.2.10", 40004),
        1,
        10,
        2,
        True,
    )

    assert sequence == 3
    assert timestamp == 330
    assert marker is False
    assert fifo.samples == 80
    assert len(sock.sent) == 2


def test_send_ready_talkback_frames_stops_when_fifo_returns_no_frame() -> None:
    class _EmptyReadFifo:
        samples = 160

        def read(self, _samples: int) -> None:
            self.samples = 0
            return None

    sock = _FakeSocket()

    sequence, timestamp, marker = ring_talkback._send_ready_talkback_frames(
        _FakeEncoder(packet_payloads=[b"a"]),
        _EmptyReadFifo(),
        sock,
        ("192.0.2.10", 40004),
        1,
        10,
        2,
        True,
    )

    assert (sequence, timestamp, marker) == (1, 10, True)
    assert sock.sent == []


def test_send_talkback_silence_preroll_uses_configured_frame_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ring_talkback.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(ring_talkback, "_ANNOUNCEMENT_PREROLL_SECONDS", 0.04)
    sock = _FakeSocket()

    sequence, timestamp, marker = ring_talkback._send_talkback_silence_preroll(
        SimpleNamespace(AudioFrame=_FakeAudioFrame),
        _FakeEncoder(packet_payloads=[b"s"]),
        sock,
        ("192.0.2.10", 40004),
        1,
        10,
        2,
        True,
    )

    assert sequence == 3
    assert timestamp == 330
    assert marker is False
    assert len(sock.sent) == 2


def test_keep_talkback_alive_sync_sends_preroll_file_audio_and_flush(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_av(monkeypatch, with_audio=True)
    monkeypatch.setattr(ring_talkback.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(ring_talkback, "_ANNOUNCEMENT_PREROLL_SECONDS", 0.02)
    sock = _FakeSocket()
    monkeypatch.setattr(
        ring_talkback,
        "_open_talkback_socket",
        lambda _host: (sock, ("192.0.2.10", 40004)),
    )
    monkeypatch.setattr(ring_talkback.random, "randrange", lambda *_args: 1)
    stop_event = threading.Event()
    stop_event.set()

    ring_talkback._keep_talkback_alive_sync(
        "192.0.2.10",
        Path("announcement.wav"),
        stop_event,
    )

    assert sock.closed is True
    assert len(sock.sent) >= 3


def test_keep_talkback_alive_sync_flushes_after_keepalive_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_av(monkeypatch, with_audio=False)
    monkeypatch.setattr(ring_talkback.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(ring_talkback, "_ANNOUNCEMENT_PREROLL_SECONDS", 0.0)
    sock = _FakeSocket()
    monkeypatch.setattr(
        ring_talkback,
        "_open_talkback_socket",
        lambda _host: (sock, ("192.0.2.10", 40004)),
    )
    stop_event = threading.Event()
    calls: list[str] = []

    class _GuardEncoder:
        sample_rate = 8000
        layout = "mono"
        format = "s16"
        time_base = None
        options: dict[str, str] = {}

        def open(self) -> None:
            return None

        def encode(self, frame: Any = None) -> list[_FakePacket]:
            if frame is None:
                calls.append("flush")
                return []
            calls.append("frame")
            stop_event.set()
            return [_FakePacket(b"packet")]

    class _GuardCodecContext:
        def create(self, codec_name: str, _mode: str) -> _GuardEncoder:
            assert codec_name == "speex"
            return _GuardEncoder()

    sys.modules["av"].CodecContext = _GuardCodecContext()

    ring_talkback._keep_talkback_alive_sync("192.0.2.10", None, stop_event)

    assert calls == ["frame", "flush"]
    assert sock.closed is True


def test_keep_talkback_alive_sync_rejects_source_without_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_av(monkeypatch, with_audio=False)
    sock = _FakeSocket()
    monkeypatch.setattr(
        ring_talkback,
        "_open_talkback_socket",
        lambda _host: (sock, ("192.0.2.10", 40004)),
    )
    monkeypatch.setattr(ring_talkback, "_ANNOUNCEMENT_PREROLL_SECONDS", 0.0)
    stop_event = threading.Event()
    stop_event.set()

    with pytest.raises(ring_talkback.HomeAssistantError, match="has no audio stream"):
        ring_talkback._keep_talkback_alive_sync(
            "192.0.2.10",
            Path("announcement.wav"),
            stop_event,
        )

    assert sock.closed is True


def test_keep_talkback_alive_sync_maps_missing_pyav(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "av", raising=False)
    import builtins

    original_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "av" or name.startswith("av."):
            raise ImportError("no av")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ring_talkback.HomeAssistantError, match="PyAV is not installed"):
        ring_talkback._keep_talkback_alive_sync(
            "192.0.2.10",
            None,
            threading.Event(),
        )


def test_async_wait_talkback_ready_polls_until_audio_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeRingStatusApi(
        [{"answered": True, "audio_active": False}, {"answered": True, "audio_active": True}]
    )
    monkeypatch.setattr(ring_talkback.asyncio, "sleep", _async_noop)

    asyncio.run(
        ring_talkback._async_wait_talkback_ready(
            SimpleNamespace(runtime_data=SimpleNamespace(api=api))
        )
    )

    assert api.calls == 2


def test_async_wait_talkback_ready_accepts_typed_mapping_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _FakeRingStatusApi(
        [MappingProxyType({"answered": True, "audio_active": True})]
    )
    monkeypatch.setattr(ring_talkback.asyncio, "sleep", _async_noop)

    asyncio.run(
        ring_talkback._async_wait_talkback_ready(
            SimpleNamespace(runtime_data=SimpleNamespace(api=api))
        )
    )

    assert api.calls == 1


def test_async_wait_talkback_ready_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ring_talkback, "_TALKBACK_READY_TIMEOUT_SECONDS", 0)

    with pytest.raises(ring_talkback.HomeAssistantError, match="talkback was not ready"):
        asyncio.run(
            ring_talkback._async_wait_talkback_ready(
                SimpleNamespace(
                    runtime_data=SimpleNamespace(api=_FakeRingStatusApi([]))
                )
            )
        )


def test_async_play_and_keepalive_map_worker_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TalkbackError(Exception):
        pass

    async def ok_wait(_entry: Any) -> None:
        return None

    def broken_play(_host: str, _source: Path, *, codec_pcmu: bool = False) -> None:
        raise RuntimeError("boom")

    def broken_keepalive(
        _host: str,
        _source: Path | None,
        _stop_event: threading.Event,
        *,
        codec_pcmu: bool = False,
    ) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(ring_talkback, "_async_wait_talkback_ready", ok_wait)
    monkeypatch.setattr(ring_talkback, "HomeAssistantError", TalkbackError)
    monkeypatch.setattr(ring_talkback, "_play_announcement_sync", broken_play)
    monkeypatch.setattr(ring_talkback, "_keep_talkback_alive_sync", broken_keepalive)
    monkeypatch.setattr(ring_talkback.asyncio, "to_thread", _to_thread_inline)

    with pytest.raises(TalkbackError, match="announcement playback failed"):
        asyncio.run(
            ring_talkback.async_play_announcement_when_ready(
                object(),
                "192.0.2.10",
                Path("announcement.wav"),
            )
        )
    with pytest.raises(TalkbackError, match="talkback keepalive failed"):
        asyncio.run(
            ring_talkback.async_keep_talkback_alive_when_ready(
                object(),
                "192.0.2.10",
                None,
                threading.Event(),
            )
        )


def test_async_play_and_keepalive_propagate_homeassistant_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ok_wait(_entry: Any) -> None:
        return None

    def broken_play(_host: str, _source: Path, *, codec_pcmu: bool = False) -> None:
        raise ring_talkback.HomeAssistantError("expected play failure")

    def broken_keepalive(
        _host: str,
        _source: Path | None,
        _stop_event: threading.Event,
        *,
        codec_pcmu: bool = False,
    ) -> None:
        raise ring_talkback.HomeAssistantError("expected keepalive failure")

    monkeypatch.setattr(ring_talkback, "_async_wait_talkback_ready", ok_wait)
    monkeypatch.setattr(ring_talkback, "_play_announcement_sync", broken_play)
    monkeypatch.setattr(ring_talkback, "_keep_talkback_alive_sync", broken_keepalive)
    monkeypatch.setattr(ring_talkback.asyncio, "to_thread", _to_thread_inline)

    with pytest.raises(ring_talkback.HomeAssistantError, match="expected play failure"):
        asyncio.run(
            ring_talkback.async_play_announcement_when_ready(
                object(),
                "192.0.2.10",
                Path("announcement.wav"),
            )
        )
    with pytest.raises(
        ring_talkback.HomeAssistantError,
        match="expected keepalive failure",
    ):
        asyncio.run(
            ring_talkback.async_keep_talkback_alive_when_ready(
                object(),
                "192.0.2.10",
                None,
                threading.Event(),
            )
        )


def test_play_announcement_sync_sets_single_shot_stop_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, Path | None, bool]] = []

    def _keepalive(
        host: str,
        source: Path | None,
        stop_event: threading.Event,
        *,
        codec_pcmu: bool = False,
    ) -> None:
        seen.append((host, source, stop_event.is_set()))

    monkeypatch.setattr(ring_talkback, "_keep_talkback_alive_sync", _keepalive)

    ring_talkback._play_announcement_sync("192.0.2.10", Path("announcement.wav"))

    assert seen == [("192.0.2.10", Path("announcement.wav"), True)]


async def _async_noop(*_args: Any) -> None:
    return None


class _FakeRingStatusApi:
    def __init__(self, statuses: list[Mapping[str, Any]]) -> None:
        self._statuses = list(statuses)
        self.calls = 0

    async def async_doorbell_call_status(self) -> Mapping[str, Any]:
        self.calls += 1
        if self._statuses:
            return self._statuses.pop(0)
        return {}


class _FakeSocket:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[Any, ...]]] = []
        self.closed = False

    def sendto(self, data: bytes, target: tuple[Any, ...]) -> None:
        self.sent.append((data, target))

    def close(self) -> None:
        self.closed = True


class _FakePacket:
    duration = 160

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __bytes__(self) -> bytes:
        return self._payload


class _FakeEncoder:
    def __init__(self, packet_payloads: list[bytes] | None = None, name: str = "speex") -> None:
        self.packet_payloads = packet_payloads or [b"packet"]
        self.name = name
        self.opened = False

    def open(self) -> None:
        self.opened = True

    def encode(self, _frame: Any = None) -> list[_FakePacket]:
        return [_FakePacket(payload) for payload in self.packet_payloads]


class _FakeCodecContext:
    def __init__(self, supported_names: list[str]) -> None:
        self.supported_names = supported_names

    def create(self, codec_name: str, _mode: str) -> _FakeEncoder:
        if codec_name not in self.supported_names:
            raise RuntimeError("missing codec")
        return _FakeEncoder(name=codec_name)


class _FakePlane:
    buffer_size = 320

    def update(self, _data: bytes) -> None:
        return None


class _FakeAudioFrame:
    def __init__(
        self,
        *,
        format: str = "s16",
        layout: str = "mono",
        samples: int = 160,
    ) -> None:
        self.format = format
        self.layout = layout
        self.samples = samples
        self.sample_rate = 8000
        self.planes = [_FakePlane()]


class _FakeFifo:
    def __init__(self, samples: int = 0) -> None:
        self.samples = samples

    def write(self, frame: _FakeAudioFrame) -> None:
        self.samples += frame.samples

    def read(self, samples: int) -> _FakeAudioFrame | None:
        if self.samples <= 0:
            return None
        used = min(samples, self.samples)
        self.samples -= used
        return _FakeAudioFrame(samples=used)


class _FakeResampler:
    def __init__(self, **_kwargs: Any) -> None:
        pass

    def resample(self, frame: _FakeAudioFrame | None) -> list[_FakeAudioFrame]:
        return [] if frame is None else [frame]


class _FakeInputContainer:
    def __init__(self, with_audio: bool) -> None:
        self.streams = [SimpleNamespace(type="audio")] if with_audio else []

    def __enter__(self) -> _FakeInputContainer:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def decode(self, _stream: Any) -> list[_FakeAudioFrame]:
        return [_FakeAudioFrame(samples=160)]


def _install_fake_av(monkeypatch: pytest.MonkeyPatch, *, with_audio: bool) -> None:
    av_module = types.ModuleType("av")
    av_module.AudioFrame = _FakeAudioFrame
    av_module.CodecContext = _FakeCodecContext(["speex"])
    av_module.open = lambda *_args, **_kwargs: _FakeInputContainer(with_audio)

    audio_module = types.ModuleType("av.audio")
    fifo_module = types.ModuleType("av.audio.fifo")
    resampler_module = types.ModuleType("av.audio.resampler")
    fifo_module.AudioFifo = _FakeFifo
    resampler_module.AudioResampler = _FakeResampler
    audio_module.fifo = fifo_module
    audio_module.resampler = resampler_module

    monkeypatch.setitem(sys.modules, "av", av_module)
    monkeypatch.setitem(sys.modules, "av.audio", audio_module)
    monkeypatch.setitem(sys.modules, "av.audio.fifo", fifo_module)
    monkeypatch.setitem(sys.modules, "av.audio.resampler", resampler_module)
