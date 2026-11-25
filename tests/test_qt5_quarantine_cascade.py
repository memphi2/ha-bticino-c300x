"""A quarantine of the Qt 5 overlay no longer blocks the HA steps that depend on it.

The Home Assistant helpers run against the real qml_patch.sh on a fixture of
firmware 3.0.x. A quarantine mark of this boot used to keep the core Repair at
``qt5_failed``, leave the agent update with ``qml_patch_pending`` and refuse
the media-user label; an apply now gives the overlay one more start.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x._api_normalize import normalize_qml_patch_status
from custom_components.bticino_c300x.api_errors import C300XAgentApiError
from custom_components.bticino_c300x.display_activation import (
    display_activation_confirmed,
)
from custom_components.bticino_c300x.entry_locks import clear_entry_locks
from custom_components.bticino_c300x.qml_patch import (
    async_apply_qml_core_patch_and_confirm,
    async_restore_qml_patches_after_update,
)
from tests.test_qml_patch_qt5_overlay import Device
from tests.test_qml_patch_qt5_overlay import programs as programs


class _ScriptApi:
    """The maintenance calls HA makes, answered by the script on the fixture."""

    def __init__(self, device: Device, env: dict[str, str]) -> None:
        self.device = device
        self.env = env
        self.calls: list[str] = []

    def _run(self, action: str, **env: str) -> dict[str, Any]:
        self.calls.append(action)
        return normalize_qml_patch_status(self.device.ok(action, **self.env, **env))

    async def async_qml_patch_status(self) -> dict[str, Any]:
        return self._run("status")

    async def async_apply_qml_core_patch(self) -> dict[str, Any]:
        return self._run("core-apply")

    async def async_apply_qml_patch(self, *, dynamic_homepage: bool | None = None) -> dict[str, Any]:
        layout = {} if dynamic_homepage is None else {"C300X_QML_DYNAMIC_HOME_PAGE": "1" if dynamic_homepage else "0"}
        return self._run("apply", **layout)

    async def async_reload_gui(self, *, display_restart: bool = False) -> dict[str, Any]:
        # The Qt 5 display restart gets the longer wait.
        assert display_restart
        self._run("reload")
        return {"ok": True}


@pytest.fixture
def quarantined(tmp_path: Path, programs: dict[str, Path]) -> Iterator[tuple[Device, SimpleNamespace]]:
    clear_entry_locks("entry-1")
    tools = tmp_path / "tools"
    tools.mkdir()
    # A display program runs; restarts are not part of this fixture.
    (tools / "pidof").write_text("#!/bin/sh\necho 4242\n")
    (tools / "pidof").chmod(0o755)
    (tmp_path / "device").mkdir()
    device = Device(tmp_path / "device", programs)
    env = {"PATH": f"{tools}:{os.environ['PATH']}"}
    device.ok("apply", **env)
    device.ok("media-user-label-apply", **env)
    Path(f"{device.rcc}.failed").write_text("boot-1\n")
    status = normalize_qml_patch_status(device.ok("status", **env))
    assert status["qt5_overlay"] == "failed" and not display_activation_confirmed(status)
    api = _ScriptApi(device, env)
    entry = SimpleNamespace(
        entry_id="entry-1", data={}, options={},
        runtime_data=SimpleNamespace(api=api, qml_patch_status=status, qml_patch_status_updated_at=None),
    )
    yield device, entry
    clear_entry_locks("entry-1")


def test_the_core_repair_gives_the_overlay_one_more_start(quarantined: tuple[Device, SimpleNamespace]) -> None:
    device, entry = quarantined
    status = asyncio.run(async_apply_qml_core_patch_and_confirm(entry))
    assert status["core_patched"] is True and display_activation_confirmed(status)
    assert not Path(f"{device.rcc}.failed").exists()


@pytest.mark.parametrize("full", [False, True])
def test_the_agent_update_follow_up_completes(quarantined: tuple[Device, SimpleNamespace], full: bool) -> None:
    device, entry = quarantined
    status = asyncio.run(async_restore_qml_patches_after_update(entry, apply_full_patch=full))
    assert display_activation_confirmed(status)
    expected = ["apply", "reload"] if full else ["core-apply", "reload"]
    assert entry.runtime_data.api.calls[:2] == expected


def test_a_display_that_fails_again_stays_reported_as_failed(
    quarantined: tuple[Device, SimpleNamespace],
) -> None:
    device, entry = quarantined
    api = entry.runtime_data.api
    original = api._run

    def failing_again(action: str, **env: str) -> dict[str, Any]:
        result = original(action, **env)
        if action != "status":
            Path(f"{device.rcc}.failed").write_text("boot-1\n")
            result = original("status")
        return result

    api._run = failing_again
    with pytest.raises(C300XAgentApiError):
        asyncio.run(async_apply_qml_core_patch_and_confirm(entry))
    assert device.ok("reload", **api.env)["qt5_overlay"] == "failed"
