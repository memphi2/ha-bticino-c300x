from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytestmark = pytest.mark.usefixtures("entity_ha_boundary")

from homeassistant.exceptions import HomeAssistantError  # noqa: E402

from custom_components.bticino_c300x.api import C300XAgentApiError  # noqa: E402
from custom_components.bticino_c300x.select import async_setup_entry  # noqa: E402
from custom_components.bticino_c300x.select_camera_resolution import (  # noqa: E402
    C300XCameraResolutionSelect,
)
from tests.test_select import _FakeEntry, _FakeRuntimeData  # noqa: E402


class _ResolutionApi:
    def __init__(self, *, high: bool = True, fail: bool = False) -> None:
        self.high = high
        self.fail = fail
        self.calls: list[bool | None] = []

    async def async_camera_resolution(self, *, high_resolution: bool | None = None) -> dict[str, Any]:
        self.calls.append(high_resolution)
        if self.fail:
            raise C300XAgentApiError("offline")
        if high_resolution is not None:
            self.high = high_resolution
        return {"ok": True, "high_resolution": self.high}


def _entry(maintenance: dict[str, Any], api: _ResolutionApi) -> _FakeEntry:
    return _FakeEntry(runtime_data=_FakeRuntimeData(capabilities={"maintenance": maintenance}, api=api))


def _added(entry: _FakeEntry) -> list[Any]:
    added: list[list[Any]] = []
    asyncio.run(async_setup_entry("hass", entry, added.append))  # type: ignore[arg-type]
    return [entity for batch in added for entity in batch if isinstance(entity, C300XCameraResolutionSelect)]


def test_the_select_exists_only_where_the_agent_offers_the_resolution() -> None:
    api = _ResolutionApi(high=True)
    entities = _added(_entry({"supported": True, "camera_resolution": True}, api))
    assert len(entities) == 1
    assert entities[0].current_option == "high"
    # 3.0.x and older agents: fixed to low or not offered, so no entity.
    assert _added(_entry({"supported": True, "camera_resolution": False}, _ResolutionApi())) == []
    assert _added(_entry({"supported": True}, _ResolutionApi())) == []


def test_choosing_an_option_saves_it_on_the_device(monkeypatch) -> None:
    api = _ResolutionApi(high=True)
    entity = C300XCameraResolutionSelect(_entry({"supported": True, "camera_resolution": True}, api))
    monkeypatch.setattr(entity, "async_write_ha_state", lambda: None)
    asyncio.run(entity.async_select_option("low"))
    assert api.calls == [False]
    assert entity.current_option == "low"
    asyncio.run(entity.async_select_option("high"))
    assert api.calls == [False, True]
    assert entity.current_option == "high"


def test_a_failed_read_or_save_is_reported() -> None:
    api = _ResolutionApi(fail=True)
    entity = C300XCameraResolutionSelect(_entry({"supported": True, "camera_resolution": True}, api))
    asyncio.run(entity.async_update())
    assert entity.available is False
    with pytest.raises(HomeAssistantError):
        asyncio.run(entity.async_select_option("low"))
