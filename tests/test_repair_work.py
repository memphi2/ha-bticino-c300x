"""Repair work that Home Assistant owns: what a later submit gets.

``RepairStepWork`` keeps the work of a repair step running when its request is
dropped. These tests cover what the next submit receives: the missed result,
its own run with new input, and a clean start after the work was cancelled or
raised.
"""

from __future__ import annotations

import asyncio
import contextlib
import types
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from test_agent_update_repairs import (
    FakeAgentUpdateState,
    FakeEntry,
    FakeHass,
    FakePatchApi,
    FakeRuntimeData,
)

from custom_components.bticino_c300x import repair_work, repairs
from custom_components.bticino_c300x.device_installer import C300XDeviceInstallError
from custom_components.bticino_c300x.factory_login import LOGIN_REFUSED
from custom_components.bticino_c300x.repair_work import (
    OTHER_FLOW_FINISHED,
    RepairStepWork,
)

FIRST_LOGIN = {"bootstrap_ssh_username": "root", "bootstrap_ssh_password": "first"}
SECOND_LOGIN = {"bootstrap_ssh_username": "root", "bootstrap_ssh_password": "second"}


async def _settle() -> None:
    for _ in range(50):
        await asyncio.sleep(0)


async def _drop(request: asyncio.Task[Any]) -> None:
    request.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await request


def _needed() -> bool:
    return True


# -- a resubmit of the SSH install with other credentials --------------------


class _Installer:
    """The SSH installer: refuses the first password, held open by a gate."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.passwords: list[str] = []
        self.started = asyncio.Event()
        self.gate = asyncio.Event()

        async def install(request: Any, **_kwargs: Any) -> Any:
            self.passwords.append(request.ssh_password)
            self.started.set()
            await self.gate.wait()
            if request.ssh_password != "second":
                raise C300XDeviceInstallError(LOGIN_REFUSED)
            return types.SimpleNamespace(changed_files=())

        async def nothing(*_args: Any, **_kwargs: Any) -> None:
            return None

        async def wait_for_agent(_api: Any) -> dict[str, Any]:
            return {"version": "1.1.0", "capabilities": {}}

        async def apply_setup(_hass: Any, entry: Any, _setup: Any) -> None:
            entry.runtime_data.agent_update_state = types.SimpleNamespace(update_required=False)

        monkeypatch.setattr(repairs, "async_install_device_agent", install)
        monkeypatch.setattr(repairs, "async_ensure_installer_dependencies", nothing)
        monkeypatch.setattr(repairs, "_async_wait_for_agent_after_update", wait_for_agent)
        monkeypatch.setattr(repairs, "async_migrate_legacy_mqtt_if_available", nothing)
        monkeypatch.setattr(repairs, "_async_apply_repaired_agent_setup", apply_setup)
        monkeypatch.setattr(repairs.ir, "async_delete_issue", lambda **_: None)


def _ssh_flow() -> repairs.DeviceAgentUpdateRepairFlow:
    entry = FakeEntry(
        runtime_data=FakeRuntimeData(FakePatchApi()),
        data={"agent_host": "192.0.2.60", "agent_token": "agent-token"},
    )
    entry.runtime_data.agent_update_state = FakeAgentUpdateState()
    flow = repairs.DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]
    return flow


def test_resubmit_with_new_credentials_after_a_missed_failure_runs_again(monkeypatch) -> None:
    async def scenario() -> None:
        installer = _Installer(monkeypatch)
        flow = _ssh_flow()

        request = asyncio.create_task(flow.async_step_ssh_install(FIRST_LOGIN))
        await installer.started.wait()
        await _drop(request)
        installer.gate.set()
        await _settle()
        assert installer.passwords == ["first"]

        # The failure was never shown. The client sends other credentials:
        # they are used, not answered with the failure of the old ones.
        result = await flow.async_step_ssh_install(SECOND_LOGIN)

        assert result == {"type": "create_entry", "data": {}}
        assert installer.passwords == ["first", "second"]

    asyncio.run(scenario())


def test_resubmit_with_the_same_input_gets_the_missed_failure(monkeypatch) -> None:
    async def scenario() -> None:
        installer = _Installer(monkeypatch)
        flow = _ssh_flow()

        request = asyncio.create_task(flow.async_step_ssh_install(FIRST_LOGIN))
        await installer.started.wait()
        await _drop(request)
        installer.gate.set()
        await _settle()

        result = await flow.async_step_ssh_install(FIRST_LOGIN)

        assert result["errors"] == {"base": LOGIN_REFUSED}
        assert installer.passwords == ["first"]

    asyncio.run(scenario())


def test_resubmit_with_new_credentials_waits_for_the_running_install(monkeypatch) -> None:
    async def scenario() -> None:
        installer = _Installer(monkeypatch)
        flow = _ssh_flow()

        request = asyncio.create_task(flow.async_step_ssh_install(FIRST_LOGIN))
        await installer.started.wait()
        await _drop(request)
        retry = asyncio.create_task(flow.async_step_ssh_install(SECOND_LOGIN))
        await _settle()
        # One install at a time on the station.
        assert not retry.done()
        assert installer.passwords == ["first"]
        installer.gate.set()

        assert await retry == {"type": "create_entry", "data": {}}
        assert installer.passwords == ["first", "second"]

    asyncio.run(scenario())


# -- the work object itself --------------------------------------------------


def _hass() -> Any:
    return types.SimpleNamespace(data={})


def test_submit_that_waited_gets_nothing_to_run_when_the_repair_is_done() -> None:
    async def scenario() -> None:
        hass = _hass()
        gate = asyncio.Event()
        ran: list[str] = []

        async def first_work() -> str:
            await gate.wait()
            return "first"

        async def second_work() -> str:
            ran.append("second")
            return "second"

        first = asyncio.create_task(
            RepairStepWork(hass, "entry-1").async_run(first_work, {}, _needed)
        )
        await _settle()
        second = asyncio.create_task(
            RepairStepWork(hass, "entry-1").async_run(second_work, {}, lambda: False)
        )
        await _settle()
        assert not second.done()
        gate.set()

        assert await first == "first"
        assert await second is OTHER_FLOW_FINISHED
        assert ran == []

    asyncio.run(scenario())


def test_work_cancelled_with_home_assistant_is_not_kept() -> None:
    async def scenario() -> None:
        hass = _hass()
        work = RepairStepWork(hass, "entry-1")
        started = asyncio.Event()
        runs: list[int] = []

        async def step() -> str:
            runs.append(1)
            started.set()
            if len(runs) == 1:
                await asyncio.Event().wait()
            return "done"

        request = asyncio.create_task(work.async_run(step, {}, _needed))
        await started.wait()
        # Home Assistant stops: it cancels the work, not only the request.
        hass.data[repair_work._RUNNING]["entry-1"].cancel()

        with pytest.raises(asyncio.CancelledError):
            await request
        assert work._task is None
        assert hass.data[repair_work._RUNNING] == {}
        # The cancelled work is not handed out as a result: a submit runs anew.
        assert await work.async_run(step, {}, _needed) == "done"
        assert len(runs) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("request_dropped", [False, True])
def test_work_that_raised_is_reported_once_and_not_kept(request_dropped) -> None:
    async def scenario() -> None:
        hass = _hass()
        work = RepairStepWork(hass, "entry-1")
        gate = asyncio.Event()
        runs: list[int] = []

        async def step() -> str:
            runs.append(1)
            await gate.wait()
            if len(runs) == 1:
                raise RuntimeError("step failed")
            return "done"

        request = asyncio.create_task(work.async_run(step, {}, _needed))
        await _settle()
        if request_dropped:
            await _drop(request)
            gate.set()
            await _settle()
            # The submit that asks again is told once.
            request = asyncio.create_task(work.async_run(step, {}, _needed))
        gate.set()

        with pytest.raises(RuntimeError, match="step failed"):
            await request
        assert work._task is None
        assert hass.data[repair_work._RUNNING] == {}
        assert await work.async_run(step, {}, _needed) == "done"
        assert len(runs) == 2

    asyncio.run(scenario())


def test_work_runs_as_a_task_of_a_real_home_assistant(tmp_path) -> None:
    """``hass.async_create_task`` of the installed core, not the test stand-in."""

    async def scenario() -> None:
        hass = HomeAssistant(str(tmp_path))
        work = RepairStepWork(hass, "entry-1")
        gate = asyncio.Event()
        started = asyncio.Event()
        tasks: list[asyncio.Task[Any] | None] = []

        async def step() -> str:
            tasks.append(asyncio.current_task())
            started.set()
            await gate.wait()
            return "done"

        request = asyncio.create_task(work.async_run(step, {}, _needed))
        await started.wait()
        running = hass.data[repair_work._RUNNING]["entry-1"]
        assert running is tasks[0]
        assert running.get_name() == "bticino_c300x repair work entry-1"
        await _drop(request)
        assert not running.done()
        # Home Assistant tracks the work itself: it waits for it, request or not.
        idle = asyncio.create_task(hass.async_block_till_done())
        await _settle()
        assert not idle.done()
        gate.set()
        await idle

        assert running.done()
        assert hass.data[repair_work._RUNNING] == {}
        # The result nobody received is handed to the submit that asks again.
        assert await work.async_run(step, {}, _needed) == "done"
        assert len(tasks) == 1

    asyncio.run(scenario())
