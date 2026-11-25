"""The display follow-up of an agent update survives a lost apply answer.

The station applies an update by itself once it has the files. Home Assistant
re-applies an active Display patch afterwards; when it stops between the two,
the entry data must still say that this is due.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from test_agent_update_repairs import (
    FakeEntry,
    FakeHass,
    FakePatchApi,
    FakeRuntimeData,
    FakeSelfUpdateState,
)

from custom_components.bticino_c300x import repairs
from custom_components.bticino_c300x.agent_update import compare_agent_bundle
from custom_components.bticino_c300x.api_errors import (
    C300XAgentApiConnectionError,
    C300XAgentUpdateError,
)
from custom_components.bticino_c300x.const import CONF_AGENT_UPDATE_QML_PENDING

BUNDLE = {"agent_version": "1.1.0", "bundle_hash": "sha256:new"}
NEW_AGENT = {
    "version": "1.1.0", "capabilities": {},
    "agent": {"self_update_supported": True, "bundle_hash": "sha256:new"},
}


class _HomeAssistantStopped(BaseException):
    """Home Assistant ends while the step waits for the station."""


class _UpdatedStation(FakePatchApi):
    """Reports the Display patch as active and, once asked, the new agent."""

    async def async_validate_setup(self) -> dict[str, Any]:
        return NEW_AGENT


def _entry(data: dict[str, Any] | None = None) -> FakeEntry:
    entry = FakeEntry(runtime_data=FakeRuntimeData(_UpdatedStation()), data=dict(data or {}))
    entry.runtime_data.agent_update_state = FakeSelfUpdateState()
    return entry


def _flow(entry: FakeEntry) -> repairs.DeviceAgentUpdateRepairFlow:
    flow = repairs.DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]
    return flow


@pytest.fixture
def station(monkeypatch) -> dict[str, Any]:
    """What the station answers to the apply, and the display writes it gets."""

    station: dict[str, Any] = {"answer": {"ok": True, "qml_patch_changed": False}, "display": []}

    async def apply_update(_hass: Any, _api: Any) -> dict[str, Any]:
        answer = station["answer"]
        if isinstance(answer, BaseException):
            raise answer
        return dict(answer)

    async def verify(_hass: Any, _api: Any, _result: Any) -> dict[str, Any]:
        return NEW_AGENT

    async def restore_display(_entry: Any, *, apply_full_patch: bool) -> None:
        station["display"].append(apply_full_patch)

    async def migrate_mqtt(_api: Any) -> None:
        return None

    async def bundle(_hass: Any) -> dict[str, Any]:
        return BUNDLE

    monkeypatch.setattr(repairs, "async_apply_packaged_agent_update", apply_update)
    monkeypatch.setattr(repairs, "_async_verify_agent_after_update", verify)
    monkeypatch.setattr(repairs, "async_restore_qml_patches_after_update", restore_display)
    monkeypatch.setattr(repairs, "_async_migrate_mqtt_after_update", migrate_mqtt)
    monkeypatch.setattr(repairs, "async_load_packaged_bundle_metadata", bundle)
    monkeypatch.setattr(repairs, "async_dispatcher_send", lambda *_: None)
    monkeypatch.setattr(repairs.ir, "async_delete_issue", lambda **_: None)
    return station


def _state_at_setup(entry: FakeEntry) -> Any:
    # As RuntimeManager.async_validate_agent compares at every setup.
    return compare_agent_bundle(
        NEW_AGENT, BUNDLE, qml_patch_pending=CONF_AGENT_UPDATE_QML_PENDING in entry.data,
    )


def test_restart_after_the_stations_apply_still_reapplies_the_display(station) -> None:
    first = _entry()
    station["answer"] = _HomeAssistantStopped()
    with pytest.raises(_HomeAssistantStopped):
        asyncio.run(_flow(first).async_step_confirm({}))
    assert station["display"] == []

    # Home Assistant starts again with the stored entry data and the new agent.
    restarted = _entry(first.data)
    state = _state_at_setup(restarted)
    assert state.update_required
    assert state.reason == "qml_patch_pending"
    assert state.self_update_repair_supported

    # The station has the bundle already and changes no file this time.
    station["answer"] = {"ok": True, "qml_patch_changed": False}
    result = asyncio.run(_flow(restarted).async_step_confirm({}))

    assert result == {"type": "create_entry", "data": {}}
    assert station["display"] == [True]
    assert CONF_AGENT_UPDATE_QML_PENDING not in restarted.data
    assert not _state_at_setup(restarted).update_required


def test_update_without_display_changes_does_not_rewrite_the_display(station) -> None:
    entry = _entry()

    result = asyncio.run(_flow(entry).async_step_confirm({}))

    assert result == {"type": "create_entry", "data": {}}
    assert station["display"] == []
    assert CONF_AGENT_UPDATE_QML_PENDING not in entry.data


def test_update_with_display_changes_reapplies_once(station) -> None:
    entry = _entry()
    station["answer"] = {"ok": True, "qml_patch_changed": True}

    result = asyncio.run(_flow(entry).async_step_confirm({}))

    assert result == {"type": "create_entry", "data": {}}
    assert station["display"] == [True]
    assert CONF_AGENT_UPDATE_QML_PENDING not in entry.data


def test_lost_answer_leaves_a_repair_that_the_retry_clears(station) -> None:
    entry = _entry()
    flow = _flow(entry)
    lost = C300XAgentApiConnectionError("device-agent request timed out")
    lost.__cause__ = TimeoutError()
    station["answer"] = lost

    failed = asyncio.run(flow.async_step_confirm({}))

    assert failed["errors"] == {"base": "update_failed"}
    # Whether the station applied the update is not known: the note stays.
    assert entry.data[CONF_AGENT_UPDATE_QML_PENDING] is True

    station["answer"] = {"ok": True, "qml_patch_changed": False}
    result = asyncio.run(flow.async_step_confirm({}))

    assert result == {"type": "create_entry", "data": {}}
    assert station["display"] == [True]
    assert CONF_AGENT_UPDATE_QML_PENDING not in entry.data
    assert not _state_at_setup(entry).update_required


@pytest.mark.parametrize("refusal", [
    C300XAgentUpdateError("refused", status=409, code="update_root_already_writable"),
    C300XAgentApiConnectionError("device agent returned HTTP 500: write_failed"),
    RuntimeError("packaged native-agent bundle is missing"),
])
def test_refused_update_leaves_no_note(station, refusal) -> None:
    entry = _entry()
    station["answer"] = refusal

    failed = asyncio.run(_flow(entry).async_step_confirm({}))

    assert failed["type"] == "form"
    assert entry.data == {}
    assert station["display"] == []


def test_refused_update_keeps_the_note_of_an_earlier_run(station) -> None:
    entry = _entry({CONF_AGENT_UPDATE_QML_PENDING: True})
    station["answer"] = RuntimeError("upload refused")

    asyncio.run(_flow(entry).async_step_confirm({}))

    assert entry.data[CONF_AGENT_UPDATE_QML_PENDING] is True
