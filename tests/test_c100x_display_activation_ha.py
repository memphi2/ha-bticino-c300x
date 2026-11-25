"""Home Assistant side of the C100X display activation: API, buttons, tracker, repair."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_api import HEADER_MAINTENANCE_TOKEN, C300XAgentApi, _FakeSession
from test_button import _FakeEntry, _FakeHass, _FakeRuntimeData

from custom_components.bticino_c300x import c100x_display_activation as tracker
from custom_components.bticino_c300x import display_patch_sync
from custom_components.bticino_c300x.api_errors import C300XAgentApiError
from custom_components.bticino_c300x.button import (
    C300XActivateDisplayPagesButton,
    C300XRestoreDisplayPagesButton,
    async_setup_entry,
)
from custom_components.bticino_c300x.const import CONF_DEVICE_UI_ENABLED
from custom_components.bticino_c300x.repair_issues import ALL_REPAIR_ISSUES

ROUTE = "http://agent.local:8080/api/v1/maintenance/c100x-display"


def status(**updates: Any) -> dict[str, Any]:
    return {"supported": True, "status_known": True, "busy": False, "phase": "stock",
            "confirmed": False, "last_result": "", "reboot_pending": False,
            "activate": True, "restore": False, "alert_sound": False, **updates}


@pytest.mark.parametrize("method,path,confirm", [
    ("async_c100x_display_activate", "/actions/activate", "activate_c100x_display"),
    ("async_c100x_display_restore", "/actions/restore", "restore_c100x_display"),
])
def test_actions_send_the_maintenance_token_and_their_confirmation(method, path, confirm) -> None:
    session = _FakeSession('{"ok": true, "scheduled": true}')
    api = C300XAgentApi(session, "http://agent.local:8080", "agent-token",  # type: ignore[arg-type]
                        maintenance_token="maintenance-token")
    assert asyncio.run(getattr(api, method)()) == {"ok": True, "scheduled": True}
    request = session.requests[0]
    assert request["args"] == ("POST", ROUTE + path)
    assert request["kwargs"]["headers"][HEADER_MAINTENANCE_TOKEN] == "maintenance-token"
    assert request["kwargs"]["json"] == {"confirm": confirm}


def test_status_is_read_with_the_maintenance_token() -> None:
    session = _FakeSession('{"ok": true, "c100x_display": {"supported": true}}')
    api = C300XAgentApi(session, "http://agent.local:8080", "agent-token",  # type: ignore[arg-type]
                        maintenance_token="maintenance-token")
    assert asyncio.run(api.async_c100x_display_status())["c100x_display"] == {"supported": True}
    assert session.requests[0]["args"] == ("GET", ROUTE)
    with pytest.raises(C300XAgentApiError):
        bad = C300XAgentApi(_FakeSession('{"ok": true}'), "http://agent.local:8080",  # type: ignore[arg-type]
                            "agent-token", maintenance_token="maintenance-token")
        asyncio.run(bad.async_c100x_display_status())


def buttons(capabilities: dict[str, Any]) -> list[Any]:
    entities: list[Any] = []
    entry = _FakeEntry(title="C100X", runtime_data=_FakeRuntimeData(capabilities=capabilities))
    asyncio.run(async_setup_entry(_FakeHass(), entry, entities.extend))  # type: ignore[arg-type]
    return [e for e in entities
            if isinstance(e, (C300XActivateDisplayPagesButton, C300XRestoreDisplayPagesButton))]


def test_buttons_only_with_the_c100x_activation() -> None:
    assert buttons({}) == []
    assert buttons({"c100x_display": {"supported": False}}) == []
    activate, restore = buttons({"c100x_display": status()})
    assert activate.translation_key == "activate_display_pages"
    assert restore.translation_key == "restore_display_pages"


def test_buttons_follow_the_offered_action_and_start_the_tracker(monkeypatch) -> None:
    activate, restore = buttons({"c100x_display": status()})
    for button in (activate, restore):
        monkeypatch.setattr(type(button).__mro__[2], "available", property(lambda self: True))
    assert activate.available and not restore.available
    activate._entry.runtime_data.capabilities["c100x_display"] = status(activate=False, restore=True)
    assert not activate.available and restore.available

    followed: list[Any] = []
    monkeypatch.setattr("custom_components.bticino_c300x.button.async_follow_c100x_display",
                        lambda hass, entry: followed.append(entry))
    api = SimpleNamespace(async_c100x_display_activate=AsyncMock(return_value={"ok": True}),
                          async_c100x_display_restore=AsyncMock(side_effect=C300XAgentApiError("busy")))
    activate._entry.runtime_data.api = restore._entry.runtime_data.api = api
    activate.hass = restore.hass = _FakeHass()
    asyncio.run(activate.async_press())
    api.async_c100x_display_activate.assert_awaited_once()
    assert followed == [activate._entry]
    with pytest.raises(HomeAssistantError, match="restore"):
        asyncio.run(restore.async_press())
    assert followed == [activate._entry]


class _Hass:
    def __init__(self) -> None:
        self.reloads: list[str] = []
        self.config_entries = SimpleNamespace(async_schedule_reload=self.reloads.append)

    def async_create_background_task(self, coro: Any, name: str) -> asyncio.Task[Any]:
        return asyncio.get_running_loop().create_task(coro, name=name)


def tracked_entry(start: dict[str, Any], replies: list[Any]) -> Any:
    async def read() -> dict[str, Any]:
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {"ok": True, "c100x_display": reply}

    return _FakeEntry(title="C100X", runtime_data=_FakeRuntimeData(
        capabilities={"c100x_display": start},
        api=SimpleNamespace(async_c100x_display_status=read),  # type: ignore[arg-type]
    ))


def follow(monkeypatch, entry: Any) -> tuple[_Hass, list[tuple[str, Any]]]:
    issues: list[tuple[str, Any]] = []
    monkeypatch.setattr(tracker, "POLL_SECONDS", 0)
    monkeypatch.setattr(tracker.ir, "async_create_issue", lambda *a, **kw: issues.append(("create", kw)))
    monkeypatch.setattr(tracker.ir, "async_delete_issue", lambda *a, **kw: issues.append(("delete", a[2])))
    hass = _Hass()

    async def run() -> None:
        tracker.async_follow_c100x_display(hass, entry)  # type: ignore[arg-type]
        task = entry.runtime_data.resources.c100x_display_task
        tracker.async_follow_c100x_display(hass, entry)  # type: ignore[arg-type]
        assert entry.runtime_data.resources.c100x_display_task is task  # once per entry
        await task

    asyncio.run(run())
    return hass, issues


def test_tracker_waits_through_the_reboot_and_reloads_once(monkeypatch) -> None:
    entry = tracked_entry(status(), [
        status(phase="prepared", busy=True), status(phase="prepared", reboot_pending=True),
        C300XAgentApiError("rebooting"), status(phase="trial"),
        status(phase="installed", confirmed=True, last_result="confirmed"),
    ])
    hass, issues = follow(monkeypatch, entry)
    assert hass.reloads == [entry.entry_id]
    assert all(kind == "delete" for kind, _ in issues)
    assert entry.runtime_data.capabilities["c100x_display"]["confirmed"] is True


def test_tracker_shows_a_rollback_and_stops_without_change(monkeypatch) -> None:
    entry = tracked_entry(status(phase="trial"), [status(phase="stock", last_result="rolled_back")])
    hass, issues = follow(monkeypatch, entry)
    assert hass.reloads == [entry.entry_id]
    issue, = [issue for kind, issue in issues if kind == "create"]
    assert issue["translation_key"] == "c100x_display_rolled_back"
    assert "c100x_display_rolled_back" in ALL_REPAIR_ISSUES
    entry = tracked_entry(status(), [status()])
    hass, _ = follow(monkeypatch, entry)
    assert hass.reloads == []


@pytest.mark.parametrize("reason", ["payload_unavailable", "boot_check_failed"])
def test_a_failed_boot_check_is_a_repair_until_the_agent_clears_it(monkeypatch, reason) -> None:
    issues: list[tuple[str, Any]] = []
    monkeypatch.setattr(tracker.ir, "async_create_issue", lambda *a, **kw: issues.append(("create", a[2], kw)))
    monkeypatch.setattr(tracker.ir, "async_delete_issue", lambda *a, **kw: issues.append(("delete", a[2], {})))
    monkeypatch.setattr(tracker, "async_follow_c100x_display", lambda hass, entry: None)
    entry = _FakeEntry(title="C100X", runtime_data=_FakeRuntimeData(
        capabilities={"c100x_display": status(status_known=False, activate=False, boot_check=reason)}))
    tracker.async_follow_c100x_display_if_open(None, entry)  # type: ignore[arg-type]
    created = [kw for kind, _, kw in issues if kind == "create"]
    assert [kw["translation_key"] for kw in created] == ["c100x_display_boot_check_failed"]
    assert created[0]["translation_placeholders"]["entry_title"] == "C100X"
    assert "c100x_display_boot_check_failed" in ALL_REPAIR_ISSUES
    issues.clear()
    entry.runtime_data.capabilities["c100x_display"] = status(boot_check="")
    tracker.async_follow_c100x_display_if_open(None, entry)  # type: ignore[arg-type]
    assert ("delete", f"c100x_display_boot_check_failed_{entry.entry_id}", {}) in issues


def test_tracker_is_cancelled_with_the_entry(monkeypatch) -> None:
    monkeypatch.setattr(tracker, "POLL_SECONDS", 3600)
    entry = tracked_entry(status(phase="prepared"), [])

    async def run() -> None:
        tracker.async_follow_c100x_display(_Hass(), entry)  # type: ignore[arg-type]
        task = entry.runtime_data.resources.c100x_display_task
        entry.runtime_data.resources.close()
        with pytest.raises(asyncio.CancelledError):
            await task
        tracker.async_follow_c100x_display(_Hass(), entry)  # type: ignore[arg-type]
        assert entry.runtime_data.resources.c100x_display_task is None

    asyncio.run(run())


def test_start_follows_only_an_open_activation(monkeypatch) -> None:
    followed: list[Any] = []
    monkeypatch.setattr(tracker, "async_follow_c100x_display", lambda hass, entry: followed.append(entry))
    monkeypatch.setattr(tracker, "async_sync_c100x_display_issues", lambda *a: None)
    for start, expected in ((status(), 0), (status(phase="trial"), 1), (status(status_known=False), 2),
                            (status(phase="stock", reboot_pending=True), 3)):
        entry = _FakeEntry(runtime_data=_FakeRuntimeData(capabilities={"c100x_display": start}))
        tracker.async_follow_c100x_display_if_open(None, entry)  # type: ignore[arg-type]
        assert len(followed) == expected
    tracker.async_follow_c100x_display_if_open(None, _FakeEntry())  # type: ignore[arg-type]
    assert len(followed) == 3


@pytest.mark.parametrize("wanted,confirmed,restored", [
    (False, True, True), (True, True, False), (False, False, False),
])
def test_display_setting_off_restores_a_confirmed_c100x_display(monkeypatch, wanted, confirmed, restored) -> None:
    capabilities = {"display_bridge": {"supported": True},
                    "c100x_display": status(phase="installed", confirmed=confirmed)}
    api = SimpleNamespace(async_c100x_display_restore=AsyncMock(return_value={"ok": True}))
    entry = SimpleNamespace(
        entry_id="c100x", data={}, options=MappingProxyType({CONF_DEVICE_UI_ENABLED: wanted}),
        runtime_data=SimpleNamespace(agent_info={"model": "C100X", "capabilities": capabilities},
                                     capabilities=capabilities, api=api),
    )
    followed: list[Any] = []
    monkeypatch.setattr(display_patch_sync, "async_follow_c100x_display", lambda hass, e: followed.append(e))
    monkeypatch.setattr(display_patch_sync, "entry_display_supported", lambda e: True)
    result = asyncio.run(display_patch_sync.async_apply_display_setting(None, entry))  # type: ignore[arg-type]
    assert result is restored
    assert api.async_c100x_display_restore.await_count == int(restored)
    assert followed == ([entry] if restored else [])


def renew(monkeypatch, start: Any, replies: list[Any], *, refused: bool = False) -> tuple[Any, list[Any], list[float]]:
    entry = tracked_entry(start, replies)
    if start is None:
        entry.runtime_data.capabilities = {}
    activate = AsyncMock(side_effect=C300XAgentApiError("busy") if refused else None)
    entry.runtime_data.api.async_c100x_display_activate = activate
    followed: list[Any] = []
    waits: list[float] = []

    async def wait(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(tracker.asyncio, "sleep", wait)
    monkeypatch.setattr(tracker, "async_follow_c100x_display", lambda hass, entry: followed.append(entry))
    asyncio.run(tracker.async_renew_c100x_display_after_update(_Hass(), entry))  # type: ignore[arg-type]
    return activate, followed, waits


def test_update_renews_confirmed_pages_once_the_agent_has_read_the_new_adapter(monkeypatch) -> None:
    current = status(phase="installed", confirmed=True, activate=False, restore=True)
    activate, followed, waits = renew(monkeypatch, current, [
        C300XAgentApiError("restarting"), status(status_known=False, activate=False),
        {**current, "busy": True}, {**current, "activate": True, "available": "b" * 64},
    ])
    activate.assert_awaited_once()
    assert len(followed) == 1 and waits == [tracker.UPDATE_POLL_SECONDS] * 3


@pytest.mark.parametrize("reply", [
    status(phase="installed", confirmed=True, activate=False, restore=True),
    status(phase="stock", confirmed=False, activate=True),
    status(phase="prepared", confirmed=False, activate=False),
])
def test_update_leaves_current_pages_an_original_display_and_an_open_trial_alone(monkeypatch, reply) -> None:
    activate, followed, _ = renew(monkeypatch, status(), [reply])
    activate.assert_not_awaited()
    assert followed == []


def test_update_asks_no_c300x_and_gives_up_on_a_silent_or_refusing_station(monkeypatch) -> None:
    replies: list[Any] = [status()]
    activate, followed, _ = renew(monkeypatch, None, replies)
    assert replies and not activate.await_count and followed == []
    silent: list[Any] = [C300XAgentApiError("down")] * tracker.UPDATE_POLLS
    activate, followed, waits = renew(monkeypatch, status(), silent)
    assert not silent and not activate.await_count and len(waits) == tracker.UPDATE_POLLS - 1
    offered = status(phase="installed", confirmed=True, activate=True, restore=True)
    activate, followed, _ = renew(monkeypatch, offered, [offered], refused=True)
    activate.assert_awaited_once()
    assert followed == []


def test_both_update_paths_renew_the_c100x_pages_after_the_display_follow_up() -> None:
    source = (Path(__file__).resolve().parents[1] / "custom_components/bticino_c300x/repairs.py").read_text(
        encoding="utf-8")
    settled = "_settle_display_followup(self.hass, entry, display, full=display_full)\n"
    renewed = "            await async_renew_c100x_display_after_update(self.hass, entry)\n"
    assert source.count(settled) == source.count(settled + renewed) == 2
