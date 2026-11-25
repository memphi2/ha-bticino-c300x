"""Repair steps that write to the station or reload the entry finish their work.

Home Assistant cancels a flow step with the request of a client that
disconnects. Each case drops the request in the middle of the step's work.
"""

from __future__ import annotations

import asyncio
import contextlib
import types
from typing import Any

import pytest
from test_agent_update_repairs import (
    FakeEntry,
    FakeHass,
    FakePatchApi,
    FakeRuntimeData,
)
from test_repair_survives_dropped_request import _ReloadingConfigEntries, _settle

from custom_components.bticino_c300x import repair_work, repairs
from custom_components.bticino_c300x.const import CONF_CALLBACK_BASE_URL
from custom_components.bticino_c300x.repair_issues import (
    DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
    MEDIA_SETUP_REPAIR_REQUIRED_ISSUE,
    UNSUPPORTED_CALLBACK_URL_ISSUE,
    repair_issue_id,
)

CREATED = {"type": "create_entry", "data": {}}
CALLBACK_ISSUE = repair_issue_id(UNSUPPORTED_CALLBACK_URL_ISSUE, "entry-1")
MEDIA_ISSUE = repair_issue_id(MEDIA_SETUP_REPAIR_REQUIRED_ISSUE, "entry-1")
CORE_HOOK_ISSUE = repair_issue_id(DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE, "entry-1")


def _prepare(flow: Any) -> Any:
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}
    flow.async_abort = lambda **kwargs: {"type": "abort", **kwargs}
    return flow


async def _drop(request: asyncio.Task[Any]) -> None:
    """The client disconnects: aiohttp cancels the request handler."""

    request.cancel()
    # A setup that swallows the cancellation lets the step return instead.
    with contextlib.suppress(asyncio.CancelledError):
        await request


@pytest.fixture(autouse=True)
def issue_registry(monkeypatch) -> set[str]:
    """The open issues; a repair that finishes deletes its own."""

    issues: set[str] = set()

    class Registry:
        def async_get_issue(self, _domain: str, issue_id: str) -> Any:
            return issue_id if issue_id in issues else None

    def delete(*, hass: Any, domain: str, issue_id: str) -> None:
        issues.discard(issue_id)

    monkeypatch.setattr(repairs.ir, "async_delete_issue", delete)
    monkeypatch.setattr(repairs.ir, "async_get", lambda _hass: Registry())
    monkeypatch.setattr(repairs, "async_dispatcher_send", lambda *_: None)
    return issues


class _GatedApi(FakePatchApi):
    """A station whose named request is answered only when the gate opens."""

    def __init__(self, gated: str) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.gate = asyncio.Event()
        answer = getattr(self, gated)

        async def held(*args: Any, **kwargs: Any) -> Any:
            self.started.set()
            await self.gate.wait()
            return await answer(*args, **kwargs)

        setattr(self, gated, held)


def _callback_entry(monkeypatch) -> FakeEntry:
    entry = FakeEntry(runtime_data=FakeRuntimeData(FakePatchApi()))
    entry.data = {"agent_host": "192.0.2.60", "agent_port": 8091}
    monkeypatch.setattr(
        "custom_components.bticino_c300x.callback_url._select_non_link_local_source_ip",
        lambda *_args: "192.0.2.10",
    )
    return entry


URL = {CONF_CALLBACK_BASE_URL: "http://192.0.2.10:8123"}


def test_callback_url_repair_finishes_its_reload(monkeypatch) -> None:
    async def scenario() -> None:
        entry = _callback_entry(monkeypatch)
        hass = FakeHass(entry)
        gate = asyncio.Event()
        hass.config_entries = _ReloadingConfigEntries(entry, gate)
        flow = _prepare(repairs.CallbackUrlRepairFlow(hass, "entry-1"))

        request = asyncio.create_task(flow.async_step_configure(URL))
        await hass.config_entries.reload_started.wait()
        await _drop(request)
        gate.set()
        await _settle()

        assert entry.options == URL
        assert hass.config_entries.state == "loaded"
        # The client asks again: the result it missed, no second reload.
        assert await flow.async_step_configure(URL) == CREATED
        assert hass.config_entries.reloads == ["entry-1"]

    asyncio.run(scenario())


def test_second_flow_waits_for_the_running_repair(monkeypatch, issue_registry) -> None:
    async def scenario() -> None:
        entry = _callback_entry(monkeypatch)
        hass = FakeHass(entry)
        gate = asyncio.Event()
        hass.config_entries = _ReloadingConfigEntries(entry, gate)
        issue_registry.add(CALLBACK_ISSUE)
        first = _prepare(repairs.CallbackUrlRepairFlow(hass, "entry-1"))
        second = _prepare(repairs.CallbackUrlRepairFlow(hass, "entry-1"))

        request = asyncio.create_task(first.async_step_configure(URL))
        await hass.config_entries.reload_started.wait()
        await _drop(request)
        other = asyncio.create_task(second.async_step_configure(URL))
        await _settle()
        assert not other.done()
        gate.set()

        assert await other == CREATED
        assert hass.config_entries.reloads == ["entry-1"]
        assert hass.config_entries.state == "loaded"

    asyncio.run(scenario())


def test_second_flow_shows_its_form_when_the_issue_is_still_open(
    monkeypatch, issue_registry,
) -> None:
    async def scenario() -> None:
        entry = _callback_entry(monkeypatch)
        hass = FakeHass(entry)
        hass.config_entries = _ReloadingConfigEntries(entry)
        flow = _prepare(repairs.CallbackUrlRepairFlow(hass, "entry-1"))
        issue_registry.add(CALLBACK_ISSUE)
        release = asyncio.Event()

        async def other_work() -> None:
            await release.wait()

        other = asyncio.create_task(other_work())
        hass.data[repair_work._RUNNING] = {"entry-1": other}
        request = asyncio.create_task(flow.async_step_configure(URL))
        await _settle()
        assert not request.done()
        release.set()

        result = await request
        assert result["type"] == "form"
        assert result["step_id"] == "configure"
        assert hass.config_entries.reloads == []

    asyncio.run(scenario())


def test_core_hook_repair_finishes_after_the_station_write(issue_registry) -> None:
    async def scenario() -> None:
        api = _GatedApi("async_apply_qml_core_patch")
        api.qml_status = {"available": True, "core_patched": True, "core_state": "patched"}
        runtime = FakeRuntimeData(api)
        runtime.capabilities = {"maintenance": {"supported": True, "qml_core_patch": True}}
        marked: list[Any] = []
        runtime.diagnostics = types.SimpleNamespace(
            qml_patch_diagnostics=types.SimpleNamespace(
                mark_success=marked.append, mark_failure=lambda *_: None,
            )
        )
        hass = FakeHass(FakeEntry(runtime_data=runtime))
        issue_registry.add(CORE_HOOK_ISSUE)
        flow = _prepare(repairs.DeviceCoreQmlHookRepairFlow(hass, "entry-1"))

        request = asyncio.create_task(flow.async_step_confirm({}))
        await api.started.wait()
        await _drop(request)
        api.gate.set()
        await _settle()

        # The station did the write either way; Home Assistant now knows it.
        assert CORE_HOOK_ISSUE not in issue_registry
        assert marked
        assert await flow.async_step_confirm({}) == CREATED
        assert api.calls.count("apply_qml_core") == 1

    asyncio.run(scenario())


def test_media_repair_finishes_the_station_writes(issue_registry) -> None:
    async def scenario() -> None:
        api = _GatedApi("async_apply_firewall")
        runtime = FakeRuntimeData(
            api,
            capabilities={"doorbell_video": {"supported": True}, "doorbell_call": {"supported": True}},
            self_test_status={
                "ok": False,
                "checks": {
                    "capabilities": {"ok": True},
                    "firewall": {"ok": False, "reason": "ipv4_media_ports_missing"},
                    "rtsp": {"ok": True},
                    "talkback_rtp": {"ok": True},
                    "homeassistant_user": {"ok": False},
                    "device_routing": {"ok": False},
                    "startup": {"ok": True},
                },
            },
        )
        entry = FakeEntry(runtime_data=runtime, options={"video_enabled": True})
        issue_registry.add(MEDIA_ISSUE)
        flow = _prepare(repairs.MediaSetupRepairFlow(FakeHass(entry), "entry-1"))

        request = asyncio.create_task(flow.async_step_confirm({}))
        await api.started.wait()
        await _drop(request)
        api.gate.set()
        await _settle()

        # Not only the firewall the request was cut in: the user as well.
        assert api.calls == [
            "set_firewall_enabled:True",
            "apply_firewall",
            "ensure_homeassistant_user:Home Assistant HA Test",
            "self_test",
            "device_user_status",
        ]
        assert MEDIA_ISSUE not in issue_registry
        assert await flow.async_step_confirm({}) == {
            "type": "create_entry", "data": {"repaired": ["firewall", "homeassistant_user"]},
        }
        assert api.calls.count("apply_firewall") == 1

    asyncio.run(scenario())


def test_media_repair_finishes_its_reload() -> None:
    async def scenario() -> None:
        runtime = FakeRuntimeData(FakePatchApi())
        runtime.connection_state.available = False
        entry = FakeEntry(runtime_data=runtime, options={"video_enabled": True})
        hass = FakeHass(entry)
        gate = asyncio.Event()
        hass.config_entries = _ReloadingConfigEntries(entry, gate)
        flow = _prepare(repairs.MediaSetupRepairFlow(hass, "entry-1"))

        request = asyncio.create_task(flow.async_step_confirm({}))
        await hass.config_entries.reload_started.wait()
        await _drop(request)
        gate.set()
        await _settle()

        assert hass.config_entries.reloads == ["entry-1"]
        assert hass.config_entries.state == "loaded"

    asyncio.run(scenario())
