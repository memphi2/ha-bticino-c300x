# ruff: noqa: E402

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.usefixtures("entity_ha_boundary")

from homeassistant.exceptions import HomeAssistantError  # noqa: E402

from custom_components.bticino_c300x.api import C300XAgentApiError  # noqa: E402
from custom_components.bticino_c300x.number import (  # noqa: E402
    C300XRingerVolumeNumber,
    async_setup_entry,
)


class _FakeApi:
    def __init__(
        self,
        *,
        volume: int | None = 3,
        fail_status: bool = False,
        fail_set: bool = False,
        set_response: dict[str, Any] | None = None,
    ) -> None:
        self.volume = volume
        self.fail_status = fail_status
        self.fail_set = fail_set
        self.set_response = set_response
        self.ringer_reads = 0
        self.volume_sets: list[int] = []

    async def async_ringer_status(self) -> dict[str, Any]:
        self.ringer_reads += 1
        if self.fail_status:
            raise C300XAgentApiError("offline")
        return {"muted": False, "volume": self.volume}

    async def async_set_ringer_volume(self, volume: int) -> dict[str, Any]:
        self.volume_sets.append(volume)
        if self.fail_set:
            raise C300XAgentApiError("not applied")
        if self.set_response is not None:
            return self.set_response
        self.volume = volume
        return {"volume": volume}


@dataclass
class _FakeConnectionState:
    available: bool = True


@dataclass
class _FakeRuntimeData:
    capabilities: dict[str, Any] = field(
        default_factory=lambda: {"ringer": {"supported": True, "volume": True}}
    )
    api: _FakeApi = field(default_factory=_FakeApi)
    connection_state: _FakeConnectionState = field(default_factory=_FakeConnectionState)


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    runtime_data: _FakeRuntimeData = field(default_factory=_FakeRuntimeData)


def test_number_setup_adds_supported_entity_after_initial_refresh() -> None:
    entry = _FakeEntry()
    added: list[list[Any]] = []

    asyncio.run(async_setup_entry("hass", entry, added.append))  # type: ignore[arg-type]

    assert len(added) == 1
    entity = added[0][0]
    assert isinstance(entity, C300XRingerVolumeNumber)
    assert entry.runtime_data.api.ringer_reads == 1
    assert entity.native_value == 3


def test_number_setup_skips_legacy_boolean_ringer_capability() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(capabilities={"ringer": True})
    )
    added: list[list[Any]] = []

    asyncio.run(async_setup_entry("hass", entry, added.append))  # type: ignore[arg-type]

    assert added == []
    assert entry.runtime_data.api.ringer_reads == 0


@pytest.mark.parametrize("value", [0, 4, 10])
def test_ringer_volume_number_sets_volume(value: int) -> None:
    entry = _FakeEntry()
    entity = C300XRingerVolumeNumber(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_set_native_value(value))

    assert entry.runtime_data.api.volume_sets == [value]
    assert entity.native_value == value
    assert entity.available is True


def test_ringer_volume_number_does_not_keep_unconfirmed_set_value() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(api=_FakeApi(set_response={"raw": "*#*1##"}))
    )
    entity = C300XRingerVolumeNumber(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_set_native_value(8))

    assert entry.runtime_data.api.volume_sets == [8]
    assert entity.native_value is None
    assert entity.available is False


def test_ringer_volume_number_refreshes_actual_value_after_set_failure() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(api=_FakeApi(volume=3, fail_set=True))
    )
    entity = C300XRingerVolumeNumber(entry)  # type: ignore[arg-type]

    with pytest.raises(HomeAssistantError):
        asyncio.run(entity.async_set_native_value(8))

    assert entry.runtime_data.api.volume_sets == [8]
    assert entry.runtime_data.api.ringer_reads == 1
    assert entity.native_value == 3
    assert entity.available is True
    assert entity.wrote_state is True


@pytest.mark.parametrize("value", [-1, 11, 10.5, "invalid"])
def test_ringer_volume_number_rejects_invalid_volume(value: Any) -> None:
    entry = _FakeEntry()
    entity = C300XRingerVolumeNumber(entry)  # type: ignore[arg-type]

    with pytest.raises(HomeAssistantError):
        asyncio.run(entity.async_set_native_value(value))  # type: ignore[arg-type]

    assert entry.runtime_data.api.volume_sets == []


def test_ringer_volume_event_updates_number() -> None:
    entity = C300XRingerVolumeNumber(_FakeEntry())  # type: ignore[arg-type]

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_type": "ringer_volume_changed",
                "volume": 7,
            }
        )
    )

    assert entity.native_value == 7
    assert entity.available is True


def test_ringer_volume_number_marks_unavailable_when_refresh_fails() -> None:
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=_FakeApi(fail_status=True)))
    entity = C300XRingerVolumeNumber(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False
    assert entity.native_value is None
