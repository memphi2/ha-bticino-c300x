from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.bticino_c300x.const import CONF_DOORSTATION_AUDIO_GAIN_DB
from custom_components.bticino_c300x.doorstation_audio import (
    async_ensure_doorstation_audio_gain,
)


class _FakeApi:
    def __init__(self, status: dict | None = None) -> None:
        self.status = status
        self.status_calls = 0
        self.gain_calls: list[float] = []

    async def async_doorbell_video_status(self) -> dict:
        self.status_calls += 1
        return self.status or {"bridge": {}}

    async def async_set_doorstation_audio_gain_db(self, gain_db: float) -> dict:
        self.gain_calls.append(gain_db)
        return {"ok": True, "doorstation_audio_gain_db": gain_db}


def _entry(*, gain_db: float | None = None, status: dict | None = None) -> SimpleNamespace:
    options = {}
    if gain_db is not None:
        options[CONF_DOORSTATION_AUDIO_GAIN_DB] = gain_db
    return SimpleNamespace(
        data={},
        options=options,
        runtime_data=SimpleNamespace(api=_FakeApi(status)),
    )


def test_doorstation_audio_gain_default_zero_does_not_send_without_agent_status() -> None:
    entry = _entry()

    asyncio.run(async_ensure_doorstation_audio_gain(entry, status={"bridge": {}}))

    assert entry.runtime_data.api.status_calls == 0
    assert entry.runtime_data.api.gain_calls == []


def test_doorstation_audio_gain_sends_configured_nonzero_when_agent_status_unknown() -> None:
    entry = _entry(gain_db=6.0)

    asyncio.run(async_ensure_doorstation_audio_gain(entry, status={"bridge": {}}))

    assert entry.runtime_data.api.gain_calls == [6.0]


def test_doorstation_audio_gain_skips_matching_agent_value() -> None:
    entry = _entry(
        gain_db=6.0,
        status={"bridge": {CONF_DOORSTATION_AUDIO_GAIN_DB: 6.0}},
    )

    asyncio.run(async_ensure_doorstation_audio_gain(entry))

    assert entry.runtime_data.api.status_calls == 1
    assert entry.runtime_data.api.gain_calls == []


def test_doorstation_audio_gain_resets_agent_to_zero_when_reported_nonzero() -> None:
    entry = _entry(status={"bridge": {CONF_DOORSTATION_AUDIO_GAIN_DB: 6.0}})

    asyncio.run(async_ensure_doorstation_audio_gain(entry))

    assert entry.runtime_data.api.status_calls == 1
    assert entry.runtime_data.api.gain_calls == [0.0]
