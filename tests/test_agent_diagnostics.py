from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from custom_components.bticino_c300x import agent_diagnostics as diagnostics_module
from custom_components.bticino_c300x.agent_diagnostics import (
    _agent_diagnostics_change_reason,
    apply_agent_diagnostics_event,
    async_refresh_agent_diagnostics,
)
from custom_components.bticino_c300x.api import C300XAgentApiError


@dataclass
class _FakeApi:
    diagnostics: dict[str, Any] = field(default_factory=dict)
    fail: bool = False

    async def async_diagnostics(self) -> dict[str, Any]:
        if self.fail:
            raise C300XAgentApiError("offline")
        return self.diagnostics


def _entry(*, api: _FakeApi | None = None, capabilities: dict[str, Any] | None = None):
    return SimpleNamespace(
        entry_id="entry-1",
        runtime_data=SimpleNamespace(
            api=api or _FakeApi(),
            capabilities=capabilities or {"diagnostics": {"supported": True}},
            agent_diagnostics={},
            agent_diagnostics_updated_at=None,
            agent_diagnostics_updated_by=None,
            agent_diagnostics_change_reason=None,
        ),
    )


def test_refresh_agent_diagnostics_stores_status_and_notifies(
    monkeypatch,
) -> None:
    sent: list[tuple[object, str, str]] = []
    synced: list[str] = []
    entry = _entry(api=_FakeApi({"agent_write_count": 2, "last_write_reason": "qml"}))

    monkeypatch.setattr(
        diagnostics_module,
        "async_dispatcher_send",
        lambda hass, signal, entry_id: sent.append((hass, signal, entry_id)),
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_issues.async_sync_entry_repair_issues",
        lambda _hass, patched_entry: synced.append(patched_entry.entry_id),
    )

    result = asyncio.run(async_refresh_agent_diagnostics("hass", entry))

    assert result["agent_write_count"] == 2
    assert result["last_write_reason"] == "qml"
    assert entry.runtime_data.agent_diagnostics == result
    assert entry.runtime_data.agent_diagnostics_updated_at is not None
    assert entry.runtime_data.agent_diagnostics_updated_by == "api_refresh"
    assert entry.runtime_data.agent_diagnostics_change_reason == "api_refresh"
    assert sent == [("hass", "bticino_c300x_agent_diagnostics_changed", "entry-1")]
    assert synced == ["entry-1"]


def test_refresh_agent_diagnostics_skips_unsupported_or_failed_status() -> None:
    unsupported = _entry(capabilities={"diagnostics": {"supported": False}})
    failing = _entry(api=_FakeApi(fail=True))

    assert asyncio.run(async_refresh_agent_diagnostics("hass", unsupported)) is None
    assert asyncio.run(async_refresh_agent_diagnostics("hass", failing)) is None


def test_apply_agent_diagnostics_event_stores_valid_push_payload(monkeypatch) -> None:
    sent: list[str] = []
    entry = _entry()

    monkeypatch.setattr(
        diagnostics_module,
        "async_dispatcher_send",
        lambda _hass, _signal, entry_id: sent.append(entry_id),
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_issues.async_sync_entry_repair_issues",
        lambda _hass, _entry: None,
    )

    result = apply_agent_diagnostics_event(
        "hass",
        entry,
        {"agent_write_count": 3, "video_clients": 1},
    )

    assert result["agent_write_count"] == 3
    assert result["video_clients"] == 1
    assert entry.runtime_data.agent_diagnostics == result
    assert entry.runtime_data.agent_diagnostics_updated_by == "push_event"
    assert entry.runtime_data.agent_diagnostics_change_reason == "initial_push"
    assert sent == ["entry-1"]


def test_apply_agent_diagnostics_event_skips_duplicate_push_payloads(monkeypatch) -> None:
    sent: list[str] = []
    synced: list[str] = []
    payload = {"agent_write_count": 3, "video_clients": 1}
    entry = _entry()

    monkeypatch.setattr(
        diagnostics_module,
        "async_dispatcher_send",
        lambda _hass, _signal, entry_id: sent.append(entry_id),
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_issues.async_sync_entry_repair_issues",
        lambda _hass, patched_entry: synced.append(patched_entry.entry_id),
    )

    assert apply_agent_diagnostics_event("hass", entry, payload) is not None
    first_updated_at = entry.runtime_data.agent_diagnostics_updated_at
    assert apply_agent_diagnostics_event("hass", entry, payload) is not None

    assert entry.runtime_data.agent_diagnostics_updated_at == first_updated_at
    assert sent == ["entry-1"]
    assert synced == ["entry-1"]


def test_agent_diagnostics_event_records_specific_change_reason(monkeypatch) -> None:
    entry = _entry()
    monkeypatch.setattr(
        diagnostics_module,
        "async_dispatcher_send",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "custom_components.bticino_c300x.repair_issues.async_sync_entry_repair_issues",
        lambda *_args: None,
    )

    apply_agent_diagnostics_event("hass", entry, {"agent_write_count": 1})
    apply_agent_diagnostics_event(
        "hass",
        entry,
        {"agent_write_count": 1, "ring_call_active": True},
    )

    assert entry.runtime_data.agent_diagnostics_change_reason == (
        "media_diagnostics_changed"
    )


def test_agent_diagnostics_change_reason_prioritizes_known_groups() -> None:
    assert (
        _agent_diagnostics_change_reason(
            {"agent_write_count": 1},
            {"agent_write_count": 2},
        )
        == "write_diagnostics_changed"
    )
    assert (
        _agent_diagnostics_change_reason(
            {"last_wake_reason": "poll"},
            {"last_wake_reason": "api"},
        )
        == "agent_wake_reason_changed"
    )
    assert (
        _agent_diagnostics_change_reason(
            {"poll_wakeups": 1},
            {"poll_wakeups": 2},
        )
        == "agent_poll_activity_changed"
    )
    assert (
        _agent_diagnostics_change_reason(
            {"accepted_clients": 1},
            {"accepted_clients": 2},
        )
        == "agent_diagnostics_changed"
    )


def test_apply_agent_diagnostics_event_ignores_invalid_or_unsupported_payloads() -> None:
    unsupported = _entry(capabilities={"diagnostics": {"supported": False}})
    supported = _entry()

    assert apply_agent_diagnostics_event("hass", unsupported, {"agent_write_count": 1}) is None
    assert apply_agent_diagnostics_event("hass", supported, []) is None  # type: ignore[arg-type]
    assert supported.runtime_data.agent_diagnostics == {}
