from __future__ import annotations

# ruff: noqa: E402
import asyncio
import json
import socket
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

homeassistant = sys.modules.setdefault(
    "homeassistant",
    types.ModuleType("homeassistant"),
)
homeassistant.__path__ = []
exceptions = sys.modules.setdefault(
    "homeassistant.exceptions",
    types.ModuleType("homeassistant.exceptions"),
)
helpers = sys.modules.setdefault(
    "homeassistant.helpers",
    types.ModuleType("homeassistant.helpers"),
)
config_entries = sys.modules.setdefault(
    "homeassistant.config_entries",
    types.ModuleType("homeassistant.config_entries"),
)
core = sys.modules.setdefault("homeassistant.core", types.ModuleType("homeassistant.core"))
config_validation = types.ModuleType("homeassistant.helpers.config_validation")


class _HomeAssistantError(Exception):  # pragma: no cover - import-time stub only
    pass


class _ConfigEntry:  # pragma: no cover - import-time stub only
    pass


class _HomeAssistant:  # pragma: no cover - import-time stub only
    pass


exceptions.HomeAssistantError = getattr(
    exceptions,
    "HomeAssistantError",
    _HomeAssistantError,
)
config_entries.ConfigEntry = getattr(config_entries, "ConfigEntry", _ConfigEntry)
core.HomeAssistant = getattr(core, "HomeAssistant", _HomeAssistant)
homeassistant.exceptions = exceptions
homeassistant.config_entries = config_entries
homeassistant.core = core
config_validation.config_entry_only_config_schema = lambda _domain: dict
helpers.config_validation = config_validation
homeassistant.helpers = helpers
sys.modules["homeassistant.helpers.config_validation"] = config_validation

from homeassistant.exceptions import HomeAssistantError

from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_RING_CAPTURE_AUDIO_GAIN_DB,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
)
from custom_components.bticino_c300x.ring_capture import (
    _announcement_input_path,
    _async_announcement_input_path,
    _async_mkdir,
    _async_rtsp_options,
    _async_run_ffmpeg,
    _async_run_ffmpeg_command,
    _async_wait_rtsp_ready,
    _capture_audio_gain_db,
    _capture_frame_offsets,
    _capture_metadata_path,
    _capture_output_path,
    _capture_stream_path,
    _capture_work_dir,
    _resolve_root,
    _rtsp_url_from_status,
    _safe_c300x_path,
    _validate_duration,
    async_capture_doorbell_ring_call,
    raise_if_ring_capture_blocked,
)
from custom_components.bticino_c300x.ring_talkback import (
    _create_speex_encoder,
    _open_talkback_socket,
    _talkback_host_for_socket,
)


@dataclass
class _FakeConfig:
    root: Path

    def path(self, *parts: str) -> str:
        return str(self.root.joinpath(*parts))


@dataclass
class _FakeHass:
    root: Path
    config: _FakeConfig = field(init=False)
    executor_jobs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.config = _FakeConfig(self.root)

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        self.executor_jobs.append(getattr(func, "__name__", str(func)))
        return func(*args)


@dataclass
class _FakeApi:
    status: dict[str, Any]

    async def async_doorbell_video_status(self) -> dict[str, Any]:
        bridge = {"media_owner": "idle", "clients": 0}
        bridge.update(self.status.get("bridge", {}))
        return {**self.status, "bridge": bridge}


@dataclass
class _FakeRuntimeData:
    api: _FakeApi


@dataclass
class _FakeEntry:
    runtime_data: _FakeRuntimeData
    data: dict[str, Any]
    options: dict[str, Any] = field(default_factory=dict)


async def _never_called_talkback(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("talkback must not run for capture without announcement")


async def _noop_talkback(*_args: Any, **_kwargs: Any) -> None:
    return None


async def _to_thread_inline(func, /, *args, **kwargs):  # noqa: ANN001
    return func(*args, **kwargs)


def test_capture_stream_path_prefers_audio_path_when_audio_is_requested() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({})),
        data={CONF_VIDEO_STREAM_PATH: "/configured"},
    )

    assert _capture_stream_path(
        entry,
        {
            "stream_path": "/video",
            "audio_stream_path": "/audio",
            "recorder_stream_path": "/recorder",
        },
        include_audio=True,
    ) == "/audio"
    assert _capture_stream_path(
        entry,
        {
            "stream_path": "/video",
            "audio_stream_path": "/audio",
            "recorder_stream_path": "/recorder",
        },
        include_audio=False,
    ) == "/recorder"
    assert _capture_stream_path(
        entry,
        {"stream_path": "/video", "audio_stream_path": "/audio"},
        include_audio=True,
    ) == "/audio"
    assert _capture_stream_path(entry, {"stream_path": "/video"}) == "/video"
    assert _capture_stream_path(entry, {}) == "/configured"


def test_capture_audio_gain_uses_entry_option_and_clamps_range() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({})),
        data={},
        options={CONF_RING_CAPTURE_AUDIO_GAIN_DB: -4.5},
    )
    high_entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({})),
        data={},
        options={CONF_RING_CAPTURE_AUDIO_GAIN_DB: 99},
    )
    low_entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({})),
        data={},
        options={CONF_RING_CAPTURE_AUDIO_GAIN_DB: -99},
    )

    assert _capture_audio_gain_db(entry) == -4.5
    assert _capture_audio_gain_db(high_entry) == 12.0
    assert _capture_audio_gain_db(low_entry) == -12.0


def test_capture_audio_gain_falls_back_for_invalid_option() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({})),
        data={},
        options={CONF_RING_CAPTURE_AUDIO_GAIN_DB: "bad"},
    )

    assert _capture_audio_gain_db(entry) == DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB


def test_rtsp_url_uses_entry_host_port_and_status_path() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({})),
        data={
            CONF_AGENT_HOST: "192.0.2.10",
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: "/configured",
        },
    )

    assert (
        _rtsp_url_from_status(
            entry,
            {"recorder_stream_path": "doorbell-recorder"},
            include_audio=False,
        )
        == "rtsp://192.0.2.10:6554/doorbell-recorder"
    )


def test_rtsp_url_brackets_ipv6_host() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({})),
        data={
            CONF_AGENT_HOST: "fe80::1%wlan0",
            CONF_VIDEO_PORT: 6554,
            CONF_VIDEO_STREAM_PATH: "/configured",
        },
    )

    assert (
        _rtsp_url_from_status(entry, {"recorder_stream_path": "/doorbell"})
        == "rtsp://[fe80::1%25wlan0]:6554/doorbell"
    )


def test_rtsp_url_rejects_missing_host_or_invalid_port() -> None:
    missing_host = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({})),
        data={CONF_VIDEO_PORT: 6554},
    )
    bad_port = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({})),
        data={CONF_AGENT_HOST: "192.0.2.10", CONF_VIDEO_PORT: "bad"},
    )

    with pytest.raises(HomeAssistantError, match="agent host is not configured"):
        _rtsp_url_from_status(missing_host, {"recorder_stream_path": "/doorbell"})
    with pytest.raises(HomeAssistantError, match="RTSP port is invalid"):
        _rtsp_url_from_status(bad_port, {"recorder_stream_path": "/doorbell"})


def test_talkback_socket_supports_ipv6_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int, int]] = []

    class _FakeSocket:
        def __init__(self, family: int, socktype: int, proto: int) -> None:
            calls.append((family, socktype, proto))
            self.closed = False

        def close(self) -> None:
            self.closed = True

    def _getaddrinfo(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        assert host == "fe80::1%wlan0"
        assert port == 40004
        assert kwargs == {"type": socket.SOCK_DGRAM}
        return [
            (
                socket.AF_INET6,
                socket.SOCK_DGRAM,
                socket.IPPROTO_UDP,
                "",
                ("fe80::1", 40004, 0, 2),
            )
        ]

    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_talkback.socket.getaddrinfo",
        _getaddrinfo,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_talkback.socket.socket",
        _FakeSocket,
    )

    sock, target = _open_talkback_socket("[fe80::1%25wlan0]")

    assert _talkback_host_for_socket("[fe80::1%25wlan0]") == "fe80::1%wlan0"
    assert calls == [(socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP)]
    assert target == ("fe80::1", 40004, 0, 2)
    sock.close()
    assert sock.closed is True


def test_capture_output_path_rejects_paths_outside_allowed_roots(tmp_path: Path) -> None:
    hass = _FakeHass(tmp_path / "config")

    assert _capture_output_path(
        hass,
        str(tmp_path / "config" / "www" / "c300x" / "clip.mp4"),
    ).name == "clip.mp4"
    with pytest.raises(HomeAssistantError):
        _capture_output_path(hass, str(tmp_path / "config" / "www" / "bad.mp4"))
    with pytest.raises(HomeAssistantError):
        _capture_output_path(hass, "/media/c300x/clip.mkv")


def test_capture_work_dir_defaults_below_config_c300x(tmp_path: Path) -> None:
    hass = _FakeHass(tmp_path / "config")

    assert _capture_work_dir(hass) == tmp_path / "config" / "c300x"


def test_capture_work_dir_accepts_directory_not_wav_file(tmp_path: Path) -> None:
    hass = _FakeHass(tmp_path / "config")
    wav_dir = tmp_path / "config" / "c300x" / "analysis"

    assert _capture_work_dir(hass, str(wav_dir)) == wav_dir
    with pytest.raises(HomeAssistantError):
        _capture_work_dir(hass, str(wav_dir / "clip.wav"))


def test_capture_duration_validation_rejects_invalid_values() -> None:
    assert _validate_duration("5") == 5
    for value in ("bad", 0, 16):
        with pytest.raises(HomeAssistantError):
            _validate_duration(value)


def test_announcement_path_allows_only_c300x_media_roots(tmp_path: Path) -> None:
    hass = _FakeHass(tmp_path / "config")
    announcement = tmp_path / "config" / "www" / "c300x" / "announce.wav"
    announcement.parent.mkdir(parents=True)
    announcement.write_bytes(b"fake")

    assert _announcement_input_path(hass, str(announcement)) == announcement
    with pytest.raises(HomeAssistantError):
        _announcement_input_path(hass, str(tmp_path / "announce.wav"))
    with pytest.raises(HomeAssistantError):
        _announcement_input_path(
            hass,
            str(tmp_path / "config" / "www" / "c300x" / "missing.wav"),
        )


def test_announcement_path_accepts_ha_www_alias(tmp_path: Path) -> None:
    hass = _FakeHass(tmp_path / "config")
    announcement = tmp_path / "config" / "www" / "c300x" / "announce.wav"
    announcement.parent.mkdir(parents=True)
    announcement.write_bytes(b"fake")

    assert _announcement_input_path(hass, "/www/c300x/announce.wav") == announcement


def test_announcement_path_async_fallback_without_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_root = tmp_path / "config"
    announcement = config_root / "www" / "c300x" / "announce.wav"
    announcement.parent.mkdir(parents=True)
    announcement.write_bytes(b"fake")
    hass = types.SimpleNamespace(config=_FakeConfig(config_root))
    monkeypatch.setattr(asyncio, "to_thread", _to_thread_inline)

    assert (
        asyncio.run(_async_announcement_input_path(hass, str(announcement)))
        == announcement
    )


def test_safe_c300x_path_accepts_static_config_www_root_without_config() -> None:
    assert _safe_c300x_path(
        types.SimpleNamespace(),
        Path("/config/www/c300x/clip.mp4"),
        "output",
    ) == Path("/config/www/c300x/clip.mp4")


def test_resolve_root_returns_original_path_on_os_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = Path("/config/c300x")

    def _raise_os_error(self: Path, *, strict: bool = False) -> Path:
        raise OSError

    monkeypatch.setattr(Path, "resolve", _raise_os_error)

    assert _resolve_root(target) == target


def test_async_mkdir_uses_thread_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "config" / "c300x" / "analysis"
    monkeypatch.setattr(asyncio, "to_thread", _to_thread_inline)

    asyncio.run(_async_mkdir(types.SimpleNamespace(), target))

    assert target.is_dir()


def test_capture_resolves_announcement_path_in_executor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "config" / "www" / "c300x" / "clip.mp4"
    announcement = tmp_path / "config" / "www" / "c300x" / "announce.wav"
    announcement.parent.mkdir(parents=True)
    announcement.write_bytes(b"fake")
    hass = _FakeHass(tmp_path / "config")
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({"audio_stream_path": "/doorbell"})),
        data={CONF_AGENT_HOST: "192.0.2.10", CONF_VIDEO_PORT: 6554},
    )

    async def _ready(_rtsp_url: str) -> None:
        return None

    async def _ffmpeg(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _talkback(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_wait_rtsp_ready",
        _ready,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_run_ffmpeg",
        _ffmpeg,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_keep_talkback_alive_when_ready",
        _talkback,
    )

    asyncio.run(
        async_capture_doorbell_ring_call(
            hass,
            entry,
            output_path=str(target),
            announcement_path=str(announcement),
        )
    )

    assert "_announcement_input_path" in hass.executor_jobs


def test_rtsp_options_probe_uses_fake_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []
    writes: list[bytes] = []

    class _Reader:
        async def read(self, _size: int) -> bytes:
            return b"RTSP/1.0 200 OK\r\nCSeq: 1\r\n\r\n"

    class _Writer:
        def write(self, payload: bytes) -> None:
            writes.append(payload)

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def _open_connection(host: str, port: int) -> tuple[_Reader, _Writer]:
        calls.append((host, port))
        return _Reader(), _Writer()

    monkeypatch.setattr(asyncio, "open_connection", _open_connection)

    asyncio.run(_async_rtsp_options("rtsp://192.0.2.10:6554/doorbell"))

    assert calls == [("192.0.2.10", 6554)]
    assert writes[0].startswith(b"OPTIONS rtsp://192.0.2.10:6554/doorbell RTSP/1.0")


@pytest.mark.parametrize(
    "response",
    [
        b"HTTP/1.1 200 OK\r\n\r\n",
        b"RTSP/1.0 503 Service Unavailable\r\n\r\n",
    ],
)
def test_rtsp_options_probe_rejects_bad_responses(
    monkeypatch: pytest.MonkeyPatch,
    response: bytes,
) -> None:
    class _Reader:
        async def read(self, _size: int) -> bytes:
            return response

    class _Writer:
        def write(self, _payload: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def _open_connection(_host: str, _port: int) -> tuple[_Reader, _Writer]:
        return _Reader(), _Writer()

    monkeypatch.setattr(asyncio, "open_connection", _open_connection)

    with pytest.raises(HomeAssistantError):
        asyncio.run(_async_rtsp_options("rtsp://192.0.2.10:6554/doorbell"))


def test_rtsp_options_probe_rejects_invalid_rtsp_url() -> None:
    with pytest.raises(HomeAssistantError, match="Invalid C300X RTSP URL"):
        asyncio.run(_async_rtsp_options("http://192.0.2.10:6554/doorbell"))


def test_wait_rtsp_ready_returns_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _probe(rtsp_url: str) -> None:
        calls.append(rtsp_url)

    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_rtsp_options",
        _probe,
    )

    asyncio.run(_async_wait_rtsp_ready("rtsp://192.0.2.10:6554/doorbell"))

    assert calls == ["rtsp://192.0.2.10:6554/doorbell"]


def test_wait_rtsp_ready_raises_after_probe_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    async def _probe(_rtsp_url: str) -> None:
        nonlocal attempts
        attempts += 1
        raise OSError("not ready")

    async def _sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_rtsp_options",
        _probe,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._RTSP_READY_TIMEOUT_SECONDS",
        0.001,
    )
    monkeypatch.setattr(asyncio, "sleep", _sleep)

    with pytest.raises(HomeAssistantError, match="RTSP stream was not ready") as err:
        asyncio.run(_async_wait_rtsp_ready("rtsp://192.0.2.10:6554/doorbell"))

    assert attempts > 0
    assert isinstance(err.value.__cause__, OSError)


def test_capture_runs_ffmpeg_after_rtsp_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, Any]] = []
    target = tmp_path / "config" / "www" / "c300x" / "clip.mp4"
    hass = _FakeHass(tmp_path / "config")
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            _FakeApi({"recorder_stream_path": "/doorbell-recorder"})
        ),
        data={CONF_AGENT_HOST: "192.0.2.10", CONF_VIDEO_PORT: 6554},
    )

    async def _ready(rtsp_url: str) -> None:
        calls.append(("ready", rtsp_url))

    async def _ffmpeg(
        rtsp_url: str,
        output: Path,
        *,
        work_dir: Path | None,
        duration_seconds: int,
        include_audio: bool,
        audio_gain_db: float,
    ) -> None:
        calls.append(
            (
                "ffmpeg",
                (
                    rtsp_url,
                    output,
                    work_dir,
                    duration_seconds,
                    include_audio,
                    audio_gain_db,
                ),
            )
        )

    async def _talkback(
        _entry: Any,
        host: str,
        source: Path | None,
        _stop_event: Any,
    ) -> None:
        calls.append(("talkback", (host, source)))

    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_wait_rtsp_ready",
        _ready,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_run_ffmpeg",
        _ffmpeg,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_keep_talkback_alive_when_ready",
        _talkback,
    )

    result = asyncio.run(
        async_capture_doorbell_ring_call(
            hass,
            entry,
            output_path=str(target),
            duration_seconds=4,
            include_audio=True,
        )
    )

    assert result == target
    assert ("ready", "rtsp://192.0.2.10:6554/doorbell-recorder") in calls
    assert (
        "ffmpeg",
            (
                "rtsp://192.0.2.10:6554/doorbell-recorder",
                target,
                tmp_path / "config" / "c300x",
                4,
                True,
                6.0,
        ),
    ) in calls
    assert ("talkback", ("192.0.2.10", None)) in calls
    metadata_path = _capture_metadata_path(tmp_path / "config" / "c300x")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["capture_id"]
    assert metadata["output_path"] == str(target)
    assert metadata["metadata_path"] == str(metadata_path)
    assert metadata["raw_wav_path"] == str(
        tmp_path / "config" / "c300x" / "latest.raw.wav"
    )
    assert metadata["processed_wav_path"] == str(
        tmp_path / "config" / "c300x" / "latest.processed.wav"
    )
    assert metadata["frames"] == [
        str(tmp_path / "config" / "c300x" / "frame_01.jpg"),
        str(tmp_path / "config" / "c300x" / "frame_02.jpg"),
        str(tmp_path / "config" / "c300x" / "frame_03.jpg"),
    ]


def test_capture_blocks_when_rtsp_client_is_active(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "config" / "www" / "c300x" / "clip.mp4"
    hass = _FakeHass(tmp_path / "config")
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            _FakeApi(
                {
                    "recorder_stream_path": "/doorbell-recorder",
                    "bridge": {"media_owner": "agent", "clients": 1},
                }
            )
        ),
        data={CONF_AGENT_HOST: "192.0.2.10", CONF_VIDEO_PORT: 6554},
    )

    async def _ready(_rtsp_url: str) -> None:
        raise AssertionError("busy capture must not probe RTSP")

    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_wait_rtsp_ready",
        _ready,
    )

    with pytest.raises(HomeAssistantError, match="ring capture busy"):
        asyncio.run(
            async_capture_doorbell_ring_call(
                hass,
                entry,
                output_path=str(target),
            )
        )


def test_capture_block_guard_reads_typed_mapping_status() -> None:
    status = MappingProxyType(
        {
            "bridge": MappingProxyType(
                {
                    "media_owner": "agent",
                    "clients": "1",
                }
            )
        }
    )

    with pytest.raises(HomeAssistantError, match="ring capture busy"):
        raise_if_ring_capture_blocked(status)


def test_capture_allows_shared_ring_preview_when_agent_reports_capacity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "config" / "www" / "c300x" / "clip.mp4"
    hass = _FakeHass(tmp_path / "config")
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            _FakeApi(
                {
                    "recorder_stream_path": "/doorbell-recorder",
                    "bridge": {
                        "media_owner": "ring",
                        "ring_call_active": True,
                        "ring_media_active": True,
                        "clients": 1,
                        "max_clients": 2,
                        "ring_preview_sharing": True,
                    },
                }
            )
        ),
        data={CONF_AGENT_HOST: "192.0.2.10", CONF_VIDEO_PORT: 6554},
    )
    calls: list[tuple[str, Any]] = []

    async def _ready(rtsp_url: str) -> None:
        calls.append(("ready", rtsp_url))

    async def _capture(rtsp_url: str, output: Path, **kwargs: Any) -> None:
        calls.append(("capture", rtsp_url, output, kwargs))

    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_wait_rtsp_ready",
        _ready,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_run_ffmpeg",
        _capture,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_keep_talkback_alive_when_ready",
        _noop_talkback,
    )

    asyncio.run(
        async_capture_doorbell_ring_call(
            hass,
            entry,
            output_path=str(target),
        )
    )

    assert ("ready", "rtsp://192.0.2.10:6554/doorbell-recorder") in calls


def test_video_only_capture_shares_ring_preview_without_talkback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "config" / "www" / "c300x" / "clip.mp4"
    hass = _FakeHass(tmp_path / "config")
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            _FakeApi(
                {
                    "recorder_stream_path": "/doorbell-recorder",
                    "bridge": {
                        "media_owner": "ring",
                        "ring_call_active": True,
                        "ring_media_active": True,
                        "clients": 1,
                        "max_clients": 2,
                        "ring_preview_sharing": True,
                    },
                }
            )
        ),
        data={CONF_AGENT_HOST: "192.0.2.10", CONF_VIDEO_PORT: 6554},
    )
    calls: list[tuple[str, Any]] = []

    async def _ready(rtsp_url: str) -> None:
        calls.append(("ready", rtsp_url))

    async def _capture(rtsp_url: str, output: Path, **kwargs: Any) -> None:
        calls.append(("capture", rtsp_url, output, kwargs))

    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_wait_rtsp_ready",
        _ready,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_run_ffmpeg",
        _capture,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_keep_talkback_alive_when_ready",
        _never_called_talkback,
    )

    asyncio.run(
        async_capture_doorbell_ring_call(
            hass,
            entry,
            output_path=str(target),
            include_audio=False,
        )
    )

    assert calls == [
        ("ready", "rtsp://192.0.2.10:6554/doorbell-recorder"),
        (
            "capture",
            "rtsp://192.0.2.10:6554/doorbell-recorder",
            target,
            {
                "work_dir": tmp_path / "config" / "c300x",
                "duration_seconds": 5,
                "include_audio": False,
                "audio_gain_db": 6.0,
            },
        ),
    ]


def test_capture_ffmpeg_audio_uses_mp4_safe_normalized_aac(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    class _Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def _create_subprocess_exec(*command: str, **_kwargs: Any) -> _Process:
        commands.append(list(command))
        return _Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _create_subprocess_exec)

    asyncio.run(
        _async_run_ffmpeg(
            "rtsp://192.0.2.10:6554/doorbell",
            tmp_path / "clip.mp4",
            work_dir=tmp_path / "work",
            duration_seconds=4,
            include_audio=True,
        )
    )

    command = commands[0]
    audio_filter = command[command.index("-af") + 1]
    assert "aresample=48000" in audio_filter
    assert "pan=stereo" in audio_filter
    assert "dynaudnorm=" not in audio_filter
    assert "alimiter=" in audio_filter
    assert "volume=6dB" in audio_filter
    assert "volume=30dB" not in audio_filter
    assert command[command.index("-ac") + 1] == "2"
    assert command[command.index("-ar") + 1] == "48000"
    assert command[command.index("-b:a") + 1] == "128k"
    assert str(tmp_path / "work" / "latest.raw.wav") in command
    assert commands[1][-1] == str(tmp_path / "work" / "latest.processed.wav")
    assert len(commands) == 5
    frame_commands = commands[2:]
    assert [cmd[-1] for cmd in frame_commands] == [
        str(tmp_path / "work" / "frame_01.jpg"),
        str(tmp_path / "work" / "frame_02.jpg"),
        str(tmp_path / "work" / "frame_03.jpg"),
    ]
    assert [cmd[cmd.index("-ss") + 1] for cmd in frame_commands] == [
        "1.000",
        "2.400",
        "3.800",
    ]


def test_capture_ffmpeg_audio_uses_configured_gain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    class _Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def _create_subprocess_exec(*command: str, **_kwargs: Any) -> _Process:
        commands.append(list(command))
        return _Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _create_subprocess_exec)

    asyncio.run(
        _async_run_ffmpeg(
            "rtsp://192.0.2.10:6554/doorbell",
            tmp_path / "clip.mp4",
            work_dir=tmp_path / "work",
            duration_seconds=4,
            include_audio=True,
            audio_gain_db=-4.5,
        )
    )

    audio_filter = commands[0][commands[0].index("-af") + 1]
    assert "volume=-4.5dB" in audio_filter


def test_capture_ffmpeg_video_only_disables_audio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    class _Process:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def _create_subprocess_exec(*command: str, **_kwargs: Any) -> _Process:
        commands.append(list(command))
        return _Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _create_subprocess_exec)

    asyncio.run(
        _async_run_ffmpeg(
            "rtsp://192.0.2.10:6554/doorbell-video",
            tmp_path / "clip.mp4",
            work_dir=tmp_path / "work",
            duration_seconds=4,
            include_audio=False,
        )
    )

    assert "-an" in commands[0]
    assert len(commands) == 4
    assert [cmd[-1] for cmd in commands[1:]] == [
        str(tmp_path / "work" / "frame_01.jpg"),
        str(tmp_path / "work" / "frame_02.jpg"),
        str(tmp_path / "work" / "frame_03.jpg"),
    ]


def test_capture_frame_offsets_handle_short_clips() -> None:
    assert _capture_frame_offsets(1) == (0.5, 0.65, 0.8)
    assert _capture_frame_offsets(2) == (1.0, 1.4, 1.8)


def test_ffmpeg_command_reports_missing_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _create_subprocess_exec(*_args: str, **_kwargs: Any) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _create_subprocess_exec)

    with pytest.raises(HomeAssistantError, match="ffmpeg is not installed"):
        asyncio.run(
            _async_run_ffmpeg_command(
                ["ffmpeg"],
                command_timeout=1,
                error_prefix="C300X capture failed",
            )
        )


def test_ffmpeg_command_reports_stderr_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Process:
        returncode = 1

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b"bad codec"

    async def _create_subprocess_exec(*_args: str, **_kwargs: Any) -> _Process:
        return _Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _create_subprocess_exec)

    with pytest.raises(HomeAssistantError, match="C300X capture failed: bad codec"):
        asyncio.run(
            _async_run_ffmpeg_command(
                ["ffmpeg"],
                command_timeout=1,
                error_prefix="C300X capture failed",
            )
        )


def test_ffmpeg_command_times_out_and_kills_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Process:
        def __init__(self) -> None:
            self.returncode = None
            self.killed = False

        async def communicate(self) -> tuple[bytes, bytes]:
            if not self.killed:
                await asyncio.sleep(60)
            return b"", b""

        def kill(self) -> None:
            self.killed = True

    process = _Process()

    async def _create_subprocess_exec(*_args: str, **_kwargs: Any) -> _Process:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _create_subprocess_exec)

    with pytest.raises(HomeAssistantError, match="C300X capture failed: timed out"):
        asyncio.run(
            _async_run_ffmpeg_command(
                ["ffmpeg"],
                command_timeout=0.01,
                error_prefix="C300X capture failed",
            )
        )

    assert process.killed is True


def test_announcement_speex_encoder_accepts_runtime_codec_alias() -> None:
    calls: list[str] = []

    class _CodecContext:
        @staticmethod
        def create(codec_name: str, _mode: str) -> object:
            calls.append(codec_name)
            if codec_name == "speex":
                return object()
            raise RuntimeError("missing")

    class _AvModule:
        CodecContext = _CodecContext

    assert _create_speex_encoder(_AvModule()) is not None
    assert calls == ["speex"]


def test_capture_plays_announcement_in_parallel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, Any]] = []
    target = tmp_path / "config" / "www" / "c300x" / "clip.mp4"
    announcement = tmp_path / "config" / "www" / "c300x" / "announce.wav"
    announcement.parent.mkdir(parents=True)
    announcement.write_bytes(b"fake")
    hass = _FakeHass(tmp_path / "config")
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({"audio_stream_path": "/doorbell"})),
        data={CONF_AGENT_HOST: "192.0.2.10", CONF_VIDEO_PORT: 6554},
    )

    async def _ready(rtsp_url: str) -> None:
        calls.append(("ready", rtsp_url))

    async def _ffmpeg(
        rtsp_url: str,
        output: Path,
        *,
        work_dir: Path | None,
        duration_seconds: int,
        include_audio: bool,
        audio_gain_db: float,
    ) -> None:
        calls.append(
            (
                "ffmpeg",
                (
                    rtsp_url,
                    output,
                    work_dir,
                    duration_seconds,
                    include_audio,
                    audio_gain_db,
                ),
            )
        )

    async def _talkback(
        _entry: Any,
        host: str,
        source: Path | None,
        _stop_event: Any,
    ) -> None:
        calls.append(("talkback", (host, source)))

    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_wait_rtsp_ready",
        _ready,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_run_ffmpeg",
        _ffmpeg,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_keep_talkback_alive_when_ready",
        _talkback,
    )

    asyncio.run(
        async_capture_doorbell_ring_call(
            hass,
            entry,
            output_path=str(target),
            duration_seconds=4,
            include_audio=True,
            announcement_path=str(announcement),
        )
    )

    assert ("talkback", ("192.0.2.10", announcement)) in calls


def test_capture_cancels_long_announcement_after_capture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    target = tmp_path / "config" / "www" / "c300x" / "clip.mp4"
    announcement = tmp_path / "config" / "www" / "c300x" / "announce.wav"
    announcement.parent.mkdir(parents=True)
    announcement.write_bytes(b"fake")
    hass = _FakeHass(tmp_path / "config")
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(_FakeApi({"audio_stream_path": "/doorbell"})),
        data={CONF_AGENT_HOST: "192.0.2.10", CONF_VIDEO_PORT: 6554},
    )

    async def _ready(_rtsp_url: str) -> None:
        return None

    async def _ffmpeg(*_args: Any, **_kwargs: Any) -> None:
        await asyncio.sleep(0)
        events.append("capture_done")

    async def _talkback(*_args: Any, **_kwargs: Any) -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            events.append("talkback_cancelled")
            raise

    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_wait_rtsp_ready",
        _ready,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_run_ffmpeg",
        _ffmpeg,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.ring_capture._async_keep_talkback_alive_when_ready",
        _talkback,
    )

    asyncio.run(
        async_capture_doorbell_ring_call(
            hass,
            entry,
            output_path=str(target),
            duration_seconds=1,
            announcement_path=str(announcement),
        )
    )

    assert events == ["capture_done", "talkback_cancelled"]
