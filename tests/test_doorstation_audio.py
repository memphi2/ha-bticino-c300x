from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.bticino_c300x.api_errors import C300XAgentApiError
from custom_components.bticino_c300x.const import (
    CONF_AUDIO_FINE_GAIN_DB,
    CONF_DOOR_AUDIO_LEVEL_DB,
    RETIRED_AUDIO_OPTION_KEYS,
)
from custom_components.bticino_c300x.doorstation_audio import (
    agent_audio_level,
    async_ensure_doorstation_audio_level,
    audio_fine_gain_db,
    door_audio_level_db,
)


class _FakeApi:
    def __init__(self, status: dict | None = None, *, fail: bool = False) -> None:
        self.status = status
        self.fail = fail
        self.status_calls = 0
        self.level_calls: list[tuple[int, int]] = []

    async def async_doorbell_video_status(self) -> dict:
        self.status_calls += 1
        return self.status or {"bridge": {}}

    async def async_set_doorstation_audio_level(self, door_level_db: int, fine_gain_db: int) -> dict:
        self.level_calls.append((door_level_db, fine_gain_db))
        if self.fail:
            raise C300XAgentApiError("HTTP 400")
        return {"ok": True}


def _entry(options: dict | None = None, *, status: dict | None = None, fail: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        data={},
        options=dict(options or {}),
        runtime_data=SimpleNamespace(api=_FakeApi(status, fail=fail)),
    )


def _status(door: object, fine: object) -> dict:
    return {"bridge": {"audio_level": {"door_level_db": door, "fine_gain_db": fine}}}


def test_defaults_are_door_level_stock_and_no_fine_adjustment() -> None:
    entry = _entry()

    assert door_audio_level_db(entry) == 0
    assert audio_fine_gain_db(entry) == 0


def test_an_entry_with_the_retired_keys_reads_the_defaults() -> None:
    entry = _entry(dict.fromkeys(RETIRED_AUDIO_OPTION_KEYS, 15.5))

    assert (door_audio_level_db(entry), audio_fine_gain_db(entry)) == (0, 0)
    asyncio.run(async_ensure_doorstation_audio_level(entry, status=_status(6, 0)))
    assert entry.runtime_data.api.level_calls == [(0, 0)]


def test_invalid_stored_values_fall_back_to_the_defaults() -> None:
    entry = _entry({CONF_DOOR_AUDIO_LEVEL_DB: 5, CONF_AUDIO_FINE_GAIN_DB: "loud"})

    assert (door_audio_level_db(entry), audio_fine_gain_db(entry)) == (0, 0)


def test_sends_the_configured_levels_when_the_agent_has_others() -> None:
    entry = _entry({CONF_DOOR_AUDIO_LEVEL_DB: 12, CONF_AUDIO_FINE_GAIN_DB: -3}, status=_status(6, 0))

    asyncio.run(async_ensure_doorstation_audio_level(entry))

    assert entry.runtime_data.api.status_calls == 1
    assert entry.runtime_data.api.level_calls == [(12, -3)]


def test_skips_matching_agent_levels() -> None:
    entry = _entry({CONF_DOOR_AUDIO_LEVEL_DB: 0, CONF_AUDIO_FINE_GAIN_DB: 4})

    asyncio.run(async_ensure_doorstation_audio_level(entry, status=_status(0, 4)))

    assert entry.runtime_data.api.status_calls == 0
    assert entry.runtime_data.api.level_calls == []


def test_sends_when_the_agent_reports_no_level() -> None:
    for status in ({"bridge": {}}, {"bridge": {"audio_level": None}}, _status(6.0, 0), None):
        entry = _entry()
        asyncio.run(async_ensure_doorstation_audio_level(entry, status=status))
        assert entry.runtime_data.api.level_calls == [(0, 0)]


def test_a_rejected_write_does_not_block_the_stream() -> None:
    entry = _entry(status=_status(6, 0), fail=True)

    asyncio.run(async_ensure_doorstation_audio_level(entry))

    assert entry.runtime_data.api.level_calls == [(0, 0)]


def test_agent_audio_level_reads_only_the_bridge_object() -> None:
    assert agent_audio_level(None) == {}
    assert agent_audio_level({"bridge": "x"}) == {}
    assert agent_audio_level(_status(3, 1)) == {"door_level_db": 3, "fine_gain_db": 1}
