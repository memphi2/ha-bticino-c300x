"""The device speaker in Home Assistant: text-to-speech and sounds."""

from __future__ import annotations

import array
import asyncio
import io
import math
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
from homeassistant.helpers.network import NoURLAvailableError  # noqa: E402

from custom_components.bticino_c300x import announcements, media_player  # noqa: E402
from custom_components.bticino_c300x.api import C300XAgentApiError  # noqa: E402
from custom_components.bticino_c300x.media_player import (  # noqa: E402
    C300XSpeaker,
    async_setup_entry,
    media_url_for_ffmpeg,
)

# A status read the agent does not answer.
NO_ANSWER = "no answer"
# The sound is over, the agent still switches the speaker off.
SWITCHING_OFF = "switching off"
# The agent was restarted while it played: no result, busy switching the speaker off.
RESTARTED = "restarted"
# Playing, but the device has not let the agent have its speaker yet.
STARTING = "starting"


class _FakeApi:
    """An agent that takes a sound only while it is not busy with the last one."""

    def __init__(self, *results: str | None, refuse: bool = False, busy_once: bool = False,
                 door_call: bool = False) -> None:
        # What the agent answers to each status read: None while the sound plays.
        self.results = list(results)
        self.refuse = refuse
        # The agent still holds a sound the speaker does not know of.
        self.busy = busy_once
        self.door_call = door_call
        # Set: the agent answers a play only once it is set.
        self.gate: asyncio.Event | None = None
        self.played: list[tuple[bytes, int]] = []
        self.events: list[str] = []
        self.stopped = 0

    async def async_play_announcement(self, sound: bytes, volume: int) -> dict[str, Any]:
        if self.gate is not None:
            await self.gate.wait()
        if self.refuse:
            raise C300XAgentApiError("announcement_unsupported")
        if self.door_call:
            raise C300XAgentApiError("announcement_device_busy")
        if self.busy:
            self.events.append("refused busy")
            raise C300XAgentApiError("announcement_busy")
        self.busy = True
        self.played.append((sound, volume))
        self.events.append(f"play {sound.decode()}")
        return {"ok": True, "playing": True}

    async def async_announcement_status(self) -> Any:
        result = self.results.pop(0)
        self.events.append(f"status {result}")
        if result == NO_ANSWER:
            raise C300XAgentApiError("timeout")
        self.busy = result in (None, SWITCHING_OFF, STARTING)
        if result == SWITCHING_OFF:
            return {"playing": False, "busy": True, "result": "preempted"}
        if result == RESTARTED:
            # A restarted agent switches the speaker off without knowing the sound.
            return {"playing": False, "busy": True, "result": ""}
        if result == STARTING:
            return {"playing": True, "started": False, "busy": True, "result": ""}
        return {"playing": result is None, "started": result is None, "busy": result is None,
                "result": result or ""}

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


class _FakeHass:
    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    def async_create_background_task(self, coro: Any, name: str) -> asyncio.Task[Any]:
        return asyncio.get_running_loop().create_task(coro)


@pytest.fixture
def speaker(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A speaker whose media goes through stand-ins for conversion and waiting."""

    def make(*results: str | None, refuse: bool = False, busy_once: bool = False,
             door_call: bool = False) -> C300XSpeaker:
        api = _FakeApi(*results, refuse=refuse, busy_once=busy_once, door_call=door_call)
        entity = C300XSpeaker(_FakeEntry(api))  # type: ignore[arg-type]
        entity.entity_id = "media_player.c300x_speaker"
        entity.hass = _FakeHass()  # type: ignore[assignment]
        entity.async_write_ha_state = lambda: None  # type: ignore[method-assign]
        return entity

    async def convert(url: str) -> bytes:
        return url.encode()

    monkeypatch.setattr(media_player, "async_sound_for_device", convert)
    monkeypatch.setattr(media_player, "media_url_for_ffmpeg", lambda _hass, url: url)
    monkeypatch.setattr(media_player, "_START_POLL_SECONDS", 0)
    monkeypatch.setattr(media_player, "_POLL_SECONDS", 0)
    return make


async def _played_to_the_end(entity: C300XSpeaker, media: str) -> None:
    await entity.async_play_media("music", media)
    if entity._sound is not None:
        await entity._sound


def test_speaker_exists_only_where_the_agent_can_play_sound() -> None:
    added: list[Any] = []
    asyncio.run(async_setup_entry(None, _FakeEntry(_FakeApi()), added.extend))  # type: ignore[arg-type]
    asyncio.run(async_setup_entry(  # type: ignore[arg-type]
        None, _FakeEntry(_FakeApi(), capabilities={"announcements": {"supported": False}}), added.extend))
    asyncio.run(async_setup_entry(None, _FakeEntry(_FakeApi(), capabilities={}), added.extend))  # type: ignore[arg-type]

    assert [type(entity) for entity in added] == [C300XSpeaker]


def test_plays_speech_at_its_volume_and_is_idle_again_when_the_device_is_done(speaker: Any) -> None:
    entity = speaker(None, None, "played")

    async def run() -> None:
        await entity.async_play_media("music", "hello")
        assert entity.state == MediaPlayerState.PLAYING
        assert entity._sound is not None
        await entity._sound

    asyncio.run(run())

    assert entity._entry.runtime_data.api.played == [(b"hello", 60)]
    assert entity.state == MediaPlayerState.IDLE
    assert entity.extra_state_attributes == {"last_result": "played"}


def test_resolves_a_media_source_before_playing(speaker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    entity = speaker("played")
    asked: list[tuple[str, str]] = []

    async def resolve(_hass: Any, media_id: str, target: str) -> Any:
        asked.append((media_id, target))
        return SimpleNamespace(url="/media/local/ding.wav")

    monkeypatch.setattr(media_player.media_source, "async_resolve_media", resolve)

    asyncio.run(entity.async_play_media("music", "media-source://media_source/local/ding.wav"))

    assert asked == [("media-source://media_source/local/ding.wav", "media_player.c300x_speaker")]
    assert entity._entry.runtime_data.api.played[0][0] == b"/media/local/ding.wav"
    # A sound shorter than the first look is already over.
    assert entity.state == MediaPlayerState.IDLE


def test_a_second_sound_waits_until_the_first_is_over(speaker: Any) -> None:
    entity = speaker(None, None, "played", "played")

    async def run() -> None:
        await asyncio.gather(
            _played_to_the_end(entity, "first"), _played_to_the_end(entity, "second"),
        )

    asyncio.run(run())

    # The agent holds one file: the second upload starts after the first sound ended.
    assert entity._entry.runtime_data.api.events == [
        "play first", "status None", "status None", "status played", "play second", "status played",
    ]


def test_sounds_play_in_the_order_they_were_asked_for(
    speaker: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entity = speaker("played", "played")

    async def convert(url: str) -> bytes:
        # A long text takes longer to convert than a short one asked for after it.
        await asyncio.sleep(0.05 if url == "long" else 0)
        return url.encode()

    monkeypatch.setattr(media_player, "async_sound_for_device", convert)

    async def run() -> None:
        first = asyncio.ensure_future(_played_to_the_end(entity, "long"))
        await asyncio.sleep(0)
        await asyncio.gather(first, _played_to_the_end(entity, "short"))

    asyncio.run(run())

    assert [sound for sound, _volume in entity._entry.runtime_data.api.played] == [b"long", b"short"]


def test_a_request_that_gives_up_lets_the_next_one_play(speaker: Any) -> None:
    entity = speaker("played")

    async def fail(url: str) -> bytes:
        raise HomeAssistantError("conversion failed")

    async def run() -> None:
        with pytest.MonkeyPatch.context() as patch, pytest.raises(HomeAssistantError, match="conversion failed"):
            patch.setattr(media_player, "async_sound_for_device", fail)
            await entity.async_play_media("music", "broken")
        await asyncio.wait_for(_played_to_the_end(entity, "next"), 1)

    asyncio.run(run())

    assert entity._entry.runtime_data.api.played == [(b"next", 60)]


def test_a_request_that_gives_up_in_the_middle_keeps_the_order(
    speaker: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entity = speaker("played", "played")

    async def convert(url: str) -> bytes:
        if url == "broken":
            raise HomeAssistantError("conversion failed")
        await asyncio.sleep(0.05 if url == "long" else 0)
        return url.encode()

    monkeypatch.setattr(media_player, "async_sound_for_device", convert)

    async def run() -> None:
        first = asyncio.ensure_future(_played_to_the_end(entity, "long"))
        await asyncio.sleep(0)
        with pytest.raises(HomeAssistantError, match="conversion failed"):
            await entity.async_play_media("music", "broken")
        await asyncio.gather(first, _played_to_the_end(entity, "short"))

    asyncio.run(run())

    assert [sound for sound, _volume in entity._entry.runtime_data.api.played] == [b"long", b"short"]


def test_a_caller_that_leaves_in_the_middle_keeps_the_order(
    speaker: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entity = speaker("played", "played")

    async def convert(url: str) -> bytes:
        await asyncio.sleep(0.05 if url == "long" else 0.02 if url == "left" else 0)
        return url.encode()

    monkeypatch.setattr(media_player, "async_sound_for_device", convert)

    async def run() -> None:
        first = asyncio.ensure_future(_played_to_the_end(entity, "long"))
        await asyncio.sleep(0)
        left = asyncio.ensure_future(entity.async_play_media("music", "left"))
        await asyncio.sleep(0)
        last = asyncio.ensure_future(_played_to_the_end(entity, "short"))
        await asyncio.sleep(0)
        left.cancel()
        await asyncio.wait_for(asyncio.gather(first, last), 2)

    asyncio.run(run())

    assert [sound for sound, _volume in entity._entry.runtime_data.api.played] == [b"long", b"short"]


def test_a_second_sound_waits_until_the_speaker_is_switched_off(speaker: Any) -> None:
    entity = speaker(None, SWITCHING_OFF, "played", "played")

    async def run() -> None:
        await asyncio.gather(
            _played_to_the_end(entity, "first"), _played_to_the_end(entity, "second"),
        )

    asyncio.run(run())

    # The first sound is over at once; the second is taken once the speaker is off.
    assert entity._entry.runtime_data.api.events == [
        "play first", "status None", "status switching off",
        "refused busy", "status played", "play second", "status played",
    ]
    assert entity.extra_state_attributes == {"last_result": "played"}


def test_says_so_when_the_device_keeps_its_speaker_for_a_call(speaker: Any) -> None:
    entity = speaker("device_busy")

    with pytest.raises(HomeAssistantError, match="using its speaker"):
        asyncio.run(entity.async_play_media("music", "x"))

    assert entity.state == MediaPlayerState.IDLE
    assert entity.extra_state_attributes == {"last_result": "device_busy"}


def test_a_device_that_uses_its_speaker_is_said_also_when_it_takes_a_moment(speaker: Any) -> None:
    # The agent plays, but the device has not let it have the speaker yet.
    entity = speaker(STARTING, STARTING, "device_busy")

    with pytest.raises(HomeAssistantError, match="using its speaker"):
        asyncio.run(entity.async_play_media("music", "x"))

    assert entity.extra_state_attributes == {"last_result": "device_busy"}


def test_a_sound_counts_as_started_only_once_the_device_let_it_have_the_speaker(
    speaker: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entity = speaker(STARTING, None, "played")
    # Following the started sound is slower than waiting for its start.
    monkeypatch.setattr(media_player, "_POLL_SECONDS", 0.05)

    async def run() -> None:
        await entity.async_play_media("music", "x")
        # The action returned once the agent said the device let it have the speaker.
        assert entity._entry.runtime_data.api.events == ["play x", "status starting", "status None"]
        assert entity._sound is not None
        await entity._sound

    asyncio.run(run())

    assert entity.extra_state_attributes == {"last_result": "played"}


def test_says_so_when_a_door_call_is_under_way(speaker: Any) -> None:
    entity = speaker(door_call=True)

    with pytest.raises(HomeAssistantError, match="using its speaker"):
        asyncio.run(entity.async_play_media("music", "x"))

    assert entity.extra_state_attributes == {"last_result": "device_busy"}


def test_a_door_call_that_cuts_the_sound_is_no_error(speaker: Any) -> None:
    # The agent leaves the speaker to the device for the call; the sound is over at once.
    entity = speaker(None, SWITCHING_OFF)

    asyncio.run(_played_to_the_end(entity, "x"))

    assert entity.state == MediaPlayerState.IDLE
    assert entity.extra_state_attributes == {"last_result": "preempted"}


def test_a_status_read_without_answer_is_tried_again(speaker: Any) -> None:
    entity = speaker(NO_ANSWER, None, NO_ANSWER, "played")

    asyncio.run(_played_to_the_end(entity, "x"))

    assert entity.extra_state_attributes == {"last_result": "played"}
    assert entity.state == MediaPlayerState.IDLE


def test_a_missing_answer_at_the_start_is_asked_for_again(speaker: Any) -> None:
    entity = speaker(NO_ANSWER, "device_busy")

    with pytest.raises(HomeAssistantError, match="using its speaker"):
        asyncio.run(entity.async_play_media("music", "x"))


def test_a_sound_the_agent_never_reports_ends_after_its_time(
    speaker: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(media_player, "_END_MARGIN_SECONDS", -1)
    monkeypatch.setattr(media_player, "_START_SECONDS", 0)
    entity = speaker(NO_ANSWER)

    asyncio.run(_played_to_the_end(entity, "x"))

    assert entity.extra_state_attributes == {"last_result": "unknown"}
    assert entity.state == MediaPlayerState.IDLE


def test_says_so_when_the_agent_refuses_the_sound(speaker: Any) -> None:
    entity = speaker(refuse=True)

    with pytest.raises(HomeAssistantError, match="was not played: announcement_unsupported"):
        asyncio.run(entity.async_play_media("music", "x"))

    assert entity.state == MediaPlayerState.IDLE
    assert entity.extra_state_attributes == {"last_result": "not_played"}


def test_an_unexpected_failure_is_no_success(speaker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    entity = speaker()

    async def broken(_sound: bytes, _volume: int) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(entity._entry.runtime_data.api, "async_play_announcement", broken)

    with pytest.raises(HomeAssistantError, match="unexpectedly"):
        asyncio.run(entity.async_play_media("music", "x"))

    assert entity.extra_state_attributes == {"last_result": "failed"}


def test_a_failure_nobody_waits_for_any_more_is_logged(
    speaker: Any, caplog: pytest.LogCaptureFixture,
) -> None:
    entity = speaker(door_call=True)

    async def run() -> None:
        api = entity._entry.runtime_data.api
        api.gate = asyncio.Event()
        play = asyncio.create_task(entity.async_play_media("music", "x"))
        for _ in range(100):
            if entity._sound is not None:
                break
            await asyncio.sleep(0)
        play.cancel()
        with pytest.raises(asyncio.CancelledError):
            await play
        api.gate.set()
        assert entity._sound is not None
        await entity._sound

    asyncio.run(run())

    assert "using its speaker" in caplog.text


def test_nothing_is_played_once_the_speaker_was_removed(
    speaker: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entity = speaker("played")

    async def run() -> None:
        converting, release = asyncio.Event(), asyncio.Event()

        async def slow(url: str) -> bytes:
            converting.set()
            await release.wait()
            return url.encode()

        monkeypatch.setattr(media_player, "async_sound_for_device", slow)
        play = asyncio.create_task(entity.async_play_media("music", "x"))
        await converting.wait()
        await entity.async_will_remove_from_hass()
        release.set()
        with pytest.raises(HomeAssistantError, match="removed"):
            await play

    asyncio.run(run())

    assert entity._entry.runtime_data.api.played == []


def test_a_caller_gets_an_answer_when_the_speaker_is_removed_while_its_sound_starts(speaker: Any) -> None:
    entity = speaker()
    api = entity._entry.runtime_data.api

    async def run() -> None:
        # The agent does not answer the play request yet.
        api.gate = asyncio.Event()
        play = asyncio.create_task(entity.async_play_media("music", "x"))
        for _step in range(5):
            await asyncio.sleep(0)
        sound = entity._sound
        assert sound is not None
        await entity.async_will_remove_from_hass()
        with pytest.raises(HomeAssistantError, match="removed while the sound started"):
            await asyncio.wait_for(play, 2)
        await asyncio.wait({sound})
        assert sound.cancelled()

    asyncio.run(run())

    assert api.played == []


def test_plays_again_after_its_id_was_renamed(speaker: Any) -> None:
    entity = speaker("played")

    async def run() -> None:
        # Home Assistant removes the entity and adds the same one again.
        await entity.async_will_remove_from_hass()
        entity.async_get_last_extra_data = _no_saved_data  # type: ignore[method-assign]
        await entity.async_added_to_hass()
        await _played_to_the_end(entity, "x")

    asyncio.run(run())

    assert entity.extra_state_attributes == {"last_result": "played"}


async def _no_saved_data() -> None:
    return None


def test_a_caller_that_gives_up_does_not_lose_the_playing_sound(speaker: Any) -> None:
    entity = speaker(None, None, "played", "played")

    async def run() -> None:
        first = asyncio.create_task(entity.async_play_media("music", "first"))
        for _ in range(100):
            if entity._entry.runtime_data.api.played:
                break
            await asyncio.sleep(0)
        # For example an automation that is restarted.
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        await _played_to_the_end(entity, "second")

    asyncio.run(run())

    assert entity._entry.runtime_data.api.events == [
        "play first", "status None", "status None", "status played", "play second", "status played",
    ]


def test_waits_for_a_sound_the_agent_still_holds_from_before(speaker: Any) -> None:
    # For example after a reload while a sound played.
    entity = speaker(None, "played", "played", busy_once=True)

    asyncio.run(_played_to_the_end(entity, "x"))

    assert entity._entry.runtime_data.api.events == [
        "refused busy", "status None", "status played", "play x", "status played",
    ]
    assert entity.extra_state_attributes == {"last_result": "played"}


def test_a_sound_the_restarted_agent_forgot_is_over_at_once(speaker: Any) -> None:
    entity = speaker(None, RESTARTED)

    asyncio.run(_played_to_the_end(entity, "x"))

    assert entity.extra_state_attributes == {"last_result": "unknown"}
    assert entity.state == MediaPlayerState.IDLE


def test_volume_is_kept_for_the_next_sound_and_over_a_restart(speaker: Any) -> None:
    entity = speaker("played", "played")

    async def last_data() -> Any:
        # Saved while the entity was unavailable: the state has no volume, the data has.
        return SimpleNamespace(as_dict=lambda: {"volume": 0.25})

    async def run() -> None:
        await entity.async_set_volume_level(1.0)
        await _played_to_the_end(entity, "x")
        assert entity.extra_restore_state_data.as_dict() == {"volume": 1.0}
        entity.async_get_last_extra_data = last_data  # type: ignore[method-assign]
        await entity.async_added_to_hass()
        await _played_to_the_end(entity, "x")

    asyncio.run(run())

    assert [volume for _sound, volume in entity._entry.runtime_data.api.played] == [100, 25]


def test_stop_asks_the_agent_to_end_the_sound(speaker: Any) -> None:
    entity = speaker()

    asyncio.run(entity.async_media_stop())

    assert entity._entry.runtime_data.api.stopped == 1


def test_ffmpeg_fetches_home_assistant_media_over_the_internal_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass: Any = SimpleNamespace(config=SimpleNamespace(api=SimpleNamespace(use_ssl=True, port=8123)))
    asked: list[dict[str, Any]] = []
    internal = {"url": "http://homeassistant.local:8123"}

    def process(_hass: Any, url: str, *, allow_relative_url: bool = False) -> str:
        assert allow_relative_url
        return url if url.startswith("http") else url + "?authSig=x"

    def get_url(_hass: Any, **kwargs: Any) -> str:
        asked.append(kwargs)
        if not internal["url"]:
            raise NoURLAvailableError
        return internal["url"]

    monkeypatch.setattr(media_player, "async_process_play_media_url", process)
    monkeypatch.setattr(media_player, "get_url", get_url)

    assert media_url_for_ffmpeg(hass, "/api/tts_proxy/a.mp3") == (
        "http://homeassistant.local:8123/api/tts_proxy/a.mp3?authSig=x")
    # Also an internal address written as an IP, which HTTPS leaves out by default.
    assert asked == [{"allow_external": False, "allow_cloud": False, "allow_ip": True}]
    internal["url"] = ""
    assert media_url_for_ffmpeg(hass, "/api/tts_proxy/a.mp3") == (
        "https://127.0.0.1:8123/api/tts_proxy/a.mp3?authSig=x")
    assert media_url_for_ffmpeg(hass, "https://radio.example/a.mp3") == "https://radio.example/a.mp3"


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
    assert announcements.announcement_seconds(sound) == 0.1
    command = commands[0]
    assert command[command.index("-ar") + 1] == "8000" and command[command.index("-ac") + 1] == "1"
    # ffmpeg may fetch only web addresses, no file or device of the Home Assistant host.
    assert command[command.index("-protocol_whitelist") + 1] == "http,https,tcp,tls,crypto"


def test_a_failed_conversion_does_not_tell_the_signature_or_password(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "http://user:secret@ha:8123/media/local/x.mp3?authSig=signature"

    async def run(command: list[str], **_kwargs: Any) -> bytes:
        raise HomeAssistantError(f"C300X announcement could not be converted: {url}: 404 Not Found" + "x" * 900)

    monkeypatch.setattr(announcements, "_async_run_ffmpeg_command", run)

    with pytest.raises(HomeAssistantError) as raised:
        asyncio.run(announcements.async_sound_for_device(url))

    message = str(raised.value)
    assert "http://ha/media/local/x.mp3: 404 Not Found" in message
    assert "signature" not in message and "secret" not in message
    assert len(message) <= 300


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


def _served(content: bytes) -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *_args: Any) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/sound.wav"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_real_conversion_of_a_stereo_file_has_one_tone_after_the_lead_in() -> None:
    # Two seconds of stereo silence with one short tone at 0.5 s in both channels.
    rate = 22050
    samples = array.array("h", [0] * rate * 2 * 2)
    for frame in range(int(rate * 0.5), int(rate * 0.55)):
        value = int(12000 * math.sin(2 * math.pi * 1000 * frame / rate))
        samples[2 * frame] = samples[2 * frame + 1] = value
    source = io.BytesIO()
    with wave.open(source, "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(samples.tobytes())

    server, url = _served(source.getvalue())
    try:
        sound = asyncio.run(announcements.async_sound_for_device(url))
    finally:
        server.shutdown()

    with wave.open(io.BytesIO(sound)) as result:
        assert (result.getframerate(), result.getnchannels(), result.getsampwidth()) == (8000, 1, 2)
        pcm = array.array("h", result.readframes(result.getnframes()))

    def loudest(start: float, end: float) -> int:
        return max(abs(value) for value in pcm[int(start * 8000):int(end * 8000)])

    # The tone comes once, 300 ms later for the speaker to switch on; no echo of one channel.
    assert loudest(0.78, 0.88) > 5000
    assert loudest(0.40, 0.70) < 500
    assert loudest(0.95, 1.40) < 500
    assert 2.5 <= len(pcm) / 8000 <= 2.7
