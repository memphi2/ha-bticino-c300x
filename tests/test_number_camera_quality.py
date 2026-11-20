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
        self.running = {"running_bitrate_kbps": 800, "running_fps": 15}
        self.fail = fail
        self.supported = supported
        self.calls: list[dict[str, int]] = []

    async def async_camera_quality(self, **changes: int) -> dict[str, Any]:
        self.calls.append(changes)
        if self.fail:
            raise C300XAgentApiError("offline")
        if changes:
            self.values.update(changes)
        restart = (self.values["bitrate_kbps"], self.values["fps"]) != (
            self.running["running_bitrate_kbps"], self.running["running_fps"])
        return {"ok": True, "supported": self.supported, **self.values, **self.running,
                "bitrate_min": 300, "bitrate_max": 2500, "fps_min": 5, "fps_max": 25,
                "restart_required": restart}

    def restarted(self) -> None:
        self.running = {"running_bitrate_kbps": self.values["bitrate_kbps"],
                        "running_fps": self.values["fps"]}


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
    bitrate._batch.delay = 0
    return bitrate, fps


def test_the_numbers_exist_only_where_the_agent_offers_them() -> None:
    bitrate, fps = _added(_entry({"supported": True, "camera_quality": True}, _QualityApi()))
    assert (bitrate.native_value, bitrate.native_unit_of_measurement) == (800, "kbit/s")
    assert (fps.native_value, fps.native_unit_of_measurement) == (15, "fps")
    assert bitrate.unique_id != fps.unique_id
    # The limits are the agent's, not the built-in ones.
    assert (bitrate.native_min_value, bitrate.native_max_value) == (300, 2500)
    assert (fps.native_min_value, fps.native_max_value) == (5, 25)
    assert bitrate.extra_state_attributes == {"restart_required": False, "pending_value": None}
    # Firmware 3.0.x and older agents: no entity.
    assert _added(_entry({"supported": True, "camera_quality": False}, _QualityApi())) == []
    assert _added(_entry({"supported": True}, _QualityApi())) == []


def test_a_new_value_shows_as_pending_until_the_device_runs_it() -> None:
    api = _QualityApi()
    bitrate, fps = _numbers(api)
    asyncio.run(bitrate.async_set_native_value(3000.0))
    assert api.calls == [{"bitrate_kbps": 3000}]
    # The number shows what the device runs; the saved value waits for the restart.
    assert bitrate.native_value == 800
    assert bitrate.extra_state_attributes == {"restart_required": True, "pending_value": 3000}
    api.restarted()
    asyncio.run(bitrate.async_update())
    assert bitrate.native_value == 3000
    assert bitrate.extra_state_attributes == {"restart_required": False, "pending_value": None}


def test_an_agent_that_does_not_know_the_running_values_shows_the_saved_ones() -> None:
    api = _QualityApi()
    api.running = {"running_bitrate_kbps": 0, "running_fps": 0}
    bitrate, _fps = _numbers(api)
    asyncio.run(bitrate.async_update())
    assert bitrate.native_value == 800 and bitrate.extra_state_attributes["pending_value"] is None


def test_a_failed_save_reads_the_values_again() -> None:
    api = _QualityApi()
    bitrate, _fps = _numbers(api)
    real = api.async_camera_quality

    async def refuse(**changes: int) -> dict[str, Any]:
        if changes:
            api.calls.append(changes)
            raise C300XAgentApiError("refused")
        return await real()

    api.async_camera_quality = refuse  # type: ignore[method-assign]
    with pytest.raises(HomeAssistantError):
        asyncio.run(bitrate.async_set_native_value(1000.0))
    assert bitrate.native_value == 800 and bitrate.available is True


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


def test_changes_to_both_numbers_are_saved_in_one_write() -> None:
    api = _QualityApi()
    bitrate, fps = _numbers(api)
    bitrate._batch.delay = 0.05

    async def both() -> None:
        await asyncio.gather(bitrate.async_set_native_value(3000.0), fps.async_set_native_value(25.0))

    asyncio.run(both())
    # One write, so the device restarts once.
    assert api.calls == [{"bitrate_kbps": 3000, "fps": 25}]
    assert bitrate.extra_state_attributes["pending_value"] == 3000
    assert fps.extra_state_attributes["pending_value"] == 25


def test_a_failed_write_is_reported_to_every_change_it_carried() -> None:
    api = _QualityApi()
    bitrate, fps = _numbers(api)
    bitrate._batch.delay = 0.05

    async def both() -> list[Any]:
        api.fail = True
        results = await asyncio.gather(bitrate.async_set_native_value(3000.0),
                                       fps.async_set_native_value(25.0), return_exceptions=True)
        api.fail = False
        return results

    results = asyncio.run(both())
    assert all(isinstance(result, HomeAssistantError) for result in results)
    assert api.calls[0] == {"bitrate_kbps": 3000, "fps": 25}


def test_removing_the_numbers_drops_a_change_not_written_yet() -> None:
    api = _QualityApi()
    bitrate, _fps = _numbers(api)
    bitrate._batch.delay = 30

    async def removed() -> None:
        pending = asyncio.ensure_future(bitrate.async_set_native_value(3000.0))
        await asyncio.sleep(0)
        bitrate._batch.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

    asyncio.run(removed())
    assert api.calls == []


def test_a_status_from_the_other_number_updates_only_the_same_entry() -> None:
    api = _QualityApi()
    bitrate, _fps = _numbers(api)
    asyncio.run(bitrate.async_update())
    status = {"supported": True, "bitrate_kbps": 2000, "fps": 15, "running_bitrate_kbps": 800,
              "running_fps": 15, "restart_required": True}
    bitrate._handle_status("other-entry", status)
    assert bitrate.extra_state_attributes["pending_value"] is None
    bitrate._handle_status("entry-1", status)
    assert bitrate.extra_state_attributes == {"restart_required": True, "pending_value": 2000}


def test_the_numbers_read_again_when_the_device_is_back_after_the_restart() -> None:
    from types import SimpleNamespace

    api = _QualityApi()
    bitrate, _fps = _numbers(api)
    scheduled: list[Any] = []
    connection = bitrate._entry.runtime_data.connection_state
    asyncio.run(bitrate.async_update())
    bitrate._handle_connection("entry-1")  # nothing pending: no read
    asyncio.run(bitrate.async_set_native_value(3000.0))
    bitrate.hass = SimpleNamespace(async_create_task=scheduled.append)  # type: ignore[assignment]
    connection.available = False
    bitrate._handle_connection("entry-1")
    bitrate._handle_connection("other-entry")
    assert scheduled == []
    connection.available = True
    bitrate._handle_connection("entry-1")
    assert len(scheduled) == 1
    api.restarted()
    asyncio.run(scheduled[0])
    assert bitrate.native_value == 3000 and bitrate.extra_state_attributes["restart_required"] is False

