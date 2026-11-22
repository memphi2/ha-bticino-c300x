"""Applying the settings applies the Display setting to the device."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x import display_patch_sync, runtime_manager
from custom_components.bticino_c300x.api import C300XAgentApiError
from custom_components.bticino_c300x.const import (
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
    monkeypatch: pytest.MonkeyPatch, status: dict[str, Any], *, fail: bool = False, follows: bool = True
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
            return {"patched": after if follows else not after}

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


def _manager(entry: Any, updates: list[dict[str, Any]]) -> Any:
    def update_entry(target: Any, *, data: dict[str, Any]) -> None:
        updates.append(data)
        target.data = data

    return SimpleNamespace(
        hass=SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update_entry)),
        entry=entry, connection_state=SimpleNamespace(available=True),
        _platform_gate_state_loaded=True, _api=lambda: object(),
    )


def _start(monkeypatch: pytest.MonkeyPatch, entry: Any, results: list[bool | None]) -> list[Any]:
    seen: list[Any] = []

    async def apply_setting(_hass: Any, target: Any) -> bool | None:
        seen.append(target)
        return results.pop(0)

    async def nothing(*_args: Any) -> Any:
        return None

    monkeypatch.setattr(display_patch_sync, "async_apply_display_setting", apply_setting)
    for name in ("_async_track_display_updates", "_async_configure_display_bridge",
                 "_async_sync_device_user", "_async_refresh_self_test"):
        monkeypatch.setattr(runtime_manager, name, nothing)
    entry.runtime_data.resources = SimpleNamespace()
    return seen


def test_a_new_entry_applies_its_display_setting_at_the_first_start(monkeypatch):
    entry = _entry(True, data={CONF_DISPLAY_SETTING_PENDING: True, "agent_host": "a"})
    seen = _start(monkeypatch, entry, [True])
    updates: list[dict[str, Any]] = []
    sync = runtime_manager.C300XRuntimeManager.async_sync_device_state
    asyncio.run(sync(_manager(entry, updates)))
    assert seen == [entry]
    assert updates == [{"agent_host": "a"}]
    # A plain restart changes nothing on the device.
    asyncio.run(sync(_manager(entry, updates)))
    assert seen == [entry]


def test_the_mark_stays_until_the_device_followed(monkeypatch):
    entry = _entry(True, data={CONF_DISPLAY_SETTING_PENDING: True})
    seen = _start(monkeypatch, entry, [None, True])
    updates: list[dict[str, Any]] = []
    sync = runtime_manager.C300XRuntimeManager.async_sync_device_state
    asyncio.run(sync(_manager(entry, updates)))
    assert entry.data == {CONF_DISPLAY_SETTING_PENDING: True}
    asyncio.run(sync(_manager(entry, updates)))
    assert entry.data == {}
    assert seen == [entry, entry]


def test_a_start_cut_off_during_the_apply_keeps_the_mark(monkeypatch):
    entry = _entry(True, data={CONF_DISPLAY_SETTING_PENDING: True})
    _start(monkeypatch, entry, [])

    async def cut_off(_hass: Any, _entry: Any) -> bool | None:
        raise asyncio.CancelledError

    monkeypatch.setattr(display_patch_sync, "async_apply_display_setting", cut_off)
    sync = runtime_manager.C300XRuntimeManager.async_sync_device_state
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(sync(_manager(entry, [])))
    assert entry.data == {CONF_DISPLAY_SETTING_PENDING: True}


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
    asyncio.run(runtime_manager.C300XRuntimeManager.async_sync_device_state(_manager(entry, [])))
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
