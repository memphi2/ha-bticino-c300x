"""A Qt 5 display the agent does not know: the agent runs on without the display pages.

The Home Assistant helpers run against the real qml_patch.sh on a fixture of
firmware 3.0.x whose display program matches no known build. The script leaves
the display as shipped and reports why; the agent update follow-up completes,
the core Repair names the reason and a settings save does not ask again.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x._api_normalize import normalize_qml_patch_status
from custom_components.bticino_c300x.api_errors import C300XAgentApiError
from custom_components.bticino_c300x.config_flow_qml import qml_patch_status_label
from custom_components.bticino_c300x.display_activation import display_unsupported
from custom_components.bticino_c300x.display_patch_sync import _differs
from custom_components.bticino_c300x.entry_locks import clear_entry_locks
from custom_components.bticino_c300x.qml_patch import (
    async_apply_qml_core_patch_and_confirm,
    async_restore_qml_patches_after_update,
)
from tests.test_qml_patch_qt5_overlay import Device
from tests.test_qml_patch_qt5_overlay import programs as programs
from tests.test_qt5_quarantine_cascade import _ScriptApi


@pytest.fixture
def unknown(tmp_path: Path, programs: dict[str, Path]) -> Iterator[tuple[Device, SimpleNamespace]]:
    clear_entry_locks("entry-1")
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "pidof").write_text("#!/bin/sh\necho 4242\n")
    (tools / "pidof").chmod(0o755)
    (tmp_path / "device").mkdir()
    device = Device(tmp_path / "device", programs)
    device.program = tmp_path / "BtClass-unknown"
    device.program.write_bytes(b"\x7fELF a later build")
    api = _ScriptApi(device, {"PATH": f"{tools}:{os.environ['PATH']}"})
    entry = SimpleNamespace(
        entry_id="entry-1", data={}, options={},
        runtime_data=SimpleNamespace(api=api, qml_patch_status={}, qml_patch_status_updated_at=None),
    )
    yield device, entry
    clear_entry_locks("entry-1")


@pytest.mark.parametrize("full", [False, True])
def test_the_agent_update_follow_up_completes_without_the_display_pages(
    unknown: tuple[Device, SimpleNamespace], full: bool,
) -> None:
    device, entry = unknown
    status = asyncio.run(async_restore_qml_patches_after_update(entry, apply_full_patch=full))
    assert display_unsupported(status) == "display_program_unknown"
    assert entry.runtime_data.api.calls == ["core-apply"]
    assert not device.rcc.exists()
    assert device.wrapper.read_text().startswith("#!/bin/sh\n") and "c300x" not in device.wrapper.read_text()


def test_the_core_repair_names_the_reason(unknown: tuple[Device, SimpleNamespace]) -> None:
    _device, entry = unknown
    with pytest.raises(C300XAgentApiError, match="display_program_unknown"):
        asyncio.run(async_apply_qml_core_patch_and_confirm(entry))
    stored = entry.runtime_data.qml_patch_status
    assert display_unsupported(stored) == "display_program_unknown"
    assert qml_patch_status_label(stored) == "display_unsupported"


@pytest.mark.parametrize("wanted", [False, True])
def test_a_settings_save_does_not_ask_the_unknown_display_again(
    unknown: tuple[Device, SimpleNamespace], wanted: bool,
) -> None:
    device, entry = unknown
    entry.runtime_data.api._run("core-apply")
    status = normalize_qml_patch_status(device.ok("status", **entry.runtime_data.api.env))
    assert status["qt5_unsupported"] == "display_program_unknown"
    assert _differs(status, wanted, "stock") is None
