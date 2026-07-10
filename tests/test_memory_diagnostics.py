from __future__ import annotations

import asyncio
import logging
from collections import Counter
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x.memory_diagnostics import (
    _format_growth,
    _process_rss_bytes,
    async_start_memory_diagnostics,
)

_LOGGER_NAME = "custom_components.bticino_c300x.memory_diagnostics"


def test_process_rss_bytes_returns_positive_or_none() -> None:
    rss = _process_rss_bytes()
    assert rss is None or (isinstance(rss, int) and rss > 0)


def test_format_growth_reports_only_climbing_types() -> None:
    assert _format_growth(None, Counter({"dict": 10})) == ""
    previous = Counter({"dict": 100, "Task": 5})
    current = Counter({"dict": 700, "Task": 6})  # dict +600 (>=500), Task +1
    growth = _format_growth(previous, current)
    assert "dict+600" in growth
    assert "Task" not in growth


def test_disabled_when_not_debug() -> None:
    logger = logging.getLogger(_LOGGER_NAME)
    previous_level = logger.level
    logger.setLevel(logging.WARNING)
    try:
        removed: list[object] = []
        async_start_memory_diagnostics(
            SimpleNamespace(),
            SimpleNamespace(async_on_unload=removed.append),
        )
        assert removed == []
    finally:
        logger.setLevel(previous_level)


def test_enabled_registers_tracker_and_runs_first_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import homeassistant.helpers.event as he

    monkeypatch.setattr(
        he,
        "async_track_time_interval",
        lambda hass, action, interval: (lambda: None),
        raising=False,
    )
    logger = logging.getLogger(_LOGGER_NAME)
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        created: list[Any] = []

        async def _executor(func: Any, *args: Any) -> Any:
            return func(*args)

        hass = SimpleNamespace(
            async_add_executor_job=_executor,
            async_create_task=created.append,
        )
        removed: list[object] = []
        async_start_memory_diagnostics(
            hass,
            SimpleNamespace(async_on_unload=removed.append),
        )

        assert len(removed) == 1  # the interval tracker is registered for cleanup
        assert len(created) == 1  # the first snapshot is scheduled
        asyncio.run(created[0])  # runs without error and logs one snapshot
    finally:
        logger.setLevel(previous_level)
