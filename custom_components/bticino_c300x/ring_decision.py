"""Decision helpers for C300X ring-call transcription results."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .ring_capture import _safe_c300x_path

DEFAULT_RING_ANALYSIS_RESULT_PATH = "/config/c300x/ring/analysis/result.json"
DEFAULT_RING_ANALYSIS_DECISION_PATH = "/config/c300x/ring/analysis/decision.json"


@dataclass(frozen=True)
class RingAnalysisDecision:
    """Strict decision derived from a local ring transcription result."""

    matched: bool
    phrase_match: bool
    decision_path: Path


async def async_evaluate_ring_analysis(
    hass: Any,
    *,
    result_path: str | None = None,
    decision_path: str | None = None,
    expected_phrase: str | None = None,
) -> RingAnalysisDecision:
    """Evaluate a local Whisper result without image/person guessing."""

    result = _ring_result_path(hass, result_path)
    decision = _ring_decision_path(hass, decision_path)
    payload = await _async_read_json(hass, result)
    phrase_match = _phrase_match(payload, expected_phrase=expected_phrase)
    decision_payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "result_path": str(result),
        "matched": phrase_match,
        "phrase_match": phrase_match,
        "expected_phrase": expected_phrase or "",
        "transcript": str(payload.get("transcript") or "").strip(),
    }
    await _async_write_json(hass, decision, decision_payload)
    return RingAnalysisDecision(
        matched=phrase_match,
        phrase_match=phrase_match,
        decision_path=decision,
    )


def _ring_result_path(hass: Any, result_path: str | None) -> Path:
    result = _safe_c300x_path(
        hass,
        Path(result_path or DEFAULT_RING_ANALYSIS_RESULT_PATH).expanduser(),
        "ring analysis result",
    )
    if result.suffix.lower() != ".json":
        raise HomeAssistantError("C300X ring analysis result must be a JSON file")
    if not result.is_file():
        raise HomeAssistantError("C300X ring analysis result does not exist")
    return result


def _ring_decision_path(hass: Any, decision_path: str | None) -> Path:
    decision = _safe_c300x_path(
        hass,
        Path(decision_path or DEFAULT_RING_ANALYSIS_DECISION_PATH).expanduser(),
        "ring analysis decision",
    )
    if decision.suffix.lower() != ".json":
        raise HomeAssistantError("C300X ring analysis decision must be a JSON file")
    return decision


async def _async_read_json(hass: Any, path: Path) -> dict[str, Any]:
    def _read() -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            raise HomeAssistantError("C300X ring analysis result is invalid JSON") from err
        if not isinstance(data, dict):
            raise HomeAssistantError("C300X ring analysis result must be a JSON object")
        return data

    if hasattr(hass, "async_add_executor_job"):
        return await hass.async_add_executor_job(_read)
    return await asyncio.to_thread(_read)


async def _async_write_json(hass: Any, path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    if hasattr(hass, "async_add_executor_job"):
        await hass.async_add_executor_job(_write)
        return
    await asyncio.to_thread(_write)


def _phrase_match(payload: dict[str, Any], *, expected_phrase: str | None) -> bool:
    if "phrase_match" in payload:
        return bool(payload["phrase_match"])
    if not expected_phrase:
        return False
    transcript = str(payload.get("transcript") or "").strip()
    return transcript.casefold() == expected_phrase.strip().casefold()
