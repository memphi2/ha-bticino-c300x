from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x.qml_patch import (
    async_apply_qml_core_patch_and_confirm,
    async_apply_qml_patch_and_confirm,
    async_refresh_qml_patch_status,
    async_restore_qml_core_patch_and_confirm,
    async_restore_qml_patch_and_confirm,
)


@dataclass
class _FakeApi:
    status: dict[str, Any] = field(default_factory=dict)
    apply_status: dict[str, Any] = field(default_factory=dict)
    restore_status: dict[str, Any] = field(default_factory=dict)
    core_apply_status: dict[str, Any] = field(default_factory=dict)
    core_restore_status: dict[str, Any] = field(default_factory=dict)
    fail_action: str | None = None

    async def async_qml_patch_status(self) -> dict[str, Any]:
        return self.status

    async def async_apply_qml_patch(self) -> dict[str, Any]:
        if self.fail_action == "apply":
            raise RuntimeError("apply failed")
        return self.apply_status

    async def async_restore_qml_patch(self) -> dict[str, Any]:
        if self.fail_action == "restore":
            raise RuntimeError("restore failed")
        return self.restore_status

    async def async_apply_qml_core_patch(self) -> dict[str, Any]:
        if self.fail_action == "core_apply":
            raise RuntimeError("core apply failed")
        return self.core_apply_status

    async def async_restore_qml_core_patch(self) -> dict[str, Any]:
        if self.fail_action == "core_restore":
            raise RuntimeError("core restore failed")
        return self.core_restore_status


def _entry(api: _FakeApi, initial: dict[str, Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
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
