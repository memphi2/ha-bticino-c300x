from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
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
from custom_components.bticino_c300x.snapshot_store import SnapshotStore
from custom_components.bticino_c300x.snapshots import StreamSnapshots


class _FakeConfigEntries:
    def __init__(self, entries: list[Any]) -> None:
        self._entries = entries

    def async_entries(self, domain: str) -> list[Any]:
        return [entry for entry in self._entries if entry.domain == domain]

    def async_get_entry(self, entry_id: str) -> Any | None:
        return next(
            (entry for entry in self._entries if entry.entry_id == entry_id), None
        )


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


def test_media_source_fetch_helpers_use_cached_reads(monkeypatch) -> None:
    import custom_components.bticino_c300x.media_source as module

    async def _messages(_entry: Any, *, force_refresh: bool) -> dict[str, Any]:
        return {"messages": [{"force_refresh": force_refresh}]}

    async def _memos(_entry: Any, *, force_refresh: bool) -> dict[str, Any]:
        return {"memos": [{"force_refresh": force_refresh}]}

    monkeypatch.setattr(module, "async_answering_machine_messages", _messages)
    monkeypatch.setattr(module, "async_memos", _memos)
    entry = _FakeEntry("entry1", runtime_data=object())

    assert asyncio.run(_async_messages_for_entry(entry)) == {
        "messages": [{"force_refresh": False}]
    }
    assert asyncio.run(_async_memos_for_entry(entry)) == {
        "memos": [{"force_refresh": False}]
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
    assert [
        (child.identifier, child.media_content_type) for child in browse.children
    ] == [("capture/doorbell_20260719_100000.mp4", "video/mp4")]


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
        _FakeHass(
            [
                _FakeEntry("with-runtime", runtime_data=object()),
                _FakeEntry("without-runtime"),
            ]
        )
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


@pytest.mark.parametrize("identifier", ["capture/a%00.mp4", "capture/a%0A.mp4"])
def test_resolve_media_rejects_a_capture_name_with_a_control_character(
    tmp_path: Path, identifier: str
) -> None:
    source = C300XStoredMediaSource(_FakeHass([], tmp_path / "config"))  # type: ignore[arg-type]

    with pytest.raises(Unresolvable):
        asyncio.run(source.async_resolve_media(_item(identifier)))


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


@pytest.fixture
def archive(tmp_path, monkeypatch):
    import custom_components.bticino_c300x.media_source as module
    import custom_components.bticino_c300x.snapshot_store as storage

    now = 1_800_000_000
    monkeypatch.setattr(storage.time, "time", lambda: now)
    entry = SimpleNamespace(
        entry_id="entry1",
        domain=DOMAIN,
        title="Front door",
        runtime_data=object(),
        data={},
        options={"snapshot_retention_days": 2},
    )
    hass = _FakeHass([entry], tmp_path)
    # Use the real manager's serialized disk helper without starting its lifecycle.
    manager = object.__new__(StreamSnapshots)
    manager.hass = hass
    manager.entry = entry
    manager.store = SnapshotStore(hass, entry.entry_id)
    manager.lock = asyncio.Lock()
    manager._jobs = set()
    manager._cancel_retention = None
    manager.closed = False
    manager.enabled = True
    hass.data = {DOMAIN: {"stream_snapshots": {entry.entry_id: manager}}}
    manager.store.root.mkdir(parents=True)

    def image(age, digest):
        name = f"c300x-{int((now - age) * 1000):013d}-{digest * 32}.jpg"
        (manager.store.root / name).write_bytes(b"stored jpeg")
        return name

    recent = image(60, "a")
    older = image(86400, "b")
    expired = image(2 * 86400, "c")

    async def offline(_entry):
        raise module.C300XAgentApiError("offline")

    monkeypatch.setattr(module, "_async_messages_for_entry", offline)
    monkeypatch.setattr(module, "_async_memos_for_entry", offline)
    return SimpleNamespace(
        source=C300XStoredMediaSource(hass),
        manager=manager,
        recent=recent,
        older=older,
        expired=expired,
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_snapshot_archive_browse_and_resolve_even_when_capture_off(archive, enabled):
    archive.manager.enabled = enabled

    async def check():
        root = await archive.source.async_browse_media(_item(None))
        assert [child.identifier for child in root.children] == [
            "snapshot/entry1",
            "capture",
        ]
        folder = await archive.source.async_browse_media(_item("snapshot/entry1"))
        assert folder.title == "Front door - Stream images"
        assert folder.can_expand and not folder.can_play
        assert [child.identifier for child in folder.children] == [
            f"snapshot/entry1/{archive.recent}",
            f"snapshot/entry1/{archive.older}",
        ]
        for child in folder.children:
            assert child.can_play and not child.can_expand
            assert child.media_content_type == "image/jpeg"
            media = await archive.source.async_resolve_media(_item(child.identifier))
            assert media.mime_type == "image/jpeg"
            assert media.url == child.thumbnail
            assert (
                media.url
                == f"/api/{DOMAIN}/snapshots/entry1/{child.identifier.rsplit('/', 1)[1]}"
            )
        assert not (archive.manager.store.root / archive.expired).exists()

    asyncio.run(check())


def test_snapshot_resolve_rejects_expired_and_missing_images(archive):
    for name in (archive.expired, "c300x-1800000000000-" + "d" * 32 + ".jpg"):
        with pytest.raises(Unresolvable, match="expired or does not exist"):
            asyncio.run(
                archive.source.async_resolve_media(_item(f"snapshot/entry1/{name}"))
            )


@pytest.mark.parametrize("closed", [True, False])
def test_snapshot_unknown_or_closed_store_is_unavailable(archive, closed):
    archive.manager.closed = closed
    entry_id = "entry1" if closed else "missing"
    with pytest.raises(BrowseError, match="Unknown"):
        asyncio.run(archive.source.async_browse_media(_item(f"snapshot/{entry_id}")))
    with pytest.raises(Unresolvable, match="Unknown"):
        asyncio.run(
            archive.source.async_resolve_media(
                _item(f"snapshot/{entry_id}/{archive.recent}")
            )
        )
    if closed:
        root = asyncio.run(archive.source.async_browse_media(_item(None)))
        assert [child.identifier for child in root.children] == ["capture"]


@pytest.mark.parametrize(
    "name",
    [
        "",
        "..",
        "../private.jpg",
        "/etc/passwd",
        "bad.jpg",
        "a\\private.jpg",
        "%2e%2e%2fprivate.jpg",
        "%252e%252e%252fprivate.jpg",
        "bad\x00.jpg",
    ],
)
def test_snapshot_rejects_invalid_names_and_traversal(archive, name):
    outside = archive.manager.store.root.parent / "private.jpg"
    outside.write_bytes(b"private")
    with pytest.raises(Unresolvable):
        asyncio.run(
            archive.source.async_resolve_media(_item(f"snapshot/entry1/{name}"))
        )
    assert outside.read_bytes() == b"private"


@pytest.mark.parametrize(
    "operation,error_type",
    [
        ("browse", BrowseError),
        ("resolve", Unresolvable),
    ],
)
@pytest.mark.parametrize(
    "failure", [OSError("disk unavailable"), ValueError("unsafe root")]
)
def test_snapshot_storage_errors_are_translated(
    archive, monkeypatch, operation, error_type, failure
):
    def fail(*args):
        assert archive.manager.lock.locked()
        raise failure

    monkeypatch.setattr(
        archive.manager.store, "items" if operation == "browse" else "read", fail
    )
    identifier = "snapshot/entry1"
    if operation == "resolve":
        identifier += f"/{archive.recent}"
    method = getattr(archive.source, f"async_{operation}_media")
    with pytest.raises(error_type) as caught:
        asyncio.run(method(_item(identifier)))
    assert caught.value.__cause__ is failure
    assert not archive.manager.lock.locked()


@pytest.mark.parametrize(
    "operation,error_type",
    [
        ("browse", BrowseError),
        ("resolve", Unresolvable),
    ],
)
@pytest.mark.parametrize("during_io", [False, True])
def test_snapshot_close_during_wait_or_disk_job(
    archive, monkeypatch, operation, error_type, during_io
):
    identifier = "snapshot/entry1"
    if operation == "resolve":
        identifier += f"/{archive.recent}"
    method = getattr(archive.source, f"async_{operation}_media")

    async def check():
        if during_io:
            original = archive.manager.disk_job

            async def close_after_read(*args):
                result = await original(*args)
                archive.manager.closed = True
                return result

            monkeypatch.setattr(archive.manager, "disk_job", close_after_read)
            with pytest.raises(error_type, match="Unknown"):
                await method(_item(identifier))
        else:
            await archive.manager.lock.acquire()
            task = asyncio.create_task(method(_item(identifier)))
            await asyncio.sleep(0)
            assert not task.done()
            archive.manager.closed = True
            archive.manager.lock.release()
            with pytest.raises(error_type, match="Unknown"):
                await task

    asyncio.run(check())
