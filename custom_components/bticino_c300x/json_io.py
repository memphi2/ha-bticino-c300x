"""Async JSON file helpers for C300X local analysis files."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any


async def async_write_json_file(hass: Any, path: Path, payload: dict[str, Any]) -> None:
    """Write JSON through Home Assistant's executor when available."""

    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    if hasattr(hass, "async_add_executor_job"):
        await hass.async_add_executor_job(_write)
        return
    await asyncio.to_thread(_write)
