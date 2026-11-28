from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.bticino_c300x.entity import C300XEntity


class _ReadingEntity(C300XEntity):
    """An entity that does not poll and marks itself unavailable on a failed read."""

    _attr_should_poll = False

    def __init__(self, entry: SimpleNamespace) -> None:
        super().__init__(entry, "reading")
        self._attr_available = False
        self.reads = 0
        self.writes = 0
        self.read_ok = True

    async def async_update(self) -> None:
        self.reads += 1
        self._attr_available = self.read_ok

    def async_write_ha_state(self) -> None:
        self.writes += 1


class _PlainEntity(C300XEntity):
    def __init__(self, entry: SimpleNamespace) -> None:
        super().__init__(entry, "plain")
        self._attr_available = False
        self.writes = 0

    def async_write_ha_state(self) -> None:
        self.writes += 1


def _entry(available: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        runtime_data=SimpleNamespace(
            connection_state=SimpleNamespace(available=available), agent_info={}
        ),
    )


def _run(entity: C300XEntity, entry_id: str = "entry-1") -> list[asyncio.Task]:
    tasks: list[asyncio.Task] = []

    def create_task(coro, name):
        task = asyncio.ensure_future(coro)
        tasks.append(task)
        return task

    entity.hass = SimpleNamespace(  # type: ignore[assignment]
        async_create_background_task=create_task
    )

    async def go() -> None:
        entity._handle_c300x_connection_state_changed(entry_id)
        await asyncio.gather(*tasks)

    asyncio.run(go())
    return tasks


def test_an_entity_marked_unavailable_by_a_failed_read_reads_again_when_the_agent_answers() -> None:
    entity = _ReadingEntity(_entry())

    tasks = _run(entity)

    assert len(tasks) == 1 and entity.reads == 1
    assert entity.available is True
    assert entity.writes == 1


def test_it_stays_unavailable_when_the_second_read_fails_too() -> None:
    entity = _ReadingEntity(_entry())
    entity.read_ok = False

    _run(entity)

    assert entity.reads == 1 and entity.available is False


def test_no_read_is_started_for_other_entries_available_entities_or_a_lost_agent() -> None:
    other = _ReadingEntity(_entry())
    assert _run(other, "entry-2") == [] and other.reads == 0

    healthy = _ReadingEntity(_entry())
    healthy._attr_available = True
    assert _run(healthy) == [] and healthy.reads == 0

    away = _ReadingEntity(_entry(available=False))
    assert _run(away) == [] and away.reads == 0

    # An entity without a read of its own has nothing to refresh.
    plain = _PlainEntity(_entry())
    assert _run(plain) == []


@pytest.mark.parametrize("kind", ["mute", "volume"])
@pytest.mark.parametrize("removed", [False, True])
def test_ringer_refreshes_once_after_connection_loss(monkeypatch, kind, removed) -> None:
    from custom_components.bticino_c300x import entity as entity_module
    from custom_components.bticino_c300x.number import C300XRingerVolumeNumber
    from custom_components.bticino_c300x.switch import C300XRingerMuteSwitch

    async def go() -> None:
        entry = _entry()
        api = SimpleNamespace(
            async_ringer_status=AsyncMock(return_value={"muted": False, "volume": 5})
        )
        entry.runtime_data.api = api
        entity = (
            C300XRingerMuteSwitch(entry) if kind == "mute"
            else C300XRingerVolumeNumber(entry)
        )
        tasks = []
        callbacks = []
        writes = []

        def create_task(coro, name):
            task = asyncio.create_task(coro)
            tasks.append(task)
            return task

        entity.hass = SimpleNamespace(
            async_create_background_task=create_task,
            bus=SimpleNamespace(async_listen=lambda *_: lambda: None),
        )
        monkeypatch.setattr(entity, "async_on_remove", callbacks.append)
        monkeypatch.setattr(entity, "async_write_ha_state", lambda: writes.append(True))
        monkeypatch.setattr(entity_module, "async_dispatcher_connect", lambda *_: lambda: None)
        monkeypatch.setattr(
            sys.modules[type(entity).__module__], "async_dispatcher_connect", lambda *_: lambda: None
        )
        await entity.async_update()
        await entity.async_added_to_hass()
        entity._handle_c300x_connection_state_changed(entry.entry_id)
        assert not tasks

        entry.runtime_data.connection_state.available = False
        entity._handle_c300x_connection_state_changed(entry.entry_id)
        assert not entity.available
        assert entity._attr_available is True

        resume = asyncio.Event()

        async def changed_status():
            await resume.wait()
            return {"muted": True, "volume": 2}

        api.async_ringer_status.side_effect = changed_status
        entry.runtime_data.connection_state.available = True
        entity._handle_c300x_connection_state_changed(entry.entry_id)
        entity._handle_c300x_connection_state_changed(entry.entry_id)
        await asyncio.sleep(0)
        try:
            assert len(tasks) == 1
            assert api.async_ringer_status.await_count == 2
            if removed:
                writes_before_removal = len(writes)
                for cancel in callbacks:
                    cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                assert tasks[0].cancelled()
                assert len(writes) == writes_before_removal
            else:
                resume.set()
                await asyncio.gather(*tasks)
                assert entity.available
                if kind == "mute":
                    assert entity.is_on is True
                else:
                    assert entity.native_value == 2
                entity._handle_c300x_connection_state_changed(entry.entry_id)
                assert len(tasks) == 1
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(go())


def test_connection_recovery_does_not_refresh_other_healthy_entities() -> None:
    entry = _entry()
    entity = _ReadingEntity(entry)
    entity._attr_available = True
    entry.runtime_data.connection_state.available = False
    assert _run(entity) == []
    entry.runtime_data.connection_state.available = True
    assert _run(entity) == []
    assert entity.reads == 0


def test_reconnect_reads_are_coalesced_and_cancelled_on_entity_removal(monkeypatch) -> None:
    from custom_components.bticino_c300x import entity as entity_module

    async def go() -> None:
        entity = _ReadingEntity(_entry())
        started = asyncio.Event()
        callbacks = []
        tasks = []

        async def update():
            entity.reads += 1
            started.set()
            await asyncio.Event().wait()

        def create_task(coro, name):
            task = asyncio.create_task(coro)
            tasks.append(task)
            return task

        entity.hass = SimpleNamespace(async_create_background_task=create_task)
        monkeypatch.setattr(entity, "async_update", update)
        monkeypatch.setattr(entity, "async_on_remove", callbacks.append)
        monkeypatch.setattr(entity_module, "async_dispatcher_connect", lambda *_: lambda: None)
        await entity.async_added_to_hass()
        entity._handle_c300x_connection_state_changed("entry-1")
        await started.wait()
        entity._handle_c300x_connection_state_changed("entry-1")
        await asyncio.sleep(0)
        try:
            assert entity.reads == 1
            for remove in callbacks:
                remove()
            await asyncio.sleep(0)
            assert tasks[0].cancelled()
            assert entity.writes == 0
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(go())


@pytest.mark.parametrize(("stored", "model"), [("C100X", "Classe 100X"), ("C300X", "Classe 300X"), (None, "Classe 300X")])
def test_an_offline_entry_names_the_model_its_agent_named_last(stored, model) -> None:
    from custom_components.bticino_c300x.device_profile import STATION_MODEL
    from custom_components.bticino_c300x.entity import _device_info

    entry = _entry(available=False)
    entry.data = {STATION_MODEL: stored} if stored else {}
    entry.runtime_data.agent_info = {"model": None, "display_kind": None, "offline_error": "down"}
    assert _device_info(entry)["model"] == model
    del entry.runtime_data
    assert _device_info(entry)["model"] == model
