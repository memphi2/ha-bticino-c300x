from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x import runtime_manager
from custom_components.bticino_c300x.api_errors import C300XAgentApiError
from custom_components.bticino_c300x.const import (
    CONF_AUDIO_FINE_GAIN_DB,
    CONF_DOOR_AUDIO_LEVEL_DB,
    RETIRED_AUDIO_OPTION_KEYS,
)
from custom_components.bticino_c300x.doorstation_audio import (
    agent_audio_level,
    async_ensure_doorstation_audio_level,
    async_sync_doorstation_audio_level,
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


def test_a_failing_write_warns_once_until_one_succeeds(caplog) -> None:
    entry = _entry({CONF_DOOR_AUDIO_LEVEL_DB: 9}, status=_status(0, 0), fail=True)

    def warnings() -> int:
        return sum(record.levelno == logging.WARNING for record in caplog.records)

    with caplog.at_level(logging.DEBUG):
        for _ in range(3):
            asyncio.run(async_ensure_doorstation_audio_level(entry))
        assert warnings() == 1
        entry.runtime_data.api.fail = False
        asyncio.run(async_ensure_doorstation_audio_level(entry))
        entry.runtime_data.api.fail = True
        asyncio.run(async_ensure_doorstation_audio_level(entry))

    assert warnings() == 2
    assert len(entry.runtime_data.api.level_calls) == 5


def test_the_sync_after_setup_sends_a_lowered_level() -> None:
    entry = _entry({CONF_DOOR_AUDIO_LEVEL_DB: 0}, status=_status(12, 0))

    asyncio.run(async_sync_doorstation_audio_level(entry))

    assert entry.runtime_data.api.level_calls == [(0, 0)]


@pytest.mark.parametrize("error", [C300XAgentApiError("offline"), RuntimeError("closed")])
def test_the_sync_after_setup_never_raises(error: Exception) -> None:
    entry = _entry(status=_status(12, 0))

    async def fail(*_args: object) -> None:
        raise error

    entry.runtime_data.api.async_set_doorstation_audio_level = fail
    asyncio.run(async_sync_doorstation_audio_level(entry))

    async def cancelled(*_args: object) -> None:
        raise asyncio.CancelledError

    entry.runtime_data.api.async_set_doorstation_audio_level = cancelled
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(async_sync_doorstation_audio_level(entry))


def test_the_startup_sync_sends_the_levels_before_the_later_steps(monkeypatch) -> None:
    """Setup and every options save (which reloads the entry) reach the agent."""

    entry = _entry({CONF_DOOR_AUDIO_LEVEL_DB: 0}, status=_status(9, 0))
    entry.runtime_data.resources = SimpleNamespace(closed=False)
    manager = runtime_manager.C300XRuntimeManager(SimpleNamespace(), entry)
    manager.api = entry.runtime_data.api

    async def no_display(*_args: object, **_kwargs: object) -> None:
        return None

    async def later_step_fails(*_args: object) -> None:
        raise RuntimeError("device user")

    monkeypatch.setattr(manager, "_async_refresh_display_registration", no_display)
    monkeypatch.setattr(runtime_manager, "_async_sync_device_user", later_step_fails)

    with pytest.raises(RuntimeError, match="device user"):
        asyncio.run(manager.async_sync_device_state())

    assert entry.runtime_data.api.level_calls == [(0, 0)]


def test_saving_only_a_new_door_level_reloads_the_entry(monkeypatch) -> None:
    """The reload is what runs the startup sync after an options save."""

    entry = _entry({CONF_DOOR_AUDIO_LEVEL_DB: 9})
    reloads: list[object] = []

    async def reload(_hass: object, updated: object) -> None:
        reloads.append(updated)

    async def no_reapply(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(runtime_manager, "_async_update_listener", reload)
    monkeypatch.setattr(runtime_manager, "_async_reapply_display_patch_for_home_page", no_reapply)
    listener = runtime_manager._entry_update_listener(entry)
    entry.options = {CONF_DOOR_AUDIO_LEVEL_DB: 0}
    asyncio.run(listener(None, entry))

    assert reloads == [entry]
