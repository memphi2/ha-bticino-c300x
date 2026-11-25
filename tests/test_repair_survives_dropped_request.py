"""The agent update of a repair step finishes when its request is dropped.

Home Assistant cancels the request handler, and with it the flow step, when
the client disconnects. The update and the reload after it must not end there.
"""

from __future__ import annotations

import asyncio
import contextlib
import types
from typing import Any

import pytest
from test_agent_update_repairs import (
    FakeConfigEntries,
    FakeEntry,
    FakeHass,
    FakePatchApi,
    FakeRuntimeData,
    FakeSelfUpdateState,
)

from custom_components.bticino_c300x import repairs


class _ReloadingConfigEntries(FakeConfigEntries):
    """Reload like Home Assistant: a cancelled setup is swallowed and stays failed."""

    def __init__(self, entry: Any, gate: asyncio.Event | None = None) -> None:
        super().__init__(entry)
        self.state = "loaded"
        self.gate = gate
        self.reload_started = asyncio.Event()

    async def async_reload(self, entry_id: str) -> bool:
        self.reloads.append(entry_id)
        self.state = "not_loaded"
        self.reload_started.set()
        try:
            if self.gate is not None:
                await self.gate.wait()
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            # config_entries.py logs "Setup of config entry ... cancelled",
            # sets the state and does not raise.
            self.state = "setup_error"
            return False
        self.state = "loaded"
        return True


class _Station:
    """The steps of one update, with a gate in the upload."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []
        self.upload_started = asyncio.Event()
        self.upload_gate = asyncio.Event()

        async def apply_update(_hass: Any, _api: Any) -> dict[str, Any]:
            self.calls.append("apply_update")
            self.upload_started.set()
            await self.upload_gate.wait()
            return {"ok": True, "restart_scheduled": False, "qml_patch_changed": True}

        async def verify_update(_hass: Any, _api: Any, _result: Any) -> dict[str, Any]:
            self.calls.append("verify")
            return {"version": "1.1.0", "capabilities": {}}

        async def restore_state(*_args: Any) -> None:
            self.calls.append("restore")

        async def migrate_mqtt(_api: Any) -> None:
            self.calls.append("migrate_mqtt")

        async def apply_setup(_hass: Any, setup_entry: Any, _setup: Any) -> None:
            self.calls.append("apply_setup")
            setup_entry.runtime_data.agent_update_state = types.SimpleNamespace(
                update_required=False
            )

        monkeypatch.setattr(repairs, "async_apply_packaged_agent_update", apply_update)
        monkeypatch.setattr(repairs, "_async_verify_agent_after_update", verify_update)
        monkeypatch.setattr(repairs, "_async_restore_external_patch_state", restore_state)
        monkeypatch.setattr(repairs, "_async_migrate_mqtt_after_update", migrate_mqtt)
        monkeypatch.setattr(repairs, "_async_apply_repaired_agent_setup", apply_setup)
        monkeypatch.setattr(repairs, "async_dispatcher_send", lambda *_: None)
        monkeypatch.setattr(repairs.ir, "async_delete_issue", lambda **_: None)


def _flow(hass: FakeHass) -> repairs.DeviceAgentUpdateRepairFlow:
    flow = repairs.DeviceAgentUpdateRepairFlow(hass, "entry-1")  # type: ignore[arg-type]
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]
    return flow


def _entry() -> FakeEntry:
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    entry.runtime_data.agent_update_state = FakeSelfUpdateState()
    return entry


async def _settle() -> None:
    for _ in range(50):
        await asyncio.sleep(0)


FULL_UPDATE = ["apply_update", "verify", "restore", "migrate_mqtt", "apply_setup"]


@pytest.mark.parametrize("dropped_in", ["upload", "reload"])
def test_dropped_request_does_not_end_the_update(monkeypatch, dropped_in) -> None:
    async def scenario() -> None:
        entry = _entry()
        hass = FakeHass(entry)
        reload_gate = asyncio.Event()
        hass.config_entries = _ReloadingConfigEntries(entry, reload_gate)
        station = _Station(monkeypatch)
        flow = _flow(hass)

        request = asyncio.create_task(flow.async_step_confirm({}))
        await station.upload_started.wait()
        if dropped_in == "reload":
            station.upload_gate.set()
            await hass.config_entries.reload_started.wait()
        # The client disconnects: aiohttp cancels the request handler.
        request.cancel()
        # A setup that swallows the cancellation lets the step return instead.
        with contextlib.suppress(asyncio.CancelledError):
            await request
        station.upload_gate.set()
        reload_gate.set()
        await _settle()

        assert station.calls == FULL_UPDATE
        assert hass.config_entries.reloads == ["entry-1"]
        assert hass.config_entries.state == "loaded"

        # The client asks again: it gets the result it missed, no second update.
        result = await flow.async_step_confirm({})
        assert result == {"type": "create_entry", "data": {}}
        assert station.calls == FULL_UPDATE
        assert hass.config_entries.reloads == ["entry-1"]

    asyncio.run(scenario())


def test_resubmit_during_the_update_waits_for_it(monkeypatch) -> None:
    async def scenario() -> None:
        entry = _entry()
        hass = FakeHass(entry)
        hass.config_entries = _ReloadingConfigEntries(entry)
        station = _Station(monkeypatch)
        flow = _flow(hass)

        request = asyncio.create_task(flow.async_step_confirm({}))
        await station.upload_started.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        retry = asyncio.create_task(flow.async_step_confirm({}))
        await _settle()
        assert not retry.done()
        station.upload_gate.set()

        assert await retry == {"type": "create_entry", "data": {}}
        assert station.calls == FULL_UPDATE
        assert hass.config_entries.state == "loaded"

    asyncio.run(scenario())


def test_second_flow_does_not_update_the_station_a_second_time(monkeypatch) -> None:
    async def scenario() -> None:
        entry = _entry()
        hass = FakeHass(entry)
        hass.config_entries = _ReloadingConfigEntries(entry)
        station = _Station(monkeypatch)
        first = _flow(hass)
        second = _flow(hass)

        request = asyncio.create_task(first.async_step_confirm({}))
        await station.upload_started.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        # The repair is opened again from the list while the update runs.
        other = asyncio.create_task(second.async_step_confirm({}))
        await _settle()
        assert not other.done()
        # Dropping that request ends neither its wait's target nor the update.
        other.cancel()
        with pytest.raises(asyncio.CancelledError):
            await other
        other = asyncio.create_task(second.async_step_confirm({}))
        await _settle()
        station.upload_gate.set()

        assert await other == {"type": "create_entry", "data": {}}
        assert station.calls == FULL_UPDATE
        assert hass.config_entries.reloads == ["entry-1"]
        assert hass.config_entries.state == "loaded"

    asyncio.run(scenario())


def test_failed_update_is_reported_and_can_be_repeated(monkeypatch) -> None:
    async def scenario() -> None:
        entry = _entry()
        hass = FakeHass(entry)
        hass.config_entries = _ReloadingConfigEntries(entry)
        station = _Station(monkeypatch)
        attempts = 0

        async def failing_verify(_hass: Any, _api: Any, _result: Any) -> dict[str, Any]:
            nonlocal attempts
            attempts += 1
            raise RuntimeError("agent did not come back")

        monkeypatch.setattr(repairs, "_async_verify_agent_after_update", failing_verify)
        station.upload_gate.set()
        flow = _flow(hass)

        for expected in (1, 2):
            result = await flow.async_step_confirm({})
            assert result["errors"] == {"base": "update_failed"}
            assert attempts == expected
        assert hass.config_entries.reloads == []
        assert hass.data[f"{repairs.DOMAIN}_repair_work"] == {}

    asyncio.run(scenario())
