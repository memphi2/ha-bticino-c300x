"""Applying the settings applies the Display setting to the device."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from custom_components.bticino_c300x import (
    display_patch_sync,
    qml_patch,
    runtime_manager,
)
from custom_components.bticino_c300x.api import C300XAgentApi, C300XAgentApiError
from custom_components.bticino_c300x.const import (
    CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
    CONF_DEVICE_UI_ENABLED,
    CONF_DISPLAY_SETTING_PENDING,
)

_ADVERTISED = {"maintenance": {"supported": True, "qml_patch": True, "qml_restore": True}}


def _entry(setting: bool | None, capabilities: dict[str, Any] | None = None, data: dict | None = None) -> Any:
    options = {} if setting is None else {CONF_DEVICE_UI_ENABLED: setting}
    return SimpleNamespace(
        entry_id="entry-1", data=dict(data or {}), options=options,
        runtime_data=SimpleNamespace(
            capabilities=_ADVERTISED if capabilities is None else capabilities, qml_patch_status={}
        ),
    )


def _device(
    monkeypatch: pytest.MonkeyPatch, status: dict[str, Any], *, fail: bool = False, follows: bool = True,
    home_buttons: str | None = None,
) -> list[str]:
    calls: list[str] = []

    async def read(_entry: Any, *, wait_busy: bool = False) -> dict[str, Any]:
        assert wait_busy, "a status read waits out a running maintenance job"
        if fail:
            raise C300XAgentApiError("unreachable")
        return status

    def action(name: str, after: bool):
        async def run(_entry: Any, _changed: Any) -> dict[str, Any]:
            calls.append(name)
            result: dict[str, Any] = {"patched": after if follows else not after}
            if home_buttons is not None:
                result["home_buttons"] = home_buttons
            return result

        return run

    monkeypatch.setattr(display_patch_sync, "async_refresh_qml_patch_status", read)
    monkeypatch.setattr(display_patch_sync, "async_apply_qml_patch_and_confirm", action("apply", True))
    monkeypatch.setattr(display_patch_sync, "async_restore_qml_patch_and_confirm", action("restore", False))
    return calls


def _apply(entry: Any) -> bool | None:
    return asyncio.run(display_patch_sync.async_apply_display_setting(SimpleNamespace(), entry))


@pytest.mark.parametrize(
    ("setting", "status", "expected", "result"),
    [
        (True, {"patched": False}, ["apply"], True),
        (False, {"patched": True}, ["restore"], True),
        (True, {"patched": True}, [], False),
        (False, {"patched": False}, [], False),
        # Only some files there, after a cut-off apply: both ways bring it in line.
        (True, {"state": "partial", "patched": None}, ["apply"], True),
        (False, {"state": "partial", "patched": None}, ["restore"], True),
    ],
)
def test_the_device_follows_the_display_setting(monkeypatch, setting, status, expected, result):
    calls = _device(monkeypatch, status)
    assert _apply(_entry(setting)) is result
    assert calls == expected


def test_a_device_that_says_nothing_or_does_not_follow_stays_to_do(monkeypatch):
    calls = _device(monkeypatch, {"state": "patching"})
    assert _apply(_entry(True)) is None
    assert calls == []
    calls = _device(monkeypatch, {"patched": False}, follows=False)
    assert _apply(_entry(True)) is None
    assert calls == ["apply"]
    calls = _device(monkeypatch, {"patched": False}, fail=True)
    assert _apply(_entry(True)) is None
    assert calls == []
    # Before the agent answered at all there is nothing to judge by.
    assert _apply(_entry(True, capabilities={})) is None


@pytest.mark.parametrize("wanted", [False, True])
def test_quarantined_display_is_neither_confirmed_nor_automatically_retried(monkeypatch, wanted):
    calls = _device(monkeypatch, {"patched": True, "qt5_overlay": "failed", "gui_running": True})
    entry = _entry(wanted, data={CONF_DISPLAY_SETTING_PENDING: True})
    updates = []
    manager = _manager(entry, updates)
    asyncio.run(display_patch_sync.async_settle_display_setting(manager.hass, entry))
    assert calls == []
    assert updates == []
    assert CONF_DISPLAY_SETTING_PENDING in entry.data


@pytest.mark.parametrize("overlay", ["off", "incomplete"])
def test_incomplete_activation_is_repaired_even_with_patched_files(monkeypatch, overlay):
    calls = _device(monkeypatch, {"patched": True, "qt5_overlay": overlay, "gui_running": True})
    assert _apply(_entry(True)) is True
    assert calls == ["apply"]


def test_failed_activation_after_setting_apply_is_not_confirmed(monkeypatch):
    _device(monkeypatch, {"patched": False, "qt5_overlay": "off", "gui_running": True})
    async def failed(*_args):
        return {"patched": True, "qt5_overlay": "failed", "gui_running": True}
    monkeypatch.setattr(display_patch_sync, "async_apply_qml_patch_and_confirm", failed)
    assert _apply(_entry(True)) is None


def test_without_a_setting_or_the_agent_action_nothing_is_to_do(monkeypatch):
    calls = _device(monkeypatch, {"patched": False})
    assert _apply(_entry(None)) is False
    assert _apply(_entry(True, {"maintenance": {"supported": True, "qml_patch": False}})) is False
    assert calls == []


def _manager(entry: Any, updates: list[dict[str, Any]]) -> runtime_manager.C300XRuntimeManager:
    def update_entry(target: Any, *, data: dict[str, Any]) -> None:
        updates.append(data)
        target.data = data

    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update_entry))
    manager = runtime_manager.C300XRuntimeManager(hass, entry)
    manager.api = Mock(spec_set=C300XAgentApi)
    manager._platform_gate_state_loaded = True
    return manager


def _quiet_start(monkeypatch: pytest.MonkeyPatch, entry: Any) -> None:
    async def nothing(*_args: Any) -> Any:
        return None

    for name in ("_async_track_display_updates", "_async_configure_display_bridge",
                 "_async_sync_device_user", "_async_refresh_self_test"):
        monkeypatch.setattr(runtime_manager, name, nothing)
    entry.runtime_data.resources = SimpleNamespace()


def _start(monkeypatch: pytest.MonkeyPatch, entry: Any, results: list[bool | None]) -> list[Any]:
    seen: list[Any] = []

    async def apply_setting(_hass: Any, target: Any) -> bool | None:
        seen.append(target)
        return results.pop(0)

    monkeypatch.setattr(display_patch_sync, "async_apply_display_setting", apply_setting)
    _quiet_start(monkeypatch, entry)
    return seen


def test_a_new_entry_applies_its_display_setting_at_the_first_start(monkeypatch):
    entry = _entry(True, data={CONF_DISPLAY_SETTING_PENDING: True, "agent_host": "a"})
    seen = _start(monkeypatch, entry, [True])
    updates: list[dict[str, Any]] = []
    asyncio.run(_manager(entry, updates).async_sync_device_state())
    assert seen == [entry]
    assert updates == [{"agent_host": "a"}]
    # A plain restart changes nothing on the device.
    asyncio.run(_manager(entry, updates).async_sync_device_state())
    assert seen == [entry]


def test_the_mark_stays_until_the_device_followed(monkeypatch):
    entry = _entry(True, data={CONF_DISPLAY_SETTING_PENDING: True})
    seen = _start(monkeypatch, entry, [None, True])
    updates: list[dict[str, Any]] = []
    asyncio.run(_manager(entry, updates).async_sync_device_state())
    assert entry.data == {CONF_DISPLAY_SETTING_PENDING: True}
    asyncio.run(_manager(entry, updates).async_sync_device_state())
    assert entry.data == {}
    assert seen == [entry, entry]


def test_a_start_cut_off_during_the_apply_keeps_the_mark(monkeypatch):
    entry = _entry(True, data={CONF_DISPLAY_SETTING_PENDING: True})
    _start(monkeypatch, entry, [])

    async def cut_off(_hass: Any, _entry: Any) -> bool | None:
        raise asyncio.CancelledError

    monkeypatch.setattr(display_patch_sync, "async_apply_display_setting", cut_off)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_manager(entry, []).async_sync_device_state())
    assert entry.data == {CONF_DISPLAY_SETTING_PENDING: True}


def _side_by_side_entry() -> Any:
    entry = _entry(True, data={CONF_DISPLAY_SETTING_PENDING: True})
    entry.options[CONF_DASHBOARD_DYNAMIC_HOMEPAGE] = False
    return entry


def test_a_layout_change_whose_reapply_failed_is_applied_at_the_next_start(monkeypatch):
    """Both layouts report patched; only the reported layout shows the device kept the old one."""

    entry = _entry(True, data={CONF_DISPLAY_SETTING_PENDING: True})
    entry.runtime_data.qml_patch_status = {"patched": True}

    async def unreachable(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise C300XAgentApiError("unreachable")

    async def nothing(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(qml_patch, "async_apply_qml_patch_and_confirm", unreachable)
    monkeypatch.setattr(runtime_manager, "_async_update_listener", nothing)
    listener = runtime_manager._entry_update_listener(entry)
    entry.options = {**entry.options, CONF_DASHBOARD_DYNAMIC_HOMEPAGE: False}
    asyncio.run(listener(None, entry))
    assert display_patch_sync.display_setting_pending(entry)

    calls = _device(monkeypatch, {"patched": True, "home_buttons": "stock"}, home_buttons="side_by_side")
    _quiet_start(monkeypatch, entry)
    asyncio.run(_manager(entry, []).async_sync_device_state())
    assert calls == ["apply"]
    assert not display_patch_sync.display_setting_pending(entry)


def test_the_mark_stays_until_the_device_reports_the_wanted_layout(monkeypatch):
    calls = _device(monkeypatch, {"patched": True, "home_buttons": "stock"}, home_buttons="stock")
    assert _apply(_side_by_side_entry()) is None
    assert calls == ["apply"]


def test_a_matching_layout_is_not_applied_again(monkeypatch):
    calls = _device(monkeypatch, {"patched": True, "home_buttons": "side_by_side"})
    assert _apply(_side_by_side_entry()) is False
    assert calls == []


def test_a_qt5_display_follows_the_layout_only_with_a_confirmed_overlay(monkeypatch):
    active = {"patched": True, "qt5_overlay": "active", "gui_running": True}
    calls = _device(monkeypatch, {**active, "home_buttons": "stock"})

    async def applied(*_args: Any) -> dict[str, Any]:
        calls.append("apply")
        return {**active, "home_buttons": "side_by_side"}

    monkeypatch.setattr(display_patch_sync, "async_apply_qml_patch_and_confirm", applied)
    assert _apply(_side_by_side_entry()) is True
    assert calls == ["apply"]
    # A quarantined overlay is not retried for a layout change either.
    calls.clear()
    _device(monkeypatch, {**active, "qt5_overlay": "failed", "home_buttons": "stock"})
    monkeypatch.setattr(display_patch_sync, "async_apply_qml_patch_and_confirm", applied)
    assert _apply(_side_by_side_entry()) is None
    assert calls == []
    # The wanted layout under an overlay that did not come up stays to do.
    async def fell_back(*_args: Any) -> dict[str, Any]:
        return {**active, "qt5_overlay": "failed", "home_buttons": "side_by_side"}

    _device(monkeypatch, {**active, "home_buttons": "stock"})
    monkeypatch.setattr(display_patch_sync, "async_apply_qml_patch_and_confirm", fell_back)
    assert _apply(_side_by_side_entry()) is None


def test_a_status_without_the_layout_is_taken_as_it_is(monkeypatch):
    # An agent that does not name its layout cannot confirm one; asking it
    # again at every start would never end.
    calls = _device(monkeypatch, {"patched": True})
    assert _apply(_side_by_side_entry()) is False
    assert calls == []
    calls = _device(monkeypatch, {"patched": False})
    assert _apply(_side_by_side_entry()) is True
    assert calls == ["apply"]


def test_other_settings_saved_leave_the_device_alone(monkeypatch):
    # An entry from before the setting stored it with the first save of any
    # area, not always as its device has it.
    entry = _entry(False)
    seen = _start(monkeypatch, entry, [True])

    async def nothing(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(runtime_manager, "_async_update_listener", nothing)
    monkeypatch.setattr(runtime_manager, "_async_reapply_display_patch_for_home_page", nothing)
    listener = runtime_manager._entry_update_listener(entry)
    entry.options = {CONF_DEVICE_UI_ENABLED: False, "video_enabled": True}
    asyncio.run(listener(None, entry))
    asyncio.run(_manager(entry, []).async_sync_device_state())
    assert seen == []
    assert entry.data == {}


def test_the_display_settings_submitted_reach_the_device_at_the_start_after_the_reload():
    from test_display_settings import _OptionsAreas
    from test_executor import run

    entry = SimpleNamespace(
        entry_id="display", data={CONF_DEVICE_UI_ENABLED: False},
        options={}, runtime_data=None, update_listeners=[],
    )
    areas = _OptionsAreas(entry)
    # A change is saved and marked; its listener reloads.
    result = run(areas._flow().async_step_dashboard({CONF_DEVICE_UI_ENABLED: True}))
    assert result["type"] == "menu"
    assert entry.options[CONF_DEVICE_UI_ENABLED] is True
    assert display_patch_sync.display_setting_pending(entry)
    reloads = areas.hass.config_entries.async_schedule_reload.call_count
    # The same again saves nothing: it is marked and reloaded here.
    del entry.data[CONF_DISPLAY_SETTING_PENDING]
    result = run(areas._flow().async_step_dashboard({CONF_DEVICE_UI_ENABLED: True}))
    assert result["type"] == "menu"
    assert display_patch_sync.display_setting_pending(entry)
    assert areas.hass.config_entries.async_schedule_reload.call_count == reloads + 1


def test_an_entry_from_before_the_setting_keeps_its_display_on_an_unrelated_save():
    from custom_components.bticino_c300x.config_flow_features import (
        current_feature_options,
    )

    entry = _entry(None)
    entry.runtime_data.qml_patch_status = {"patched": True}
    assert current_feature_options(entry)[CONF_DEVICE_UI_ENABLED] is True
    entry.runtime_data.qml_patch_status = {"patched": False}
    assert current_feature_options(entry)[CONF_DEVICE_UI_ENABLED] is False


_QML_TIMEOUT = '{"ok":false,"available":true,"error":"qml_patch_timeout","rolled_back":true}'


def test_a_write_past_the_agent_deadline_stays_to_do(monkeypatch):
    """The agent's answer to a write it had to stop: the mark stays, the
    status is read again since the stopped write may have changed the
    device, and the next start tries again."""

    from test_api import _QueuedSession

    session = _QueuedSession([
        (200, '{"ok": true, "state": "original", "patched": false}'),
        (504, _QML_TIMEOUT),
        (200, '{"ok": true, "state": "original", "patched": false, "transaction": "pending"}'),
    ])
    entry = _entry(True, data={CONF_DISPLAY_SETTING_PENDING: True})
    entry.runtime_data.api = C300XAgentApi(
        session,  # type: ignore[arg-type]
        "http://agent.local:8080", "agent-token", maintenance_token="maintenance-token",
    )
    monkeypatch.setattr(display_patch_sync, "async_dispatcher_send", lambda *_args: None)
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))
    asyncio.run(display_patch_sync.async_settle_display_setting(hass, entry))  # type: ignore[arg-type]
    assert len(session.requests) == 3
    assert session.requests[1]["args"][1].endswith("/qml-patch/actions/apply")
    assert session.requests[2]["args"][1].endswith("/qml-patch")
    assert entry.data == {CONF_DISPLAY_SETTING_PENDING: True}
    hass.config_entries.async_update_entry.assert_not_called()
    assert entry.runtime_data.qml_patch_status["state"] == "original"
    assert entry.runtime_data.qml_patch_status["transaction"] == "pending"


def test_the_agent_timeout_answer_names_itself():
    from test_api import _FakeSession

    from custom_components.bticino_c300x.api import C300XAgentApiConnectionError

    api = C300XAgentApi(
        _FakeSession(_QML_TIMEOUT, response_status=504),  # type: ignore[arg-type]
        "http://agent.local:8080", "agent-token", maintenance_token="maintenance-token",
    )
    with pytest.raises(C300XAgentApiConnectionError, match="qml_patch_timeout"):
        asyncio.run(api.async_apply_qml_patch(dynamic_homepage=True))


def test_owed_display_steps_are_applied_although_the_old_pages_read_as_patched(monkeypatch):
    calls = _device(monkeypatch, {"patched": True})
    assert _apply(_entry(True, data={"display_followup_pending": True})) is True
    assert calls == ["apply"]


def test_settling_the_setting_clears_owed_display_steps(monkeypatch):
    calls = _device(monkeypatch, {"patched": True})
    entry = _entry(True, data={"display_followup_pending": True, CONF_DISPLAY_SETTING_PENDING: True})
    updates: list[dict[str, Any]] = []

    def update(_entry: Any, *, data: dict[str, Any]) -> None:
        updates.append(data)
        entry.data = data

    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))
    asyncio.run(display_patch_sync.async_settle_display_setting(hass, entry))
    assert calls == ["apply"]
    assert "display_followup_pending" not in entry.data
