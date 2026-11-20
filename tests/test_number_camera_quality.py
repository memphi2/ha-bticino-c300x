from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytestmark = pytest.mark.usefixtures("entity_ha_boundary")

from homeassistant.exceptions import HomeAssistantError  # noqa: E402

from custom_components.bticino_c300x.api import C300XAgentApiError  # noqa: E402
from custom_components.bticino_c300x.number import async_setup_entry  # noqa: E402
from custom_components.bticino_c300x.number_camera_quality import (  # noqa: E402
    C300XCameraQualityNumber,
    camera_quality_numbers,
)
from tests.test_select import _FakeEntry, _FakeRuntimeData  # noqa: E402


class _QualityApi:
    def __init__(self, *, fail: bool = False, supported: bool = True) -> None:
        self.values = {"bitrate_kbps": 800, "fps": 15}
        self.restart = False
        self.fail = fail
        self.supported = supported
        self.calls: list[dict[str, int]] = []

    async def async_camera_quality(self, **changes: int) -> dict[str, Any]:
        self.calls.append(changes)
        if self.fail:
            raise C300XAgentApiError("offline")
        if changes:
            self.values.update(changes)
            self.restart = True
        return {"ok": True, "supported": self.supported, **self.values, "bitrate_min": 300,
                "bitrate_max": 2500, "fps_min": 5, "fps_max": 25, "restart_required": self.restart}


def _entry(maintenance: dict[str, Any], api: _QualityApi) -> _FakeEntry:
    return _FakeEntry(runtime_data=_FakeRuntimeData(capabilities={"maintenance": maintenance}, api=api))


def _added(entry: _FakeEntry) -> list[Any]:
    added: list[list[Any]] = []
    asyncio.run(async_setup_entry("hass", entry, added.append))  # type: ignore[arg-type]
    return [entity for batch in added for entity in batch if isinstance(entity, C300XCameraQualityNumber)]


def _numbers(api: _QualityApi) -> tuple[C300XCameraQualityNumber, C300XCameraQualityNumber]:
    bitrate, fps = camera_quality_numbers(_entry({"supported": True, "camera_quality": True}, api))
    assert isinstance(bitrate, C300XCameraQualityNumber) and isinstance(fps, C300XCameraQualityNumber)
    for entity in (bitrate, fps):
        entity.async_write_ha_state = lambda: None  # type: ignore[method-assign]
    return bitrate, fps


def test_the_numbers_exist_only_where_the_agent_offers_them() -> None:
    bitrate, fps = _added(_entry({"supported": True, "camera_quality": True}, _QualityApi()))
    assert (bitrate.native_value, bitrate.native_unit_of_measurement) == (800, "kbit/s")
    assert (fps.native_value, fps.native_unit_of_measurement) == (15, "fps")
    assert bitrate.unique_id != fps.unique_id
    # The limits are the agent's, not the built-in ones.
    assert (bitrate.native_min_value, bitrate.native_max_value) == (300, 2500)
    assert (fps.native_min_value, fps.native_max_value) == (5, 25)
    assert bitrate.extra_state_attributes == {"restart_required": False}
    # Firmware 3.0.x and older agents: no entity.
    assert _added(_entry({"supported": True, "camera_quality": False}, _QualityApi())) == []
    assert _added(_entry({"supported": True}, _QualityApi())) == []


def test_a_new_value_is_saved_alone_and_waits_for_a_restart() -> None:
    api = _QualityApi()
    bitrate, fps = _numbers(api)
    asyncio.run(bitrate.async_set_native_value(3000.0))
    asyncio.run(fps.async_set_native_value(25.0))
    assert api.calls == [{"bitrate_kbps": 3000}, {"fps": 25}]
    assert (bitrate.native_value, fps.native_value) == (3000, 25)
    assert fps.extra_state_attributes == {"restart_required": True}


def test_a_failed_read_or_save_is_reported() -> None:
    bitrate, _fps = _numbers(_QualityApi(fail=True))
    asyncio.run(bitrate.async_update())
    assert bitrate.available is False
    with pytest.raises(HomeAssistantError):
        asyncio.run(bitrate.async_set_native_value(1000.0))


def test_a_device_file_without_the_values_makes_the_numbers_unavailable() -> None:
    bitrate, fps = _numbers(_QualityApi(supported=False))
    asyncio.run(bitrate.async_update())
    asyncio.run(fps.async_update())
    assert bitrate.available is False and bitrate.native_value is None
    assert fps.available is False
