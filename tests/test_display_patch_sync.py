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


def _entry(setting: bool | None, capabilities: dict[str, Any] = _ADVERTISED) -> Any:
    options = {} if setting is None else {CONF_DEVICE_UI_ENABLED: setting}
    return SimpleNamespace(
        entry_id="entry-1", data={}, options=options,
        runtime_data=SimpleNamespace(capabilities=capabilities, qml_patch_status={}),
    )


def _device(monkeypatch: pytest.MonkeyPatch, patched: Any, *, fail: bool = False) -> list[str]:
    calls: list[str] = []

    async def status(_entry: Any) -> dict[str, Any]:
        if fail:
            raise C300XAgentApiError("unreachable")
        return {"patched": patched}

    def action(name: str, after: bool):
        async def run(_entry: Any, _changed: Any) -> dict[str, Any]:
            calls.append(name)
            return {"patched": after}

        return run

    monkeypatch.setattr(display_patch_sync, "async_refresh_qml_patch_status", status)
    monkeypatch.setattr(display_patch_sync, "async_apply_qml_patch_and_confirm", action("apply", True))
    monkeypatch.setattr(display_patch_sync, "async_restore_qml_patch_and_confirm", action("restore", False))
    return calls


def _apply(entry: Any) -> bool:
    return asyncio.run(display_patch_sync.async_apply_display_setting(SimpleNamespace(), entry))


@pytest.mark.parametrize(
    ("setting", "patched", "expected"),
    [(True, False, ["apply"]), (False, True, ["restore"]), (True, True, []), (False, False, [])],
)
def test_the_device_follows_the_display_setting(monkeypatch, setting, patched, expected):
    calls = _device(monkeypatch, patched)
    assert _apply(_entry(setting)) is bool(expected)
    assert calls == expected


@pytest.mark.parametrize("patched", [None, "patching"])
def test_an_unknown_patch_state_is_left_alone(monkeypatch, patched):
    calls = _device(monkeypatch, patched)
    assert _apply(_entry(True)) is False
    assert calls == []


def test_without_a_setting_or_the_agent_action_nothing_happens(monkeypatch):
    calls = _device(monkeypatch, False)
    assert _apply(_entry(None)) is False
    assert _apply(_entry(True, {"maintenance": {"supported": True, "qml_patch": False}})) is False
    assert calls == []


def test_an_unreachable_agent_is_only_logged(monkeypatch):
    calls = _device(monkeypatch, False, fail=True)
    assert _apply(_entry(True)) is False
    assert calls == []


def _listener_run(monkeypatch, applied: bool) -> list[str]:
    calls: list[str] = []

    async def apply_setting(_hass: Any, _entry: Any) -> bool:
        calls.append("display")
        return applied

    async def home_page(_entry: Any, **_kwargs: Any) -> None:
        calls.append("home_page")

    async def reload(entry_id: str) -> None:
        calls.append("reload")

    monkeypatch.setattr(runtime_manager, "async_apply_display_setting", apply_setting)
    monkeypatch.setattr(runtime_manager, "_async_reapply_display_patch_for_home_page", home_page)
    entry = SimpleNamespace(entry_id="entry-1", data={}, options={})
    listener = runtime_manager._entry_update_listener(entry)
    entry.options[CONF_DEVICE_UI_ENABLED] = True
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_reload=reload))
    asyncio.run(listener(hass, entry))
    return calls


def test_saving_the_settings_applies_the_display_setting_before_the_reload(monkeypatch):
    # The patch it applies carries the home page mode already.
    assert _listener_run(monkeypatch, True) == ["display", "reload"]
    assert _listener_run(monkeypatch, False) == ["display", "home_page", "reload"]


def test_a_new_entry_applies_its_display_setting_once_at_the_first_start(monkeypatch):
    seen: list[Any] = []

    async def apply_setting(_hass: Any, entry: Any) -> bool:
        seen.append(entry)
        return True

    async def nothing(*_args: Any) -> Any:
        return None

    updates: list[dict[str, Any]] = []

    def update_entry(entry: Any, *, data: dict[str, Any]) -> None:
        updates.append(data)
        entry.data = data

    monkeypatch.setattr(runtime_manager, "async_apply_display_setting", apply_setting)
    for name in ("_async_track_display_updates", "_async_configure_display_bridge",
                 "_async_sync_device_user", "_async_refresh_self_test"):
        monkeypatch.setattr(runtime_manager, name, nothing)
    entry = SimpleNamespace(
        data={CONF_DISPLAY_SETTING_PENDING: True, "agent_host": "a"},
        runtime_data=SimpleNamespace(resources=SimpleNamespace()),
    )
    manager = SimpleNamespace(
        hass=SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update_entry)),
        entry=entry, connection_state=SimpleNamespace(available=True),
        _platform_gate_state_loaded=True, _api=lambda: object(),
    )
    sync = runtime_manager.C300XRuntimeManager.async_sync_device_state
    asyncio.run(sync(manager))
    assert seen == [entry]
    assert updates == [{"agent_host": "a"}]
    # A plain restart changes nothing on the device.
    asyncio.run(sync(manager))
    assert seen == [entry]


def test_the_display_settings_submitted_as_they_are_still_reach_the_device(monkeypatch):
    from test_display_settings import _OptionsAreas
    from test_executor import run

    from custom_components.bticino_c300x import config_flow

    scheduled: list[Any] = []
    monkeypatch.setattr(
        config_flow, "async_schedule_display_setting", lambda _hass, entry: scheduled.append(entry)
    )
    entry = SimpleNamespace(
        entry_id="display", data={CONF_DEVICE_UI_ENABLED: False},
        options={}, runtime_data=None, update_listeners=[],
    )
    areas = _OptionsAreas(entry)
    # A change is saved; the reload that follows it brings the device in line.
    result = run(areas._flow().async_step_dashboard({CONF_DEVICE_UI_ENABLED: True}))
    assert result["type"] == "menu"
    assert entry.options[CONF_DEVICE_UI_ENABLED] is True
    assert scheduled == []
    # The same again saves nothing and reloads nothing, so it is applied here.
    result = run(areas._flow().async_step_dashboard({CONF_DEVICE_UI_ENABLED: True}))
    assert result["type"] == "menu"
    assert scheduled == [entry]


def test_scheduling_runs_the_apply_as_a_task_of_the_entry(monkeypatch):
    calls = _device(monkeypatch, False)
    entry = _entry(True)
    tasks: list[Any] = []
    entry.async_create_background_task = lambda _hass, coro, _name: tasks.append(coro)
    display_patch_sync.async_schedule_display_setting(SimpleNamespace(), entry)
    monkeypatch.setattr(display_patch_sync, "async_dispatcher_send", lambda *_args: None)
    asyncio.run(tasks[0])
    assert calls == ["apply"]
    # An entry that is not loaded has no device to talk to.
    entry.runtime_data = None
    display_patch_sync.async_schedule_display_setting(SimpleNamespace(), entry)
    assert len(tasks) == 1
