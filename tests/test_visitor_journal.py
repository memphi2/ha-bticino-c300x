"""Journal metadata, authority and local-only media associations."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant
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
        journal.attach_snapshot(journal.active, "c300x-1800000000000-" + "a" * 32 + ".jpg")

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
        assert journal.items()[0]["snapshot"] == manager.latest.name
        manager.capture._event(ring)
        await drain(manager)
        manager.entry.runtime_data.api.async_doorbell_snapshot.assert_awaited_once()
        journal.event(event(sequence=2))
        # An old completion can only attach to its original retained visit.
        journal.attach_snapshot(visit_id(ring.data), manager.latest.name)
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
