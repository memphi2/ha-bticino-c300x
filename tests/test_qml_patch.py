from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x.const import CONF_DASHBOARD_DYNAMIC_HOMEPAGE
from custom_components.bticino_c300x.entry_locks import clear_entry_locks
from custom_components.bticino_c300x.qml_patch import (
    async_apply_qml_core_patch_and_confirm,
    async_apply_qml_patch_and_confirm,
    async_refresh_qml_patch_status,
    async_restore_qml_core_patch_and_confirm,
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
    core_restore_status: dict[str, Any] = field(default_factory=dict)
    fail_action: str | None = None
    dynamic_homepage: bool | None = None
    calls: list[str] = field(default_factory=list)

    async def async_qml_patch_status(self) -> dict[str, Any]:
        self.calls.append("qml_status")
        return self.status

    async def async_apply_qml_patch(
        self,
        *,
        dynamic_homepage: bool = False,
    ) -> dict[str, Any]:
        self.calls.append("apply_qml")
        self.dynamic_homepage = dynamic_homepage
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
        if self.fail_action == "core_apply":
            raise RuntimeError("core apply failed")
        return self.core_apply_status

    async def async_restore_qml_core_patch(self) -> dict[str, Any]:
        self.calls.append("restore_qml_core")
        if self.fail_action == "core_restore":
            raise RuntimeError("core restore failed")
        return self.core_restore_status

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


def test_apply_qml_patch_forwards_dynamic_home_page_option() -> None:
    api = _FakeApi(
        status={"available": True, "patched": True, "state": "patched"},
        apply_status={"patched": True},
    )
    entry = _entry(api, options={CONF_DASHBOARD_DYNAMIC_HOMEPAGE: True})

    asyncio.run(async_apply_qml_patch_and_confirm(entry))

    assert api.dynamic_homepage is True


def test_restore_qml_patch_keeps_action_status_when_confirmation_mismatches() -> None:
    api = _FakeApi(restore_status={"available": True, "patched": True, "state": "busy"})
    entry = _entry(api, {"available": True, "patched": True})

    status = asyncio.run(async_restore_qml_patch_and_confirm(entry))

    assert status == {"available": True, "patched": True, "state": "busy"}
    assert entry.runtime_data.qml_patch_status == status


def test_apply_qml_patch_restores_previous_status_on_error() -> None:
    api = _FakeApi(fail_action="apply")
    previous = {"available": True, "patched": False, "state": "original"}
    entry = _entry(api, previous)

    with pytest.raises(RuntimeError, match="apply failed"):
        asyncio.run(async_apply_qml_patch_and_confirm(entry))

    assert entry.runtime_data.qml_patch_status == previous


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


def test_core_patch_restores_previous_status_on_apply_error() -> None:
    api = _FakeApi(fail_action="core_apply")
    previous = {"available": True, "patched": True, "core_patched": False}
    entry = _entry(api, previous)

    with pytest.raises(RuntimeError, match="core apply failed"):
        asyncio.run(async_apply_qml_core_patch_and_confirm(entry))

    assert entry.runtime_data.qml_patch_status == previous


def test_core_patch_keeps_action_status_when_confirmation_mismatches() -> None:
    api = _FakeApi(core_restore_status={"core_patched": True, "core_state": "busy"})
    entry = _entry(api, {"available": True, "patched": False, "core_patched": True})

    status = asyncio.run(async_restore_qml_core_patch_and_confirm(entry))

    assert status == {"core_patched": True, "core_state": "busy"}
    assert entry.runtime_data.qml_patch_status == status


def test_core_patch_restores_previous_status_on_error() -> None:
    api = _FakeApi(fail_action="core_restore")
    previous = {"available": True, "patched": True, "core_patched": True}
    entry = _entry(api, previous)

    with pytest.raises(RuntimeError, match="core restore failed"):
        asyncio.run(async_restore_qml_core_patch_and_confirm(entry))

    assert entry.runtime_data.qml_patch_status == previous


def test_restore_qml_patch_restores_previous_status_on_error() -> None:
    api = _FakeApi(fail_action="restore")
    previous = {"available": True, "patched": True, "state": "patched"}
    entry = _entry(api, previous)

    with pytest.raises(RuntimeError, match="restore failed"):
        asyncio.run(async_restore_qml_patch_and_confirm(entry))

    assert entry.runtime_data.qml_patch_status == previous


def test_concurrent_apply_and_restore_do_not_run_the_device_action_together() -> None:
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

        async def async_restore_qml_core_patch(self) -> dict[str, Any]:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0.02)
                return await super().async_restore_qml_core_patch()
            finally:
                self.active -= 1

    api = _SlowApi(
        status={"available": True, "patched": True, "state": "patched"},
        apply_status={"patched": True},
        core_restore_status={"core_patched": False},
    )
    entry = _entry(api, {"available": True, "patched": False, "core_patched": True})

    async def _run() -> None:
        await asyncio.gather(
            async_apply_qml_patch_and_confirm(entry),
            async_restore_qml_core_patch_and_confirm(entry),
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
