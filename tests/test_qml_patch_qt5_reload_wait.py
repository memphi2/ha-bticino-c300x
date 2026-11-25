"""The GUI reload waits longer only for the Qt 5 display restart (firmware 3.0.x).

On 1.7.x and 2.0.2 the request and every call site stay as in the base:
no keyword, the 30 s reload wait (10 s agent limit, 15 s grace for the
script's trap, margin). The Qt 5 restart has the 30 s write limit on the
agent and the same grace, so it waits like a display write (50 s).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x import media_watchdog
from custom_components.bticino_c300x.api import C300XAgentApi
from custom_components.bticino_c300x.display_activation import gui_reload_kwargs
from custom_components.bticino_c300x.use_cases import maintenance

QT4_STATUSES = [None, {}, {"patched": True, "core_patched": True, "gui_running": True},
                {"patched": True, "qt5_overlay": None}]
QT5_STATUSES = [{"qt5_overlay": state, "gui_restart": "idle"} for state in ("active", "off", "failed")]


class _Api:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def async_reload_gui(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"ok": True}


def _entry(status: Any) -> SimpleNamespace:
    runtime = SimpleNamespace(api=_Api())
    if status is not None:
        runtime.qml_patch_status = status
    return SimpleNamespace(runtime_data=runtime, entry_id="entry", data={}, options={})


def _timeouts(**kwargs: Any) -> list[object]:
    calls: list[dict[str, object]] = []
    api = C300XAgentApi(
        SimpleNamespace(),  # type: ignore[arg-type]
        "http://agent.local:8080", "agent-token", "maintenance-token", timeout=5,
    )

    async def request_json(method: str, path: str, **request_kwargs: object) -> dict[str, object]:
        calls.append(request_kwargs)
        return {"ok": True}

    api._request_json = request_json  # type: ignore[method-assign]
    asyncio.run(api.async_reload_gui(**kwargs))
    return [call["request_timeout"] for call in calls]


def test_the_reload_request_keeps_the_base_wait_without_the_keyword() -> None:
    assert _timeouts() == [30.0]


def test_the_reload_request_waits_like_a_display_write_for_a_qt5_restart() -> None:
    assert _timeouts(display_restart=True) == [50.0]


@pytest.mark.parametrize("status", QT4_STATUSES)
def test_no_keyword_from_a_qt4_or_unknown_status(status: Any) -> None:
    assert gui_reload_kwargs(_entry(status)) == {}


@pytest.mark.parametrize("status", QT5_STATUSES)
def test_the_keyword_from_a_cached_qt5_status(status: Any) -> None:
    assert gui_reload_kwargs(_entry(status)) == {"display_restart": True}


@pytest.mark.parametrize("status,expected", [
    *((status, {}) for status in QT4_STATUSES),
    *((status, {"display_restart": True}) for status in QT5_STATUSES),
])
def test_the_service_and_the_watchdog_pass_it_on(monkeypatch, status: Any, expected: dict) -> None:
    entry = _entry(status)
    monkeypatch.setattr(maintenance, "ensure_maintenance_action", lambda entry, action: None)
    asyncio.run(maintenance.MaintenanceUseCase(entry).reload_gui())
    asyncio.run(media_watchdog._async_reload_display_gui_for_watchdog(
        entry.runtime_data.api, gui_reload_kwargs(entry)))
    assert entry.runtime_data.api.calls == [expected, expected]
