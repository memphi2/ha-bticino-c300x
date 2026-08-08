from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from homeassistant.components.media_source import (  # noqa: F401
        MediaSourceItem as _HomeAssistantMediaSourceItem,
    )
except ModuleNotFoundError:
    homeassistant = sys.modules.setdefault(
        "homeassistant",
        types.ModuleType("homeassistant"),
    )
    components = sys.modules.setdefault(
        "homeassistant.components",
        types.ModuleType("homeassistant.components"),
    )
    media_player = types.ModuleType("homeassistant.components.media_player")
    media_source = types.ModuleType("homeassistant.components.media_source")
    core = sys.modules.setdefault(
        "homeassistant.core",
        types.ModuleType("homeassistant.core"),
    )
    helpers = sys.modules.setdefault(
        "homeassistant.helpers",
        types.ModuleType("homeassistant.helpers"),
    )
    dispatcher = sys.modules.setdefault(
        "homeassistant.helpers.dispatcher",
        types.ModuleType("homeassistant.helpers.dispatcher"),
    )

    class BrowseError(Exception):  # pragma: no cover - import-time stub only
        pass

    class Unresolvable(Exception):  # pragma: no cover - import-time stub only
        pass

    class MediaClass:  # pragma: no cover - import-time stub only
        APP = "app"
        DIRECTORY = "directory"
        MUSIC = "music"
        VIDEO = "video"

    @dataclass
    class PlayMedia:  # pragma: no cover - import-time stub only
        url: str
        mime_type: str

    @dataclass
    class BrowseMediaSource:  # pragma: no cover - import-time stub only
        domain: str
        identifier: str | None
        media_class: str
        media_content_type: str
        title: str
        can_play: bool
        can_expand: bool
        children_media_class: str | None = None
        children: list[Any] | None = None

    @dataclass
    class MediaSourceItem:  # pragma: no cover - import-time stub only
        domain: str
        identifier: str | None

    class MediaSource:  # pragma: no cover - import-time stub only
        def __init__(self, domain: str) -> None:
            self.domain = domain

    class HomeAssistant:  # pragma: no cover - import-time stub only
        pass

    media_player.BrowseError = BrowseError
    media_player.MediaClass = MediaClass
    media_source.BrowseError = BrowseError
    media_source.BrowseMediaSource = BrowseMediaSource
    media_source.MediaSource = MediaSource
    media_source.MediaSourceItem = MediaSourceItem
    media_source.PlayMedia = PlayMedia
    media_source.Unresolvable = Unresolvable
    core.HomeAssistant = HomeAssistant
    dispatcher.async_dispatcher_send = lambda *_args, **_kwargs: None
    components.media_player = media_player
    components.media_source = media_source
    homeassistant.components = components
    homeassistant.helpers = helpers
    helpers.dispatcher = dispatcher
    sys.modules["homeassistant.components.media_player"] = media_player
    sys.modules["homeassistant.components.media_source"] = media_source

components = sys.modules.setdefault(
    "homeassistant.components",
    types.ModuleType("homeassistant.components"),
)
http = sys.modules.setdefault(
    "homeassistant.components.http",
    types.ModuleType("homeassistant.components.http"),
)
if not hasattr(http, "HomeAssistantView"):

    class HomeAssistantView:  # pragma: no cover - import-time stub only
        extra_urls: list[str] = []

    http.HomeAssistantView = HomeAssistantView
components.http = http

from homeassistant.components.media_player import BrowseError  # noqa: E402
from homeassistant.components.media_source import (  # noqa: E402
    MediaSourceItem,
    Unresolvable,
)

from custom_components.bticino_c300x.const import DOMAIN  # noqa: E402
from custom_components.bticino_c300x.media_source import (  # noqa: E402
    C300XStoredMediaSource,
    _async_memos_for_entry,
    _async_messages_for_entry,
    _message_children,
    _parse_identifier,
    _voice_memo_children,
    async_get_media_source,
)


class _FakeConfigEntries:
    def __init__(self, entries: list[Any]) -> None:
        self._entries = entries

    def async_entries(self, domain: str) -> list[Any]:
        return [entry for entry in self._entries if entry.domain == domain]

    def async_get_entry(self, entry_id: str) -> Any | None:
        return next((entry for entry in self._entries if entry.entry_id == entry_id), None)


class _FakeHass:
    def __init__(self, entries: list[Any], root: Path | None = None) -> None:
        self.config_entries = _FakeConfigEntries(entries)
        self.config = _FakeConfig(root or Path("/config"))

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        return func(*args)


class _FakeConfig:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.media_dirs = {"local": str(root / "media")}

    def path(self, *parts: str) -> str:
        return str(self.root.joinpath(*parts))


class _FakeEntry:
    domain = DOMAIN

    def __init__(self, entry_id: str, *, runtime_data: Any | None = None) -> None:
        self.entry_id = entry_id
        if runtime_data is not None:
            self.runtime_data = runtime_data


def _item(identifier: str | None, hass: Any | None = None) -> MediaSourceItem:
    value = identifier or ""
    try:
        return MediaSourceItem(hass or _FakeHass([]), DOMAIN, value, None)
    except TypeError:
        return MediaSourceItem(domain=DOMAIN, identifier=value)


def test_parse_media_source_identifier_accepts_video_and_voice_forms() -> None:
    assert _parse_identifier("entry%201/message_1") == (
        "video",
        "entry 1",
        "message_1",
    )
    assert _parse_identifier("video/entry%201/message_1") == (
        "video",
        "entry 1",
        "message_1",
    )
    assert _parse_identifier("voice/entry%201/memo_1") == (
        "voice",
        "entry 1",
        "voice/memo_1",
    )
    assert _parse_identifier("capture/doorbell_20260719_100000.mp4") == (
        "capture",
        "",
        "doorbell_20260719_100000.mp4",
    )


def test_parse_media_source_identifier_rejects_incomplete_or_invalid_values() -> None:
    for identifier in (None, "", "entry-only", "voice/entry", "video/entry"):
        try:
            _parse_identifier(identifier)
        except Unresolvable:
            continue
        raise AssertionError(f"{identifier!r} should not resolve")

    for identifier in ("entry/%2Fbad", "voice/entry/%2Fbad"):
        try:
            _parse_identifier(identifier)
        except Unresolvable:
            continue
        raise AssertionError(f"{identifier!r} should not resolve")


def test_media_source_children_use_playable_video_voice_and_capture_items() -> None:
    messages = {
        "messages": [
            {"id": "message_1", "has_video": True, "iso_time": "2026-06-13T01:00:00"},
            {"id": "message_text", "has_video": False},
            {"id": "", "has_video": True},
        ]
    }
    memos = {
        "memos": [
            {
                "id": "voice/memo_1",
                "kind": "voice",
                "has_audio": True,
                "audio_mime_type": "audio/wav",
                "iso_time": "2026-06-13T01:01:00",
            },
            {"id": "text/memo_2", "kind": "text", "has_audio": False},
            {"id": "voice_no_slash", "kind": "voice", "has_audio": True},
        ]
    }

    video_children = _message_children("entry 1", messages)
    voice_children = _voice_memo_children("entry 1", memos)

    assert [child.identifier for child in video_children] == ["entry 1/message_1"]
    assert [child.identifier for child in voice_children] == ["voice/entry 1/memo_1"]
    assert video_children[0].can_play is True
    assert voice_children[0].can_play is True
    assert video_children[0].media_content_type == "video/mp4"
    assert voice_children[0].media_content_type == "audio/wav"


def test_media_source_fetch_helpers_force_refresh(monkeypatch) -> None:
    import custom_components.bticino_c300x.media_source as module

    async def _messages(_entry: Any, *, force_refresh: bool) -> dict[str, Any]:
        return {"messages": [{"force_refresh": force_refresh}]}

    async def _memos(_entry: Any, *, force_refresh: bool) -> dict[str, Any]:
        return {"memos": [{"force_refresh": force_refresh}]}

    monkeypatch.setattr(module, "async_answering_machine_messages", _messages)
    monkeypatch.setattr(module, "async_memos", _memos)
    entry = _FakeEntry("entry1", runtime_data=object())

    assert asyncio.run(_async_messages_for_entry(entry)) == {
        "messages": [{"force_refresh": True}]
    }
    assert asyncio.run(_async_memos_for_entry(entry)) == {
        "memos": [{"force_refresh": True}]
    }


def test_async_get_media_source_returns_c300x_media_source() -> None:
    source = asyncio.run(async_get_media_source(_FakeHass([])))  # type: ignore[arg-type]

    assert isinstance(source, C300XStoredMediaSource)
    assert source.domain == DOMAIN


def test_browse_media_lists_video_messages_and_voice_memos(monkeypatch) -> None:
    async def _messages(entry: Any) -> dict[str, Any]:
        return {
            "messages": [
                {"id": f"{entry.entry_id}_video", "has_video": True},
            ]
        }

    async def _memos(entry: Any) -> dict[str, Any]:
        return {
            "memos": [
                {
                    "id": f"voice/{entry.entry_id}_memo",
                    "kind": "voice",
                    "has_audio": True,
                },
            ]
        }

    import custom_components.bticino_c300x.media_source as module

    monkeypatch.setattr(module, "_async_messages_for_entry", _messages)
    monkeypatch.setattr(module, "_async_memos_for_entry", _memos)
    entry = _FakeEntry("entry1", runtime_data=object())
    source = C300XStoredMediaSource(_FakeHass([entry]))  # type: ignore[arg-type]

    browse = asyncio.run(source.async_browse_media(_item(None)))

    assert browse.domain == DOMAIN
    assert browse.can_expand is True
    assert [child.identifier for child in browse.children] == [
        "entry1/entry1_video",
        "voice/entry1/entry1_memo",
        "capture",
    ]


def test_browse_media_lists_ring_captures(tmp_path: Path) -> None:
    media_dir = tmp_path / "config" / "media" / "c300x"
    media_dir.mkdir(parents=True)
    capture = media_dir / "doorbell_20260719_100000.mp4"
    capture.write_bytes(b"mp4")
    source = C300XStoredMediaSource(_FakeHass([], tmp_path / "config"))  # type: ignore[arg-type]

    browse = asyncio.run(source.async_browse_media(_item("capture")))

    assert browse.identifier == "capture"
    assert browse.title == "Ring captures"
    assert browse.can_expand is True
    assert [(child.identifier, child.media_content_type) for child in browse.children] == [
        ("capture/doorbell_20260719_100000.mp4", "video/mp4")
    ]


def test_browse_media_ignores_entries_without_runtime_data_and_agent_errors(
    monkeypatch,
) -> None:
    import custom_components.bticino_c300x.media_source as module
    from custom_components.bticino_c300x.api import C300XAgentApiError

    async def _messages(_entry: Any) -> dict[str, Any]:
        raise C300XAgentApiError("offline")

    async def _memos(_entry: Any) -> dict[str, Any]:
        raise C300XAgentApiError("offline")

    monkeypatch.setattr(module, "_async_messages_for_entry", _messages)
    monkeypatch.setattr(module, "_async_memos_for_entry", _memos)
    source = C300XStoredMediaSource(
        _FakeHass([
            _FakeEntry("with-runtime", runtime_data=object()),
            _FakeEntry("without-runtime"),
        ])
    )  # type: ignore[arg-type]

    browse = asyncio.run(source.async_browse_media(_item(None)))

    assert [child.identifier for child in browse.children] == ["capture"]


def test_browse_media_rejects_nested_identifiers() -> None:
    source = C300XStoredMediaSource(_FakeHass([]))  # type: ignore[arg-type]

    try:
        asyncio.run(source.async_browse_media(_item("entry/message")))
    except BrowseError:
        return
    raise AssertionError("nested browse identifier should be rejected")


def test_resolve_media_returns_video_and_voice_proxy_urls(monkeypatch) -> None:
    async def _messages(_entry: Any) -> dict[str, Any]:
        return {"messages": [{"id": "message_1", "has_video": True}]}

    async def _memos(_entry: Any) -> dict[str, Any]:
        return {
            "memos": [
                {
                    "id": "voice/memo_1",
                    "kind": "voice",
                    "has_audio": True,
                    "audio_mime_type": "audio/x-wav",
                }
            ]
        }

    import custom_components.bticino_c300x.media_source as module

    monkeypatch.setattr(module, "_async_messages_for_entry", _messages)
    monkeypatch.setattr(module, "_async_memos_for_entry", _memos)
    source = C300XStoredMediaSource(
        _FakeHass([_FakeEntry("entry1", runtime_data=object())])
    )  # type: ignore[arg-type]

    video = asyncio.run(source.async_resolve_media(_item("entry1/message_1")))
    voice = asyncio.run(source.async_resolve_media(_item("voice/entry1/memo_1")))

    assert video.url == "/api/bticino_c300x/video-messages/entry1/message_1/video.mp4"
    assert video.mime_type == "video/mp4"
    assert voice.url == "/api/bticino_c300x/voice-memos/entry1/memo_1/audio"
    assert voice.mime_type == "audio/x-wav"


def test_resolve_media_returns_ring_capture_proxy_url(tmp_path: Path) -> None:
    media_dir = tmp_path / "config" / "media" / "c300x"
    media_dir.mkdir(parents=True)
    capture = media_dir / "doorbell_20260719_100000.mp4"
    capture.write_bytes(b"mp4")
    source = C300XStoredMediaSource(_FakeHass([], tmp_path / "config"))  # type: ignore[arg-type]

    media = asyncio.run(
        source.async_resolve_media(_item("capture/doorbell_20260719_100000.mp4"))
    )

    assert media.url == (
        "/api/bticino_c300x/ring-captures/doorbell_20260719_100000.mp4"
    )
    assert media.mime_type == "video/mp4"


def test_resolve_media_rejects_missing_entry_or_media(monkeypatch) -> None:
    async def _empty(_entry: Any) -> dict[str, Any]:
        return {"messages": [], "memos": []}

    import custom_components.bticino_c300x.media_source as module

    monkeypatch.setattr(module, "_async_messages_for_entry", _empty)
    monkeypatch.setattr(module, "_async_memos_for_entry", _empty)
    source = C300XStoredMediaSource(
        _FakeHass([_FakeEntry("entry1", runtime_data=object())])
    )  # type: ignore[arg-type]

    for identifier in (
        "missing/message_1",
        "entry1/message_1",
        "voice/entry1/memo_1",
        "capture/missing.mp4",
    ):
        try:
            asyncio.run(source.async_resolve_media(_item(identifier)))
        except Unresolvable:
            continue
        raise AssertionError(f"{identifier!r} should not resolve")
