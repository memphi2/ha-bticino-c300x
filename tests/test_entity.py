from __future__ import annotations

import asyncio
from types import SimpleNamespace

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
    entity.hass = SimpleNamespace(  # type: ignore[assignment]
        async_create_background_task=lambda coro, name: tasks.append(
            asyncio.ensure_future(coro)
        )
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
