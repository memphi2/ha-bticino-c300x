"""Journal metadata, authority and local-only media associations."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant
from test_stream_snapshot_store import jpeg
from test_stream_snapshots import manager_for

from custom_components.bticino_c300x import visitor_journal as journal_module
from custom_components.bticino_c300x.visitor_journal import VisitorJournal, visit_id
from custom_components.bticino_c300x.visitor_journal_media import (
    describe_clip,
    read_clip,
)


def event(kind="doorbell_pressed", sequence=1, *, entry="one", instance="boot", **payload):
    return SimpleNamespace(data={
        "entry_id": entry, "event_key": kind, "source_event_id": f"native-{instance}-{sequence}",
        "data": payload,
    })


def fixture(tmp_path, monkeypatch):
    manager = manager_for(tmp_path, monkeypatch)
    manager.hass.bus = SimpleNamespace(async_fire=Mock(), async_listen=Mock(return_value=Mock()))
    journal = manager.journal = VisitorJournal(manager.hass, manager.entry)
    journal.store = SimpleNamespace(async_load=AsyncMock(return_value=None), async_save=AsyncMock(), async_delay_save=Mock())
    return manager, journal


def test_invalidation_notifies_without_storage_and_changes_still_persist(tmp_path, monkeypatch):
    _, journal = fixture(tmp_path, monkeypatch)
    before = json.dumps(journal._payload())
    journal.invalidate()
    assert json.dumps(journal._payload()) == before
    journal.store.async_delay_save.assert_not_called()
    journal.hass.bus.async_fire.assert_called_once_with(
        journal_module.EVENT_JOURNAL_CHANGED, {"entry_id": "one"},
    )
    journal.hass.bus.async_fire.reset_mock()
    journal.event(event())
    journal.store.async_delay_save.assert_called_once_with(journal._saved_payload, 1)
    journal.hass.bus.async_fire.assert_called_once_with(
        journal_module.EVENT_JOURNAL_CHANGED, {"entry_id": "one"},
    )
    assert len(journal._payload()["visits"]) == 1
    journal.store.async_delay_save.reset_mock()
    journal.hass.bus.async_fire.reset_mock()
    journal.close()
    journal.invalidate()
    journal.changed()
    journal.store.async_delay_save.assert_not_called()
    journal.hass.bus.async_fire.assert_not_called()


@pytest.mark.parametrize("operation", ["notify", "save", "switch", "refresh"])
def test_snapshot_only_changes_invalidate_without_persisting_journal(tmp_path, monkeypatch, operation):
    async def run():
        manager, journal = fixture(tmp_path, monkeypatch)
        before = json.dumps(journal._payload())
        if operation == "notify":
            manager.notify()
        elif operation == "save":
            await manager.save(jpeg(), "on-demand")
        elif operation == "switch":
            await manager.async_set_enabled(False)
        else:
            manager.store.save(jpeg(), "existing", 14)
            await manager.refresh()
        assert json.dumps(journal._payload()) == before
        journal.store.async_delay_save.assert_not_called()
        journal.hass.bus.async_fire.assert_called_once_with(
            journal_module.EVENT_JOURNAL_CHANGED, {"entry_id": "one"},
        )
        manager.close()
        journal.hass.bus.async_fire.reset_mock()
        manager.notify()
        journal.hass.bus.async_fire.assert_not_called()

    asyncio.run(run())


def test_ring_only_entry_isolation_deduplication_and_no_backfill(tmp_path, monkeypatch):
    _, journal = fixture(tmp_path, monkeypatch)
    for kind in ("doorbell_view_requested", "home_call_started", "call_started"):
        journal.event(event(kind))
    journal.event(event(entry="two"))
    assert journal.items() == []
    ring = event()
    journal.event(ring)
    journal.event(ring)
    assert len(journal.items()) == 1
    assert journal.items()[0]["outcome"] == "unknown"
    assert visit_id(ring.data) == journal.active
    assert journal.hass.bus.async_fire.call_args.args[1] == {"entry_id": "one"}
    journal.event(event(sequence=2))
    journal.event(ring)
    assert journal.active == visit_id(event(sequence=2).data)
    unidentified = event(sequence=3)
    unidentified.data.pop("source_event_id")
    journal.event(unidentified)
    assert journal.active is None
    assert len(journal.items()) == 2


@pytest.mark.parametrize("kind,video", [
    ("call_started", {"bridge": {"media_owner": "ring", "ring_answered": True}}),
    ("doorbell_view_requested", {"bridge": {"media_owner": "ring", "ring_answer_requested": True}}),
    ("doorbell_view_requested", {"bridge": {"media_owner": "home_call", "ring_answered": True}}),
    ("doorbell_view_requested", {"bridge": {"media_owner": "ring", "ring_answered": "true"}}),
    ("doorbell_view_requested", {"external_media_active": True, "bridge": {"media_owner": "ring", "ring_answered": True}}),
    ("doorbell_media_closed", {}),
])
def test_ambiguous_or_closed_calls_never_fabricate_outcome(tmp_path, monkeypatch, kind, video):
    _, journal = fixture(tmp_path, monkeypatch)
    journal.event(event())
    journal.event(event(kind, 2, video=video))
    assert journal.items()[0]["outcome"] == "unknown"


@pytest.mark.parametrize("payload", [
    None, [], {}, {"video": None}, {"video": 1}, {"video": []},
    {"video": {"bridge": None}}, {"video": {"bridge": "ring"}},
])
def test_malformed_answer_evidence_is_ignored(tmp_path, monkeypatch, payload):
    _, journal = fixture(tmp_path, monkeypatch)
    journal.event(event())
    answer = event("doorbell_view_requested", 2)
    answer.data["data"] = payload
    journal.event(answer)
    assert journal.items()[0]["outcome"] == "unknown"


@pytest.mark.parametrize("at", [
    None, True, False, "123", [], {}, 0, -1,
    float("nan"), float("inf"), float("-inf"), 1800000000 + 86401,
])
def test_invalid_restored_timestamp_is_rejected(monkeypatch, at):
    monkeypatch.setattr(journal_module.time, "time", lambda: 1800000000)
    source = event().data["source_event_id"]
    raw = {"id": visit_id({"source_event_id": source}), "source": source, "at": at}
    assert journal_module._validated_record(raw) is None


@pytest.mark.parametrize("number_type", [int, float])
def test_numeric_subclass_timestamp_is_still_rejected(number_type):
    subclass = type("TimestampSubclass", (number_type,), {})
    source = event().data["source_event_id"]
    raw = {"id": visit_id({"source_event_id": source}), "source": source, "at": subclass(1)}
    assert journal_module._validated_record(raw) is None


@pytest.mark.parametrize("at", [1, 1.25, 1800000000, 1800000000.0, 1800000000 + 3600])
def test_valid_restored_timestamp_is_not_coerced(monkeypatch, at):
    monkeypatch.setattr(journal_module.time, "time", lambda: 1800000000)
    source = event().data["source_event_id"]
    raw = {"id": visit_id({"source_event_id": source}), "source": source, "at": at}
    record = journal_module._validated_record(raw)
    assert record is not None
    assert record["at"] is at
    assert record["source"] == source
    assert record["id"] == raw["id"]


def test_answer_requires_ordered_same_instance_ring_evidence(tmp_path, monkeypatch):
    _, journal = fixture(tmp_path, monkeypatch)
    journal.event(event(sequence=10))
    video = {"bridge": {"media_owner": "ring", "ring_answered": True}}
    journal.event(event("doorbell_view_requested", 9, video=video))
    journal.event(event("doorbell_view_requested", 11, instance="old", video=video))
    assert journal.items()[0]["outcome"] == "unknown"
    journal.event(event("doorbell_media_closed", 8))
    assert journal.active is not None
    journal.event(event("doorbell_view_requested", 11, video=video))
    assert journal.items()[0]["outcome"] == "answered"
    journal.event(event("doorbell_media_closed", 12))
    assert journal.items()[0]["outcome"] == "answered"
    assert journal.active is None


def test_lost_close_event_expires_correlation_without_claiming_missed(tmp_path, monkeypatch):
    _, journal = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(journal_module.time, "monotonic", lambda: 0)
    journal.event(event())
    monkeypatch.setattr(journal_module.time, "monotonic", lambda: journal_module.MAX_ACTIVE_SECONDS)
    journal.event(event("doorbell_view_requested", 2, video={"bridge": {"media_owner": "ring", "ring_answered": True}}))
    assert journal.active is None
    assert journal.items()[0]["outcome"] == "unknown"


def test_metadata_retention_quota_and_invalid_restore(tmp_path, monkeypatch):
    async def run():
        manager, journal = fixture(tmp_path, monkeypatch)
        now = 1800000000
        monkeypatch.setattr(journal_module.time, "time", lambda: now)
        monkeypatch.setattr(journal_module, "MAX_VISITS", 3)
        for seq in range(10):
            journal.event(event(sequence=seq))
            now += 1
        assert len(journal.items()) == 3
        assert len(json.dumps(journal._payload())) < journal_module.MAX_JOURNAL_BYTES
        journal.store.async_load.return_value = {"visits": [None, {"id": "../oops"}, *journal.items()]}
        journal.records = {}
        await journal.load()
        assert len(journal.items()) == 3
        manager.entry.options["snapshot_retention_days"] = 1
        now += 86400
        journal.prune()
        assert journal.items() == []
        assert journal.active is None
        journal.close()
        journal.event(event(sequence=99))
        assert journal.items() == []
        await journal.shutdown()
        journal.store.async_save.assert_awaited_once_with({"visits": []})

    asyncio.run(run())


def test_real_ha_storage_restores_without_restoring_active_call(tmp_path):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        entry = SimpleNamespace(entry_id="one", options={}, data={})
        first = VisitorJournal(hass, entry)
        await first.load()
        first.start()
        first.event(event())
        await first.shutdown()
        second = VisitorJournal(hass, entry)
        await second.load()
        assert len(second.items()) == 1
        assert second.active is None
        second.event(event())
        assert len(second.items()) == 1
        other = VisitorJournal(hass, SimpleNamespace(entry_id="two", options={}, data={}))
        await other.load()
        assert other.items() == []
        await second.shutdown()
        await other.shutdown()
        await hass.async_block_till_done()

    asyncio.run(run())


def test_existing_clip_identity_and_media_retention_are_independent(tmp_path, monkeypatch):
    async def run():
        manager, journal = fixture(tmp_path, monkeypatch)
        journal.event(event())
        key = journal.active
        path = tmp_path / "media" / "c300x" / ("doorbell_20261116_120000_" + "a" * 32 + ".mp4")
        path.parent.mkdir(parents=True)
        path.write_bytes(b"existing clip")
        metadata = {"output_path": str(path), "entry_id": "one", "capture_mode": "ring"}
        await journal.attach_clip(key, {**metadata, "entry_id": "two"})
        assert journal.items()[0]["clip"] is None
        await journal.attach_clip(key, {**metadata, "capture_mode": "on_demand"})
        assert journal.items()[0]["clip"] is None
        await journal.attach_clip(key, metadata)
        clip = journal.items()[0]["clip"]
        assert read_clip(manager.hass, clip) == b"existing clip"
        assert describe_clip(manager.hass, {"output_path": str(tmp_path / path.name)}) is None
        path.write_bytes(b"different clip")
        assert read_clip(manager.hass, clip) is None
        journal.records.clear()
        assert path.exists()  # The journal never owns/deletes the existing recordings.
        journal.event(event(sequence=2))
        await journal.attach_clip(key, metadata)
        assert journal.items()[0]["clip"] is None
        journal.close()
        await journal.attach_snapshot(journal.active, "c300x-1800000000000-" + "a" * 32 + ".jpg", b"")

    asyncio.run(run())


def test_capture_symlinks_and_public_media_root_are_rejected(tmp_path, monkeypatch):
    manager, _ = fixture(tmp_path, monkeypatch)
    name = "doorbell_20261116_120000_" + "b" * 32 + ".mp4"
    root = tmp_path / "media" / "c300x"
    root.mkdir(parents=True)
    outside = tmp_path / "secret"
    outside.write_bytes(b"secret")
    (root / name).symlink_to(outside)
    with pytest.raises(ValueError):
        describe_clip(manager.hass, {"output_path": str(root / name)})
    (root / name).unlink()
    manager.hass.config.media_dirs["local"] = str(tmp_path / "www")
    with pytest.raises(ValueError):
        describe_clip(manager.hass, {"output_path": str(tmp_path / "www" / "c300x" / name)})


def test_snapshot_completion_links_original_ring_without_extra_acquisition(tmp_path, monkeypatch):
    from test_stream_snapshot_capture import drain, setup

    async def run():
        manager = setup(tmp_path, monkeypatch)
        manager.hass.bus.async_fire = Mock()
        journal = manager.journal = VisitorJournal(manager.hass, manager.entry)
        journal.store = SimpleNamespace(async_delay_save=Mock())
        ring = event()
        journal.event(ring)
        manager.capture._event(ring)
        await drain(manager)
        assert journal.items()[0]["snapshot"]["name"] == manager.latest.name
        manager.capture._event(ring)
        await drain(manager)
        manager.entry.runtime_data.api.async_doorbell_snapshot.assert_awaited_once()
        journal.event(event(sequence=2))
        # An old completion can only attach to its original retained visit.
        await journal.attach_snapshot(visit_id(ring.data), manager.latest.name, manager.image)
        assert journal.records[journal.active]["snapshot"] is None
        manager.close()

    asyncio.run(run())


def test_removal_deletes_metadata_but_not_existing_artifacts(tmp_path):
    async def run():
        hass = HomeAssistant(str(tmp_path))
        journal = VisitorJournal(hass, SimpleNamespace(entry_id="one", data={}, options={}))
        hass.data.setdefault("bticino_c300x", {})["stream_snapshots"] = {"one": SimpleNamespace(journal=journal)}
        await journal.load()
        journal.event(event())
        await journal.shutdown()
        path = tmp_path / ".storage" / "bticino_c300x.visitor_journal.one"
        assert path.exists()
        await journal_module.async_remove_journal(hass, "one")
        await journal.shutdown()
        assert not path.exists()
        await hass.async_block_till_done()

    asyncio.run(run())


def test_clock_set_back_keeps_visits_and_captures(tmp_path, monkeypatch):
    """A host that starts with its clock behind must not erase recent history."""

    async def run():
        from custom_components.bticino_c300x import capture_history

        manager, journal = fixture(tmp_path, monkeypatch)
        now = 1800000000
        monkeypatch.setattr(journal_module.time, "time", lambda: now)
        monkeypatch.setattr(capture_history.time, "time", lambda: now)
        journal.event(event())
        clip = {"name": "doorbell_20261116_120000_" + "c" * 32 + ".mp4", "size": 1, "mtime_ns": 1, "ctime_ns": 1}
        monkeypatch.setattr(capture_history, "valid_clip", lambda value: value)
        journal.captures.add(clip, now)
        saved = journal._payload()
        now -= 3600
        journal.prune()
        assert len(journal.items()) == 1
        assert len(journal.captures.records) == 1
        journal.records = {}
        journal.captures.records = {}
        journal.store.async_load.return_value = saved
        await journal.load()
        assert len(journal.records) == 1
        assert len(journal.captures.records) == 1

    asyncio.run(run())


def test_clip_links_to_its_ring_after_the_call_has_closed(tmp_path, monkeypatch):
    async def run():
        manager, journal = fixture(tmp_path, monkeypatch)
        journal.event(event())
        key = journal.active
        path = tmp_path / "media" / "c300x" / ("doorbell_20261116_120000_" + "d" * 32 + ".mp4")
        path.parent.mkdir(parents=True)
        path.write_bytes(b"ring clip")
        metadata = {"output_path": str(path), "entry_id": "one", "capture_mode": "ring"}
        journal.event(event("call_ended", 2))
        assert journal.active is None
        await journal.attach_clip(key, metadata)
        clip = journal.items()[0]["clip"]
        assert read_clip(manager.hass, clip) == b"ring clip"
        other = path.with_name("doorbell_20261116_120100_" + "e" * 32 + ".mp4")
        other.write_bytes(b"later clip")
        await journal.attach_clip(key, {**metadata, "output_path": str(other)})
        assert journal.items()[0]["clip"] == clip

    asyncio.run(run())


@pytest.mark.parametrize("ring_after", [None, 0, 0.02])
def test_ring_adopts_the_image_already_requested_for_an_open_stream(tmp_path, monkeypatch, ring_after):
    from test_stream_snapshot_capture import drain, setup

    async def run():
        manager = setup(tmp_path, monkeypatch, delay=0.05)
        manager.hass.bus.async_fire = Mock()
        journal = manager.journal = VisitorJournal(manager.hass, manager.entry)
        journal.store = SimpleNamespace(async_delay_save=Mock())
        manager.capture.capture_requested("stream-1")
        if ring_after is not None:
            # The capture task has started and waits for the settling delay.
            await asyncio.sleep(ring_after)
        ring = event()
        journal.event(ring)
        manager.capture._event(ring)
        await drain(manager)
        manager.entry.runtime_data.api.async_doorbell_snapshot.assert_awaited_once()
        assert journal.items()[0]["snapshot"]["name"] == manager.latest.name
        manager.close()

    asyncio.run(run())


def test_reading_an_unchanged_journal_does_not_serialize_it_again(tmp_path, monkeypatch):
    manager, journal = fixture(tmp_path, monkeypatch)
    journal.event(event())
    journal.items()
    dumps = Mock(side_effect=json.dumps)
    monkeypatch.setattr(journal_module.json, "dumps", dumps)
    for _ in range(5):
        assert len(journal.items()) == 1
    dumps.assert_not_called()
    journal.event(event(sequence=2))
    assert len(journal.items()) == 2
    assert dumps.call_count
    monkeypatch.setattr(journal_module, "MAX_JOURNAL_BYTES", 1)
    journal.changed()
    assert journal.items() == []


@pytest.mark.parametrize("change", ["ring", "clip", "snapshot", "outcome"])
def test_a_change_is_trimmed_to_the_size_limit_before_it_is_saved(tmp_path, monkeypatch, change):
    async def run():
        manager, journal = fixture(tmp_path, monkeypatch)
        for number in range(1, 6):
            journal.event(event(sequence=number))
        journal.items()
        limit = len(json.dumps(journal._payload())) + 20
        monkeypatch.setattr(journal_module, "MAX_JOURNAL_BYTES", limit)
        journal.items()
        if change == "ring":
            journal.event(event(sequence=6))
        elif change == "snapshot":
            journal.records[journal.active]["snapshot"] = {"name": "x" * 200}
            journal.changed()
        elif change == "outcome":
            journal.records[journal.active]["outcome"] = "answered-" + "y" * 40
            journal.changed()
        else:
            key = journal.active
            path = tmp_path / "media" / "c300x" / ("doorbell_20261116_120000_" + "f" * 32 + ".mp4")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"clip")
            await journal.attach_clip(key, {"output_path": str(path), "entry_id": "one", "capture_mode": "ring"})
        # What the delayed save writes, without a read in between.
        save = journal.store.async_delay_save.call_args[0][0]
        assert len(json.dumps(save())) <= limit

    asyncio.run(run())


def test_a_clip_is_not_linked_to_an_old_visit_while_a_newer_ring_is_active(tmp_path, monkeypatch):
    async def run():
        manager, journal = fixture(tmp_path, monkeypatch)
        journal.event(event())
        first = journal.active
        journal.event(event("call_ended", 2))
        journal.event(event(sequence=3))
        assert journal.active not in (None, first)
        path = tmp_path / "media" / "c300x" / ("doorbell_20261116_120000_" + "9" * 32 + ".mp4")
        path.parent.mkdir(parents=True)
        path.write_bytes(b"clip")
        await journal.attach_clip(first, {"output_path": str(path), "entry_id": "one", "capture_mode": "ring"})
        assert journal.records[first]["clip"] is None

    asyncio.run(run())
