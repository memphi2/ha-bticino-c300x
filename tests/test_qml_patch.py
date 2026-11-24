from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x.api_errors import (
    C300XAgentApiConnectionError,
    C300XAgentApiError,
)
from custom_components.bticino_c300x.const import CONF_DASHBOARD_DYNAMIC_HOMEPAGE
from custom_components.bticino_c300x.data import C300XOperationDiagnostics
from custom_components.bticino_c300x.entry_locks import clear_entry_locks
from custom_components.bticino_c300x.qml_patch import (
    async_apply_qml_core_patch_and_confirm,
    async_apply_qml_patch_and_confirm,
    async_refresh_qml_patch_status,
    async_restore_qml_patch_and_confirm,
    async_restore_qml_patches_after_update,
)


@pytest.fixture(autouse=True)
def _fresh_entry_locks() -> Any:
    # Each test runs its own asyncio.run() loop; a cached Lock that saw
    # contention in an earlier test's loop cannot be awaited in a new one.
    clear_entry_locks("entry-1")
    yield
    clear_entry_locks("entry-1")


@dataclass
class _FakeApi:
    status: dict[str, Any] = field(default_factory=dict)
    apply_status: dict[str, Any] = field(default_factory=dict)
    restore_status: dict[str, Any] = field(default_factory=dict)
    core_apply_status: dict[str, Any] = field(default_factory=dict)
    fail_action: str | None = None
    fail_status: BaseException | None = None
    action_error: BaseException | None = None
    dynamic_homepage: bool | None = None
    calls: list[str] = field(default_factory=list)

    async def async_qml_patch_status(self) -> dict[str, Any]:
        self.calls.append("qml_status")
        if self.fail_status is not None:
            raise self.fail_status
        return self.status

    async def async_apply_qml_patch(
        self,
        *,
        dynamic_homepage: bool = False,
    ) -> dict[str, Any]:
        self.calls.append("apply_qml")
        self.dynamic_homepage = dynamic_homepage
        if self.action_error is not None:
            raise self.action_error
        if self.fail_action == "apply":
            raise RuntimeError("apply failed")
        return self.apply_status

    async def async_restore_qml_patch(self) -> dict[str, Any]:
        self.calls.append("restore_qml")
        if self.fail_action == "restore":
            raise RuntimeError("restore failed")
        return self.restore_status

    async def async_apply_qml_core_patch(self) -> dict[str, Any]:
        self.calls.append("apply_qml_core")
        if self.action_error is not None:
            raise self.action_error
        if self.fail_action == "core_apply":
            raise RuntimeError("core apply failed")
        return self.core_apply_status

    async def async_reload_gui(self) -> dict[str, Any]:
        self.calls.append("reload_gui")
        return {"ok": True}


def _entry(
    api: _FakeApi,
    initial: dict[str, Any] | None = None,
    *,
    options: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="entry-1",
        data={},
        options=options or {},
        runtime_data=SimpleNamespace(
            api=api,
            qml_patch_status=initial or {},
            qml_patch_status_updated_at=None,
        )
    )


def test_refresh_qml_patch_status_stores_device_status() -> None:
    api = _FakeApi(status={"available": True, "patched": True})
    entry = _entry(api)

    status = asyncio.run(async_refresh_qml_patch_status(entry))

    assert status == {"available": True, "patched": True}
    assert entry.runtime_data.qml_patch_status == status
    assert entry.runtime_data.qml_patch_status_updated_at is not None


@pytest.mark.parametrize("overlay", ["failed", "incomplete", "off", "unknown"])
@pytest.mark.parametrize("late", [False, True])
@pytest.mark.parametrize("core", [False, True])
def test_qt5_confirmation_rejects_action_and_late_activation_failure(overlay, late, core):
    active = {"available": True, "patched": True, "core_patched": True,
              "gui_running": True, "qt5_overlay": "active"}
    failed = {**active, "qt5_overlay": overlay}
    api = _FakeApi(status=failed if late else active,
                   apply_status=active if late else failed,
                   core_apply_status=active if late else failed)
    entry = _entry(api)
    run = async_apply_qml_core_patch_and_confirm if core else async_apply_qml_patch_and_confirm
    with pytest.raises(C300XAgentApiError, match="activation is not confirmed"):
        asyncio.run(run(entry))
    assert entry.runtime_data.qml_patch_status == failed
    assert api.calls == (["apply_qml_core" if core else "apply_qml"] + (["qml_status"] if late else []))


@pytest.mark.parametrize("late", [False, True])
def test_qt5_update_failure_stays_visible_without_following_core_failure_with_reload(late):
    active = {"available": True, "patched": True, "core_patched": True,
              "gui_running": True, "qt5_overlay": "active"}
    failed = {**active, "qt5_overlay": "failed"}
    api = _FakeApi(status=failed, core_apply_status=active if late else failed)
    entry = _entry(api)
    with pytest.raises(C300XAgentApiError, match="activation is not confirmed"):
        asyncio.run(async_restore_qml_patches_after_update(entry, apply_full_patch=False))
    assert entry.runtime_data.qml_patch_status == failed
    assert api.calls == ["apply_qml_core", *(["reload_gui", "qml_status"] if late else [])]


def test_qt5_restore_can_confirm_complete_removal():
    original = {"available": True, "patched": False, "core_patched": False,
                "gui_running": True, "qt5_overlay": "off"}
    api = _FakeApi(status=original, restore_status=original)
    assert asyncio.run(async_restore_qml_patch_and_confirm(_entry(api))) == original


def test_apply_qml_patch_confirms_with_fresh_status() -> None:
    api = _FakeApi(
        status={"available": True, "patched": True, "state": "patched"},
        apply_status={"patched": True},
    )
    entry = _entry(api, {"available": True, "patched": False, "gui_running": True})
    changes = 0

    def _changed() -> None:
        nonlocal changes
        changes += 1

    status = asyncio.run(async_apply_qml_patch_and_confirm(entry, _changed))

    assert status == {"available": True, "patched": True, "state": "patched"}
    assert changes == 2
    assert entry.runtime_data.qml_patch_status == status


@pytest.mark.parametrize(
    ("options", "expected"),
    [({}, True), ({CONF_DASHBOARD_DYNAMIC_HOMEPAGE: True}, True),
     ({CONF_DASHBOARD_DYNAMIC_HOMEPAGE: False}, False)],
    ids=["absent_is_stock", "stock", "side_by_side"],
)
def test_apply_qml_patch_forwards_the_home_page_layout(
    options: dict[str, Any], expected: bool
) -> None:
    api = _FakeApi(
        status={"available": True, "patched": True, "state": "patched"},
        apply_status={"patched": True},
    )
    entry = _entry(api, options=options)

    asyncio.run(async_apply_qml_patch_and_confirm(entry))

    assert api.dynamic_homepage is expected


def test_agent_update_repatch_keeps_a_side_by_side_layout() -> None:
    api = _FakeApi(
        status={"available": True, "patched": True, "state": "patched"},
        apply_status={"patched": True},
        core_apply_status={"core_patched": True},
    )
    entry = _entry(api, options={CONF_DASHBOARD_DYNAMIC_HOMEPAGE: False})

    asyncio.run(async_restore_qml_patches_after_update(entry, apply_full_patch=True))

    assert api.dynamic_homepage is False


def test_restore_qml_patch_keeps_action_status_when_confirmation_mismatches() -> None:
    api = _FakeApi(restore_status={"available": True, "patched": True, "state": "busy"})
    entry = _entry(api, {"available": True, "patched": True})

    status = asyncio.run(async_restore_qml_patch_and_confirm(entry))

    assert status == {"available": True, "patched": True, "state": "busy"}
    assert entry.runtime_data.qml_patch_status == status


@pytest.mark.parametrize("read_fails", [False, True])
def test_apply_qml_patch_restores_previous_status_on_error(read_fails: bool) -> None:
    """A failed write (a 504 timeout too) may have changed the device: its
    status is read again; the status from before comes back only when that
    read fails as well."""

    device = {"available": True, "patched": False, "state": "partial", "transaction": "pending"}
    api = _FakeApi(
        fail_action="apply",
        status=device,
        fail_status=C300XAgentApiConnectionError("offline") if read_fails else None,
    )
    previous = {"available": True, "patched": True, "core_patched": False, "state": "patched"}
    entry = _entry(api, previous)

    with pytest.raises(RuntimeError, match="apply failed"):
        asyncio.run(async_apply_qml_patch_and_confirm(entry))

    assert entry.runtime_data.qml_patch_status == (previous if read_fails else device)
    assert api.calls[-1] == "qml_status"


def test_core_patch_confirm_paths_update_core_state() -> None:
    api = _FakeApi(
        status={
            "available": True,
            "patched": False,
            "core_patched": True,
            "core_state": "patched",
        },
        core_apply_status={"core_patched": True},
    )
    entry = _entry(api, {"available": True, "patched": False, "core_patched": False})

    status = asyncio.run(async_apply_qml_core_patch_and_confirm(entry))

    assert status["core_patched"] is True
    assert entry.runtime_data.qml_patch_status == status


def test_core_patch_keeps_action_status_when_apply_confirmation_mismatches() -> None:
    api = _FakeApi(core_apply_status={"core_patched": False, "core_state": "busy"})
    entry = _entry(api, {"available": True, "patched": False, "core_patched": False})

    status = asyncio.run(async_apply_qml_core_patch_and_confirm(entry))

    assert status == {"core_patched": False, "core_state": "busy"}
    assert entry.runtime_data.qml_patch_status == status


@pytest.mark.parametrize("read_fails", [False, True])
def test_core_patch_restores_previous_status_on_apply_error(read_fails: bool) -> None:
    """A failed write (a 504 timeout too) may have changed the device: its
    status is read again; the status from before comes back only when that
    read fails as well."""

    device = {"available": True, "patched": False, "state": "partial", "transaction": "pending"}
    api = _FakeApi(
        fail_action="core_apply",
        status=device,
        fail_status=C300XAgentApiConnectionError("offline") if read_fails else None,
    )
    previous = {"available": True, "patched": True, "core_patched": False, "state": "patched"}
    entry = _entry(api, previous)

    with pytest.raises(RuntimeError, match="core apply failed"):
        asyncio.run(async_apply_qml_core_patch_and_confirm(entry))

    assert entry.runtime_data.qml_patch_status == (previous if read_fails else device)
    assert api.calls[-1] == "qml_status"


@pytest.mark.parametrize("read_fails", [False, True])
def test_restore_qml_patch_restores_previous_status_on_error(read_fails: bool) -> None:
    """A failed write (a 504 timeout too) may have changed the device: its
    status is read again; the status from before comes back only when that
    read fails as well."""

    device = {"available": True, "patched": False, "state": "partial", "transaction": "pending"}
    api = _FakeApi(
        fail_action="restore",
        status=device,
        fail_status=C300XAgentApiConnectionError("offline") if read_fails else None,
    )
    previous = {"available": True, "patched": True, "core_patched": False, "state": "patched"}
    entry = _entry(api, previous)

    with pytest.raises(RuntimeError, match="restore failed"):
        asyncio.run(async_restore_qml_patch_and_confirm(entry))

    assert entry.runtime_data.qml_patch_status == (previous if read_fails else device)
    assert api.calls[-1] == "qml_status"


def test_concurrent_patch_actions_do_not_run_the_device_action_together() -> None:
    """A switch toggle racing a repair-flow action must not hit the device concurrently."""

    class _SlowApi(_FakeApi):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.active = 0
            self.max_active = 0

        async def async_apply_qml_patch(
            self,
            *,
            dynamic_homepage: bool = False,
        ) -> dict[str, Any]:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0.02)
                return await super().async_apply_qml_patch(
                    dynamic_homepage=dynamic_homepage
                )
            finally:
                self.active -= 1

        async def async_apply_qml_core_patch(self) -> dict[str, Any]:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0.02)
                return await super().async_apply_qml_core_patch()
            finally:
                self.active -= 1

    api = _SlowApi(
        status={"available": True, "patched": True, "state": "patched"},
        apply_status={"patched": True},
        core_apply_status={"core_patched": True},
    )
    entry = _entry(api, {"available": True, "patched": False, "core_patched": False})

    async def _run() -> None:
        await asyncio.gather(
            async_apply_qml_patch_and_confirm(entry),
            async_apply_qml_core_patch_and_confirm(entry),
        )

    asyncio.run(_run())

    assert api.max_active == 1


def test_restore_after_update_applies_core_full_patch_and_reloads_gui() -> None:
    api = _FakeApi(
        status={"available": True, "patched": True, "state": "patched"},
        apply_status={"patched": True},
        core_apply_status={"core_patched": True},
    )
    entry = _entry(api, {"available": True, "patched": False})

    status = asyncio.run(
        async_restore_qml_patches_after_update(entry, apply_full_patch=True)
    )

    assert api.calls == [
        "apply_qml_core",
        "apply_qml",
        "qml_status",
        "reload_gui",
        "qml_status",
    ]
    assert status == {"available": True, "patched": True, "state": "patched"}
    assert entry.runtime_data.qml_patch_status == status
    assert entry.runtime_data.qml_patch_status_updated_at is not None


def test_restore_after_update_waits_while_the_agent_runs_another_job(monkeypatch) -> None:
    """Home Assistant reads the patch status on its own after the agent restarts.

    The agent runs one maintenance job at a time, so each step of the restore
    can be rejected as busy; that must not end the update with an error.
    """

    from unittest.mock import AsyncMock

    from custom_components.bticino_c300x import agent_update
    from custom_components.bticino_c300x.api_errors import C300XAgentApiConnectionError

    class _BusyFirstApi(_FakeApi):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.rejected: list[str] = []

        def _busy_once(self, step: str) -> None:
            if step not in self.rejected:
                self.rejected.append(step)
                raise C300XAgentApiConnectionError(
                    "device agent returned HTTP 409: maintenance_busy"
                )

        async def async_qml_patch_status(self) -> dict[str, Any]:
            self._busy_once("qml_status")
            return await super().async_qml_patch_status()

        async def async_apply_qml_patch(self, *, dynamic_homepage: bool | None = None) -> dict[str, Any]:
            self._busy_once("apply_qml")
            return await super().async_apply_qml_patch(dynamic_homepage=dynamic_homepage)

        async def async_apply_qml_core_patch(self) -> dict[str, Any]:
            self._busy_once("apply_qml_core")
            return await super().async_apply_qml_core_patch()

        async def async_reload_gui(self) -> dict[str, Any]:
            self._busy_once("reload_gui")
            return await super().async_reload_gui()

    monkeypatch.setattr(agent_update.asyncio, "sleep", AsyncMock())
    api = _BusyFirstApi(
        status={"available": True, "patched": True, "state": "patched"},
        apply_status={"patched": True},
        core_apply_status={"core_patched": True},
    )
    entry = _entry(api, {"available": True, "patched": False})

    status = asyncio.run(
        async_restore_qml_patches_after_update(entry, apply_full_patch=True)
    )

    assert api.rejected == ["apply_qml_core", "apply_qml", "qml_status", "reload_gui"]
    assert api.calls == ["apply_qml_core", "apply_qml", "qml_status", "reload_gui", "qml_status"]
    assert api.dynamic_homepage is True
    assert status == {"available": True, "patched": True, "state": "patched"}


def test_restore_after_update_skips_full_patch_when_not_required() -> None:
    api = _FakeApi(
        status={"available": True, "patched": False, "core_patched": True},
        core_apply_status={"core_patched": True},
    )
    entry = _entry(api)

    asyncio.run(async_restore_qml_patches_after_update(entry, apply_full_patch=False))

    assert api.calls == ["apply_qml_core", "reload_gui", "qml_status"]


def test_restore_after_update_serializes_against_concurrent_switch_toggle() -> None:
    """The post-update restore sequence must not interleave with a switch toggle."""

    class _SlowApi(_FakeApi):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.active = 0
            self.max_active = 0

        async def _tracked(self, result: dict[str, Any]) -> dict[str, Any]:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0.02)
                return result
            finally:
                self.active -= 1

        async def async_apply_qml_core_patch(self) -> dict[str, Any]:
            self.calls.append("apply_qml_core")
            return await self._tracked(self.core_apply_status)

        async def async_restore_qml_patch(self) -> dict[str, Any]:
            self.calls.append("restore_qml")
            return await self._tracked(self.restore_status)

    api = _SlowApi(
        status={"available": True, "patched": True, "state": "patched"},
        apply_status={"patched": True},
        restore_status={"patched": False},
        core_apply_status={"core_patched": True},
    )
    entry = _entry(api, {"available": True, "patched": True})

    async def _run() -> None:
        await asyncio.gather(
            async_restore_qml_patches_after_update(entry, apply_full_patch=True),
            async_restore_qml_patch_and_confirm(entry),
        )

    asyncio.run(_run())

    assert api.max_active == 1


@pytest.mark.parametrize("core", [False, True])
def test_a_cancelled_write_never_keeps_the_transient_status(core: bool) -> None:
    api = _FakeApi(action_error=asyncio.CancelledError())
    previous = {"available": True, "patched": False, "state": "original", "core_patched": True}
    entry = _entry(api, previous)
    action = async_apply_qml_core_patch_and_confirm if core else async_apply_qml_patch_and_confirm

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(action(entry))

    assert entry.runtime_data.qml_patch_status == previous


@pytest.mark.parametrize("core", [False, True])
def test_a_cancel_during_the_read_after_a_failed_write_restores_the_status(
    core: bool,
) -> None:
    api = _FakeApi(
        action_error=C300XAgentApiConnectionError("timeout"),
        fail_status=asyncio.CancelledError(),
    )
    previous = {"available": True, "patched": False, "state": "original", "core_patched": True}
    entry = _entry(api, previous)
    changes = 0

    def _changed() -> None:
        nonlocal changes
        changes += 1

    action = async_apply_qml_core_patch_and_confirm if core else async_apply_qml_patch_and_confirm
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(action(entry, _changed))

    assert api.calls[-1] == "qml_status"
    assert entry.runtime_data.qml_patch_status == previous
    assert changes == 2


@pytest.mark.parametrize("core", [False, True])
def test_a_stuck_leftover_stays_reported_during_a_write(
    core: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """A write's transient status keeps the stuck leftover: the Repairs issue
    is not dropped mid-write and the warning is not logged again."""

    stuck = {"available": True, "patched": True, "core_patched": True, "transaction": "stuck"}
    seen: list[Any] = []

    class _Api(_FakeApi):
        async def async_apply_qml_patch(self, **kwargs: Any) -> dict[str, Any]:
            seen.append(entry.runtime_data.qml_patch_status.get("transaction"))
            return await super().async_apply_qml_patch(**kwargs)

        async def async_apply_qml_core_patch(self) -> dict[str, Any]:
            seen.append(entry.runtime_data.qml_patch_status.get("transaction"))
            return await super().async_apply_qml_core_patch()

    api = _Api(status=stuck, apply_status=stuck, core_apply_status=stuck)
    entry = _entry(api, dict(stuck))
    action = async_apply_qml_core_patch_and_confirm if core else async_apply_qml_patch_and_confirm

    with caplog.at_level("WARNING"):
        asyncio.run(action(entry))

    assert seen == ["stuck"]
    assert entry.runtime_data.qml_patch_status["transaction"] == "stuck"
    assert "could not be finished" not in caplog.text


@pytest.mark.parametrize("core", [False, True])
def test_a_failed_confirming_read_keeps_the_writes_own_answer(core: bool) -> None:
    """A busy or timed-out read right after a successful write must not leave
    the "patching" status behind until a reload."""

    answer = {"available": True, "patched": True, "state": "patched", "core_patched": True}
    api = _FakeApi(
        apply_status=answer,
        core_apply_status=answer,
        fail_status=C300XAgentApiConnectionError(
            "device agent returned HTTP 409: maintenance_busy"
        ),
    )
    entry = _entry(api, {"available": True, "patched": False, "core_patched": False})
    changes = 0

    def _changed() -> None:
        nonlocal changes
        changes += 1

    action = async_apply_qml_core_patch_and_confirm if core else async_apply_qml_patch_and_confirm
    status = asyncio.run(action(entry, _changed))

    assert status == answer
    assert entry.runtime_data.qml_patch_status == answer
    assert changes == 2


def test_a_real_status_read_clears_an_earlier_failed_read() -> None:
    """The core hook Repairs issue follows the last read; one busy read at
    startup must not keep it after later reads succeed."""

    api = _FakeApi(status={"available": True, "core_patched": True})
    entry = _entry(api)
    diagnostics = C300XOperationDiagnostics()
    diagnostics.mark_failure("busy", datetime.now(UTC))
    entry.runtime_data.diagnostics = SimpleNamespace(qml_patch_diagnostics=diagnostics)

    asyncio.run(async_refresh_qml_patch_status(entry))

    assert diagnostics.last_error is None
