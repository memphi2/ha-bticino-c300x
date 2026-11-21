"""The device speaker in Home Assistant: text-to-speech and sounds."""

from __future__ import annotations

import asyncio
import io
import shutil
import threading
import wave
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.usefixtures("entity_ha_boundary")

from homeassistant.components.media_player import MediaPlayerState  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402

from custom_components.bticino_c300x import announcements, media_player  # noqa: E402
from custom_components.bticino_c300x.api import C300XAgentApiError  # noqa: E402
from custom_components.bticino_c300x.media_player import C300XSpeaker, async_setup_entry  # noqa: E402


class _FakeApi:
    def __init__(self, *results: str | None, refuse: bool = False) -> None:
        # What the agent answers to each status read: None while the sound plays.
        self.results = list(results)
        self.refuse = refuse
        self.played: list[tuple[bytes, int]] = []
        self.stopped = 0

    async def async_play_announcement(self, sound: bytes, volume: int) -> dict[str, Any]:
        if self.refuse:
            raise C300XAgentApiError("announcement_busy")
        self.played.append((sound, volume))
        return {"ok": True, "playing": True}

    async def async_announcement_status(self) -> dict[str, Any]:
        result = self.results.pop(0)
        return {"playing": result is None, "result": result or ""}

    async def async_stop_announcement(self) -> dict[str, Any]:
        self.stopped += 1
        return {"ok": True}


@dataclass
class _FakeEntry:
    api: _FakeApi
    capabilities: dict[str, Any] = field(default_factory=lambda: {"announcements": {"supported": True}})
    entry_id: str = "entry-1"
    title: str = "C300X"
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.runtime_data = SimpleNamespace(
            api=self.api, capabilities=self.capabilities, event_state=SimpleNamespace(),
            connection_state=SimpleNamespace(available=True),
        )


@pytest.fixture
def speaker(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A speaker whose media goes through stand-ins for conversion and waiting."""

    def make(*results: str | None, refuse: bool = False) -> C300XSpeaker:
        entity = C300XSpeaker(_FakeEntry(_FakeApi(*results, refuse=refuse)))  # type: ignore[arg-type]
        entity.entity_id = "media_player.c300x_speaker"
        entity.watches = []  # type: ignore[attr-defined]
        entity.hass = SimpleNamespace(  # type: ignore[assignment]
            async_create_background_task=lambda coro, name: entity.watches.append(coro) or SimpleNamespace(
                cancel=coro.close),
        )
        return entity

    async def convert(url: str) -> bytes:
        return b"WAV of " + url.encode()

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(media_player, "async_sound_for_device", convert)
    monkeypatch.setattr(media_player, "async_process_play_media_url", lambda _hass, url: "http://ha" + url)
    monkeypatch.setattr(media_player.asyncio, "sleep", no_wait)
    return make


def test_speaker_exists_only_where_the_agent_can_play_sound() -> None:
    added: list[Any] = []
    asyncio.run(async_setup_entry(None, _FakeEntry(_FakeApi()), added.extend))  # type: ignore[arg-type]
    asyncio.run(async_setup_entry(  # type: ignore[arg-type]
        None, _FakeEntry(_FakeApi(), capabilities={"announcements": {"supported": False}}), added.extend))
    asyncio.run(async_setup_entry(None, _FakeEntry(_FakeApi(), capabilities={}), added.extend))  # type: ignore[arg-type]

    assert [type(entity) for entity in added] == [C300XSpeaker]


def test_plays_speech_at_its_volume_and_is_idle_again_when_the_device_is_done(speaker: Any) -> None:
    entity = speaker(None, None, "played")

    asyncio.run(entity.async_play_media("music", "/api/tts_proxy/hello.mp3"))

    api = entity._entry.runtime_data.api
    assert api.played == [(b"WAV of http://ha/api/tts_proxy/hello.mp3", 60)]
    assert entity.state == MediaPlayerState.PLAYING
    asyncio.run(entity.watches[0])
    assert entity.state == MediaPlayerState.IDLE
    assert entity.extra_state_attributes == {"last_result": "played"}


def test_resolves_a_media_source_before_playing(speaker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    entity = speaker("played")
    asked: list[tuple[str, str]] = []

    async def resolve(_hass: Any, media_id: str, target: str) -> Any:
        asked.append((media_id, target))
        return SimpleNamespace(url="/media/local/ding.wav?authSig=x")

    monkeypatch.setattr(media_player.media_source, "async_resolve_media", resolve)

    asyncio.run(entity.async_play_media("music", "media-source://media_source/local/ding.wav"))

    assert asked == [("media-source://media_source/local/ding.wav", "media_player.c300x_speaker")]
    assert entity._entry.runtime_data.api.played[0][0] == b"WAV of http://ha/media/local/ding.wav?authSig=x"
    # A sound shorter than the first look is already over.
    assert entity.state == MediaPlayerState.IDLE
    assert entity.watches == []


def test_says_so_when_the_device_keeps_its_speaker_for_a_call(speaker: Any) -> None:
    entity = speaker("device_busy")

    with pytest.raises(HomeAssistantError, match="using its speaker"):
        asyncio.run(entity.async_play_media("music", "/x.mp3"))

    assert entity.state == MediaPlayerState.IDLE
    assert entity.extra_state_attributes == {"last_result": "device_busy"}


def test_a_door_call_that_cuts_the_sound_is_no_error(speaker: Any) -> None:
    entity = speaker(None, "preempted")

    asyncio.run(entity.async_play_media("music", "/x.mp3"))
    asyncio.run(entity.watches[0])

    assert entity.state == MediaPlayerState.IDLE
    assert entity.extra_state_attributes == {"last_result": "preempted"}


def test_says_so_when_the_agent_refuses_the_sound(speaker: Any) -> None:
    entity = speaker(refuse=True)

    with pytest.raises(HomeAssistantError, match="was not played"):
        asyncio.run(entity.async_play_media("music", "/x.mp3"))

    assert entity.state == MediaPlayerState.IDLE


def test_volume_is_kept_for_the_next_sound_and_over_a_restart(speaker: Any) -> None:
    entity = speaker("played", "played")
    asyncio.run(entity.async_set_volume_level(1.0))
    asyncio.run(entity.async_play_media("music", "/x.mp3"))

    async def last_state() -> Any:
        return SimpleNamespace(attributes={"volume_level": 0.25})

    entity.async_get_last_state = last_state
    asyncio.run(entity.async_added_to_hass())
    asyncio.run(entity.async_play_media("music", "/x.mp3"))

    assert [volume for _sound, volume in entity._entry.runtime_data.api.played] == [100, 25]


def test_stop_asks_the_agent_to_end_the_sound(speaker: Any) -> None:
    entity = speaker()

    asyncio.run(entity.async_media_stop())

    assert entity._entry.runtime_data.api.stopped == 1


def test_sound_is_made_into_the_format_of_the_device(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    async def run(command: list[str], **_kwargs: Any) -> bytes:
        commands.append(command)
        return b"\x01\x00" * 800 + b"\x7f"

    monkeypatch.setattr(announcements, "_async_run_ffmpeg_command", run)

    sound = asyncio.run(announcements.async_sound_for_device("http://ha/api/tts_proxy/x.mp3"))

    with wave.open(io.BytesIO(sound)) as result:
        assert (result.getframerate(), result.getnchannels(), result.getsampwidth()) == (8000, 1, 2)
        assert result.getnframes() == 800
    command = commands[0]
    assert command[command.index("-ar") + 1] == "8000" and command[command.index("-ac") + 1] == "1"
    # ffmpeg may fetch only web addresses, no file or device of the Home Assistant host.
    assert command[command.index("-protocol_whitelist") + 1] == "http,https,tcp,tls,crypto"


@pytest.mark.parametrize("media", ["/config/secrets.yaml", "file:///etc/passwd", "rtsp://camera/stream"])
def test_only_web_addresses_are_converted(media: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run(*_args: Any, **_kwargs: Any) -> bytes:
        raise AssertionError("ffmpeg must not run")

    monkeypatch.setattr(announcements, "_async_run_ffmpeg_command", run)

    with pytest.raises(HomeAssistantError, match="http or https"):
        asyncio.run(announcements.async_sound_for_device(media))


def test_volume_level_maps_to_the_agents_percent() -> None:
    assert [announcements.announcement_volume(level) for level in (0.0, 0.004, 0.6, 1.0, 3.0)] == [
        1, 1, 60, 100, 100]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_real_conversion_of_a_stereo_file_served_over_http() -> None:
    source = io.BytesIO()
    with wave.open(source, "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(22050)
        out.writeframes(b"\x00\x10\x00\x10" * 22050)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(source.getvalue())))
            self.end_headers()
            self.wfile.write(source.getvalue())

        def log_message(self, *_args: Any) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        sound = asyncio.run(announcements.async_sound_for_device(
            f"http://127.0.0.1:{server.server_address[1]}/sound.wav"))
    finally:
        server.shutdown()

    with wave.open(io.BytesIO(sound)) as result:
        assert (result.getframerate(), result.getnchannels(), result.getsampwidth()) == (8000, 1, 2)
        # One second of sound, the lead-in for the speaker and the tail.
        assert 1.5 <= result.getnframes() / 8000 <= 1.7
