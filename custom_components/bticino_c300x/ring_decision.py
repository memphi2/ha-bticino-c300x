"""Decision helpers for C300X ring-call transcription results."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .json_io import async_write_json_file
from .ring_ai import _read_capture_metadata, _ring_capture_metadata_path
from .ring_capture import _safe_c300x_path

DEFAULT_RING_ANALYSIS_RESULT_PATH = "/config/c300x/analysis/result.json"
DEFAULT_RING_ANALYSIS_DECISION_PATH = "/config/c300x/analysis/decision.json"
DEFAULT_USED_RING_CAPTURES_PATH = "/config/c300x/analysis/used_captures.json"
MAX_RING_ANALYSIS_AGE_SECONDS = 60


@dataclass(frozen=True)
class RingAnalysisDecision:
    """Strict decision derived from a local ring transcription result."""

    matched: bool
    phrase_match: bool
    decision_path: Path
    capture_id: str | None = None


async def async_evaluate_ring_analysis(
    hass: Any,
    *,
    result_path: str | None = None,
    decision_path: str | None = None,
    capture_path: str | None = None,
    expected_phrase: str | None = None,
    consume_on_match: bool = False,
    require_capture: bool = False,
) -> RingAnalysisDecision:
    """Evaluate a local Whisper result without image/person guessing."""

    result = await _async_ring_result_path(hass, result_path)
    decision = _ring_decision_path(hass, decision_path)
    payload = await _async_read_json(hass, result)
    phrase_match = _phrase_match(payload, expected_phrase=expected_phrase)
    guardrail = await _async_capture_guardrail_result(
        hass,
        payload,
        capture_path=capture_path,
        required=consume_on_match or require_capture,
    )
    matched = phrase_match and guardrail["ok"]
    decision_payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "result_path": str(result),
        "matched": matched,
        "phrase_match": phrase_match,
        "capture_guardrails_ok": guardrail["ok"],
        "capture_guardrail_reasons": guardrail["reasons"],
        "capture_id": guardrail["capture_id"],
        "capture_path": guardrail["capture_path"],
        "expected_phrase": expected_phrase or "",
        "transcript": str(payload.get("transcript") or "").strip(),
    }
    await async_write_json_file(hass, decision, decision_payload)
    if matched and consume_on_match and guardrail["capture_id"]:
        await _async_mark_capture_used(hass, guardrail["capture_id"])
    return RingAnalysisDecision(
        matched=matched,
        phrase_match=phrase_match,
        decision_path=decision,
        capture_id=guardrail["capture_id"] or None,
    )


async def async_mark_ring_capture_used(hass: Any, capture_id: str | None) -> None:
    """Mark a ring capture as consumed after the guarded action succeeded."""

    capture_id = str(capture_id or "").strip()
    if not capture_id:
        return
    await _async_mark_capture_used(hass, capture_id)


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


async def _async_ring_result_path(hass: Any, result_path: str | None) -> Path:
    if hasattr(hass, "async_add_executor_job"):
        return await hass.async_add_executor_job(_ring_result_path, hass, result_path)
    return await asyncio.to_thread(_ring_result_path, hass, result_path)


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


async def _async_capture_guardrail_result(
    hass: Any,
    payload: dict[str, Any],
    *,
    capture_path: str | None,
    required: bool,
) -> dict[str, Any]:
    def _check() -> dict[str, Any]:
        return _capture_guardrail_result(
            hass,
            payload,
            capture_path=capture_path,
            required=required,
        )

    if hasattr(hass, "async_add_executor_job"):
        return await hass.async_add_executor_job(_check)
    return await asyncio.to_thread(_check)


def _capture_guardrail_result(
    hass: Any,
    payload: dict[str, Any],
    *,
    capture_path: str | None,
    required: bool,
) -> dict[str, Any]:
    result_capture_id = str(payload.get("capture_id") or "").strip()
    result_capture_path = str(capture_path or payload.get("capture_path") or "").strip()
    reasons: list[str] = []
    capture_file: Path | None = None
    capture_payload: dict[str, Any] | None = None

    if not result_capture_id:
        reasons.append("missing_capture_id")
    if not result_capture_path:
        reasons.append("missing_capture_path")
    if result_capture_path:
        try:
            capture_file = _ring_capture_metadata_path(hass, result_capture_path)
            capture_payload = _read_capture_metadata(capture_file)
        except HomeAssistantError:
            reasons.append("capture_metadata_unavailable")
    if capture_payload is not None:
        capture_id = str(capture_payload.get("capture_id") or "").strip()
        if result_capture_id and capture_id != result_capture_id:
            reasons.append("capture_id_mismatch")
        if not _capture_result_paths_match(hass, payload, capture_payload):
            reasons.append("capture_wav_mismatch")
        if _capture_is_stale(capture_payload):
            reasons.append("capture_stale")
    if result_capture_id and _capture_id_was_used(hass, result_capture_id):
        reasons.append("capture_already_used")

    if not required and not result_capture_id and not result_capture_path:
        reasons = []
    return {
        "ok": not reasons,
        "reasons": reasons,
        "capture_id": result_capture_id,
        "capture_path": str(capture_file or result_capture_path),
    }


def _capture_result_paths_match(
    hass: Any,
    result_payload: dict[str, Any],
    capture_payload: dict[str, Any],
) -> bool:
    result_wav = str(result_payload.get("wav_path") or "").strip()
    capture_wav = str(capture_payload.get("raw_wav_path") or "").strip()
    if not result_wav or not capture_wav:
        return False
    try:
        result_path = _safe_c300x_path(hass, Path(result_wav), "ring result WAV")
        capture_path = _safe_c300x_path(hass, Path(capture_wav), "ring capture WAV")
    except HomeAssistantError:
        return False
    return result_path == capture_path


def _capture_is_stale(payload: dict[str, Any]) -> bool:
    created_at = str(payload.get("created_at") or "").strip()
    if not created_at:
        return True
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return datetime.now(UTC) - created > timedelta(seconds=MAX_RING_ANALYSIS_AGE_SECONDS)


def _used_captures_path(hass: Any) -> Path:
    config = getattr(hass, "config", None)
    if config is not None and hasattr(config, "path"):
        return _safe_c300x_path(
            hass,
            Path(config.path("c300x", "analysis", "used_captures.json")),
            "used ring captures",
        )
    return _safe_c300x_path(
        hass,
        Path(DEFAULT_USED_RING_CAPTURES_PATH),
        "used ring captures",
    )


def _last_used_capture_id(hass: Any) -> str:
    path = _used_captures_path(hass)
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("capture_id") or "").strip()


def _capture_id_was_used(hass: Any, capture_id: str) -> bool:
    return _last_used_capture_id(hass) == capture_id


async def _async_mark_capture_used(hass: Any, capture_id: str) -> None:
    def _mark() -> None:
        path = _used_captures_path(hass)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "capture_id": capture_id,
                    "used_at": datetime.now(UTC).isoformat(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    if hasattr(hass, "async_add_executor_job"):
        await hass.async_add_executor_job(_mark)
        return
    await asyncio.to_thread(_mark)


def _phrase_match(payload: dict[str, Any], *, expected_phrase: str | None) -> bool:
    transcript = str(payload.get("transcript") or "").strip()
    phrase = str(expected_phrase or "").strip()
    if phrase:
        return transcript.casefold() == phrase.casefold()
    return bool(payload.get("phrase_match", False))
