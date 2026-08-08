from __future__ import annotations

# ruff: noqa: E402
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x import ring_ai as ring_ai_module
from custom_components.bticino_c300x import ring_capture as ring_capture_module
from custom_components.bticino_c300x import ring_decision as ring_decision_module
from custom_components.bticino_c300x.ring_decision import (
    DEFAULT_RING_ANALYSIS_DECISION_PATH,
    DEFAULT_RING_ANALYSIS_RESULT_PATH,
    DEFAULT_USED_RING_CAPTURES_PATH,
    _capture_guardrail_result,
    _capture_is_stale,
    _capture_result_paths_match,
    _last_used_capture_id,
    _phrase_match,
    _ring_decision_path,
    _ring_result_path,
    _used_captures_path,
    async_evaluate_ring_analysis,
    async_mark_ring_capture_used,
)

ring_ai_module.HomeAssistantError = ring_capture_module.HomeAssistantError
ring_decision_module.HomeAssistantError = ring_capture_module.HomeAssistantError
HomeAssistantError = ring_capture_module.HomeAssistantError


async def _to_thread_inline(func, /, *args, **kwargs):  # noqa: ANN001
    return func(*args, **kwargs)


class _FakeConfig:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, *parts: str) -> str:
        return str(self.root.joinpath(*parts))


class _FakeHass:
    def __init__(self, root: Path) -> None:
        self.config = _FakeConfig(root)
        self.executor_jobs: list[str] = []

    async def async_add_executor_job(self, func, *args):
        self.executor_jobs.append(getattr(func, "__name__", str(func)))
        return func(*args)


def test_phrase_match_prefers_explicit_expected_phrase() -> None:
    assert (
        _phrase_match(
            {"transcript": "open the door", "phrase_match": True},
            expected_phrase="wrong phrase",
        )
        is False
    )


def test_phrase_match_uses_payload_only_without_expected_phrase() -> None:
    assert _phrase_match({"transcript": "wrong", "phrase_match": True}, expected_phrase=None)


def test_ring_decision_defaults_use_config_analysis_dir(tmp_path: Path) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))
    result = tmp_path / "c300x" / "analysis" / "result.json"
    decision = tmp_path / "c300x" / "analysis" / "decision.json"

    assert DEFAULT_RING_ANALYSIS_RESULT_PATH == "/config/c300x/analysis/result.json"
    assert DEFAULT_RING_ANALYSIS_DECISION_PATH == "/config/c300x/analysis/decision.json"
    result.parent.mkdir(parents=True)
    result.write_text("{}", encoding="utf-8")
    assert _ring_result_path(hass, str(result)) == result
    assert _ring_decision_path(hass, str(decision)) == decision


def test_ring_result_path_rejects_invalid_paths(tmp_path: Path) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))
    result = tmp_path / "c300x" / "analysis" / "result.json"
    result.parent.mkdir(parents=True)
    result.write_text("{}", encoding="utf-8")

    with pytest.raises(HomeAssistantError, match="must be a JSON file"):
        _ring_result_path(hass, str(result.with_suffix(".txt")))
    with pytest.raises(HomeAssistantError, match="does not exist"):
        _ring_result_path(hass, str(result.with_name("missing.json")))
    with pytest.raises(HomeAssistantError, match="paths must be below"):
        _ring_result_path(hass, str(tmp_path / "outside.json"))


def test_ring_decision_path_rejects_non_json_target(tmp_path: Path) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))

    with pytest.raises(HomeAssistantError, match="must be a JSON file"):
        _ring_decision_path(hass, str(tmp_path / "c300x" / "decision.txt"))


def test_evaluate_ring_analysis_matches_expected_phrase_and_writes_decision(
    tmp_path: Path,
) -> None:
    hass = _FakeHass(tmp_path)
    result = tmp_path / "c300x" / "analysis" / "result.json"
    decision = tmp_path / "c300x" / "analysis" / "decision.json"
    result.parent.mkdir(parents=True)
    result.write_text(
        json.dumps({"transcript": "Open the door", "phrase_match": False}),
        encoding="utf-8",
    )

    evaluated = asyncio.run(
        async_evaluate_ring_analysis(
            hass,
            result_path=str(result),
            decision_path=str(decision),
            expected_phrase="open the door",
        )
    )

    assert evaluated.matched is True
    assert evaluated.phrase_match is True
    assert evaluated.decision_path == decision
    payload = json.loads(decision.read_text(encoding="utf-8"))
    assert payload["matched"] is True
    assert payload["phrase_match"] is True
    assert payload["expected_phrase"] == "open the door"
    assert payload["transcript"] == "Open the door"
    assert hass.executor_jobs == ["_ring_result_path", "_read", "_check", "_write"]


def test_evaluate_ring_analysis_consumes_fresh_capture_once(
    tmp_path: Path,
) -> None:
    hass = _FakeHass(tmp_path)
    wav = tmp_path / "c300x" / "latest.raw.wav"
    capture = tmp_path / "c300x" / "latest.capture.json"
    result = tmp_path / "c300x" / "analysis" / "result.json"
    decision = tmp_path / "c300x" / "analysis" / "decision.json"
    wav.parent.mkdir(parents=True)
    result.parent.mkdir(parents=True)
    wav.write_bytes(b"fake wav")
    capture.write_text(
        json.dumps(
            {
                "capture_id": "capture-1",
                "created_at": datetime.now(UTC).isoformat(),
                "raw_wav_path": str(wav),
            }
        ),
        encoding="utf-8",
    )
    result.write_text(
        json.dumps(
            {
                "capture_id": "capture-1",
                "capture_path": str(capture),
                "wav_path": str(wav),
                "transcript": "Open the door",
                "phrase_match": False,
            }
        ),
        encoding="utf-8",
    )

    first = asyncio.run(
        async_evaluate_ring_analysis(
            hass,
            result_path=str(result),
            decision_path=str(decision),
            expected_phrase="open the door",
            consume_on_match=True,
        )
    )
    second = asyncio.run(
        async_evaluate_ring_analysis(
            hass,
            result_path=str(result),
            decision_path=str(decision),
            expected_phrase="open the door",
            consume_on_match=True,
        )
    )

    assert DEFAULT_USED_RING_CAPTURES_PATH == "/config/c300x/analysis/used_captures.json"
    assert first.matched is True
    assert second.matched is False
    payload = json.loads(decision.read_text(encoding="utf-8"))
    assert payload["capture_guardrails_ok"] is False
    assert payload["capture_guardrail_reasons"] == ["capture_already_used"]
    used = tmp_path / "c300x" / "analysis" / "used_captures.json"
    assert json.loads(used.read_text(encoding="utf-8"))["capture_id"] == "capture-1"


def test_evaluate_ring_analysis_requires_capture_without_consuming_it(
    tmp_path: Path,
) -> None:
    hass = _FakeHass(tmp_path)
    wav = tmp_path / "c300x" / "latest.raw.wav"
    capture = tmp_path / "c300x" / "latest.capture.json"
    result = tmp_path / "c300x" / "analysis" / "result.json"
    decision = tmp_path / "c300x" / "analysis" / "decision.json"
    wav.parent.mkdir(parents=True)
    result.parent.mkdir(parents=True)
    wav.write_bytes(b"fake wav")
    capture.write_text(
        json.dumps(
            {
                "capture_id": "capture-1",
                "created_at": datetime.now(UTC).isoformat(),
                "raw_wav_path": str(wav),
            }
        ),
        encoding="utf-8",
    )
    result.write_text(
        json.dumps(
            {
                "capture_id": "capture-1",
                "capture_path": str(capture),
                "wav_path": str(wav),
                "transcript": "Open the door",
                "phrase_match": False,
            }
        ),
        encoding="utf-8",
    )

    evaluated = asyncio.run(
        async_evaluate_ring_analysis(
            hass,
            result_path=str(result),
            decision_path=str(decision),
            expected_phrase="open the door",
            require_capture=True,
        )
    )

    assert evaluated.matched is True
    assert evaluated.capture_id == "capture-1"
    used = tmp_path / "c300x" / "analysis" / "used_captures.json"
    assert not used.exists()


def test_evaluate_ring_analysis_blocks_stale_capture_for_unlock(tmp_path: Path) -> None:
    hass = _FakeHass(tmp_path)
    wav = tmp_path / "c300x" / "latest.raw.wav"
    capture = tmp_path / "c300x" / "latest.capture.json"
    result = tmp_path / "c300x" / "analysis" / "result.json"
    decision = tmp_path / "c300x" / "analysis" / "decision.json"
    wav.parent.mkdir(parents=True)
    result.parent.mkdir(parents=True)
    wav.write_bytes(b"fake wav")
    capture.write_text(
        json.dumps(
            {
                "capture_id": "capture-1",
                "created_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
                "raw_wav_path": str(wav),
            }
        ),
        encoding="utf-8",
    )
    result.write_text(
        json.dumps(
            {
                "capture_id": "capture-1",
                "capture_path": str(capture),
                "wav_path": str(wav),
                "transcript": "Open",
                "phrase_match": True,
            }
        ),
        encoding="utf-8",
    )

    evaluated = asyncio.run(
        async_evaluate_ring_analysis(
            hass,
            result_path=str(result),
            decision_path=str(decision),
            consume_on_match=True,
        )
    )

    assert evaluated.phrase_match is True
    assert evaluated.matched is False
    payload = json.loads(decision.read_text(encoding="utf-8"))
    assert payload["capture_guardrail_reasons"] == ["capture_stale"]


def test_mark_ring_capture_used_ignores_empty_capture_id(tmp_path: Path) -> None:
    hass = _FakeHass(tmp_path)

    asyncio.run(async_mark_ring_capture_used(hass, ""))
    asyncio.run(async_mark_ring_capture_used(hass, None))

    assert not (tmp_path / "c300x" / "analysis" / "used_captures.json").exists()


def test_evaluate_ring_analysis_requires_capture_metadata(tmp_path: Path) -> None:
    hass = _FakeHass(tmp_path)
    result = tmp_path / "c300x" / "analysis" / "result.json"
    decision = tmp_path / "c300x" / "analysis" / "decision.json"
    result.parent.mkdir(parents=True)
    result.write_text(
        json.dumps({"transcript": "Open", "phrase_match": True}),
        encoding="utf-8",
    )

    evaluated = asyncio.run(
        async_evaluate_ring_analysis(
            hass,
            result_path=str(result),
            decision_path=str(decision),
            require_capture=True,
        )
    )

    assert evaluated.phrase_match is True
    assert evaluated.matched is False
    payload = json.loads(decision.read_text(encoding="utf-8"))
    assert payload["capture_guardrail_reasons"] == [
        "missing_capture_id",
        "missing_capture_path",
    ]


def test_evaluate_ring_analysis_blocks_mismatched_capture_metadata(
    tmp_path: Path,
) -> None:
    hass = _FakeHass(tmp_path)
    result_wav = tmp_path / "c300x" / "result.raw.wav"
    capture_wav = tmp_path / "c300x" / "capture.raw.wav"
    capture = tmp_path / "c300x" / "latest.capture.json"
    result = tmp_path / "c300x" / "analysis" / "result.json"
    decision = tmp_path / "c300x" / "analysis" / "decision.json"
    result_wav.parent.mkdir(parents=True)
    result.parent.mkdir(parents=True)
    result_wav.write_bytes(b"result")
    capture_wav.write_bytes(b"capture")
    capture.write_text(
        json.dumps(
            {
                "capture_id": "other-capture",
                "created_at": "not-a-date",
                "raw_wav_path": str(capture_wav),
            }
        ),
        encoding="utf-8",
    )
    result.write_text(
        json.dumps(
            {
                "capture_id": "capture-1",
                "capture_path": str(capture),
                "wav_path": str(result_wav),
                "transcript": "Open",
                "phrase_match": True,
            }
        ),
        encoding="utf-8",
    )

    evaluated = asyncio.run(
        async_evaluate_ring_analysis(
            hass,
            result_path=str(result),
            decision_path=str(decision),
            consume_on_match=True,
        )
    )

    assert evaluated.matched is False
    payload = json.loads(decision.read_text(encoding="utf-8"))
    assert payload["capture_guardrail_reasons"] == [
        "capture_id_mismatch",
        "capture_wav_mismatch",
        "capture_stale",
    ]


def test_evaluate_ring_analysis_treats_invalid_used_capture_file_as_unused(
    tmp_path: Path,
) -> None:
    hass = _FakeHass(tmp_path)
    wav = tmp_path / "c300x" / "latest.raw.wav"
    capture = tmp_path / "c300x" / "latest.capture.json"
    used = tmp_path / "c300x" / "analysis" / "used_captures.json"
    result = tmp_path / "c300x" / "analysis" / "result.json"
    decision = tmp_path / "c300x" / "analysis" / "decision.json"
    wav.parent.mkdir(parents=True)
    used.parent.mkdir(parents=True)
    wav.write_bytes(b"fake wav")
    used.write_text("{", encoding="utf-8")
    capture.write_text(
        json.dumps(
            {
                "capture_id": "capture-1",
                "created_at": datetime.now(UTC).isoformat(),
                "raw_wav_path": str(wav),
            }
        ),
        encoding="utf-8",
    )
    result.write_text(
        json.dumps(
            {
                "capture_id": "capture-1",
                "capture_path": str(capture),
                "wav_path": str(wav),
                "transcript": "Open",
                "phrase_match": True,
            }
        ),
        encoding="utf-8",
    )

    evaluated = asyncio.run(
        async_evaluate_ring_analysis(
            hass,
            result_path=str(result),
            decision_path=str(decision),
            consume_on_match=True,
        )
    )

    assert evaluated.matched is True
    assert json.loads(used.read_text(encoding="utf-8"))["capture_id"] == "capture-1"


def test_evaluate_ring_analysis_uses_payload_match_without_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))
    result = tmp_path / "c300x" / "analysis" / "result.json"
    decision = tmp_path / "c300x" / "analysis" / "decision.json"
    result.parent.mkdir(parents=True)
    result.write_text(
        json.dumps({"transcript": "irrelevant", "phrase_match": True}),
        encoding="utf-8",
    )
    monkeypatch.setattr(ring_decision_module.asyncio, "to_thread", _to_thread_inline)

    evaluated = asyncio.run(
        async_evaluate_ring_analysis(
            hass,
            result_path=str(result),
            decision_path=str(decision),
        )
    )

    assert evaluated.matched is True
    assert json.loads(decision.read_text(encoding="utf-8"))["expected_phrase"] == ""


def test_evaluate_ring_analysis_rejects_bad_json_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))
    result = tmp_path / "c300x" / "analysis" / "result.json"
    decision = tmp_path / "c300x" / "analysis" / "decision.json"
    result.parent.mkdir(parents=True)
    monkeypatch.setattr(ring_decision_module.asyncio, "to_thread", _to_thread_inline)

    result.write_text("{", encoding="utf-8")
    with pytest.raises(HomeAssistantError, match="invalid JSON"):
        asyncio.run(
            async_evaluate_ring_analysis(
                hass,
                result_path=str(result),
                decision_path=str(decision),
            )
        )

    result.write_text("[]", encoding="utf-8")
    with pytest.raises(HomeAssistantError, match="must be a JSON object"):
        asyncio.run(
            async_evaluate_ring_analysis(
                hass,
                result_path=str(result),
                decision_path=str(decision),
            )
        )


def test_capture_guardrail_reports_unavailable_metadata(tmp_path: Path) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))

    guardrail = _capture_guardrail_result(
        hass,
        {
            "capture_id": "capture-1",
            "capture_path": str(tmp_path / "c300x" / "missing.capture.json"),
        },
        capture_path=None,
        required=True,
    )
    optional = _capture_guardrail_result(
        hass,
        {},
        capture_path=None,
        required=False,
    )

    assert guardrail["ok"] is False
    assert guardrail["reasons"] == ["capture_metadata_unavailable"]
    assert optional["ok"] is True
    assert optional["reasons"] == []


def test_capture_path_match_rejects_missing_or_unsafe_paths(tmp_path: Path) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))
    c300x_wav = tmp_path / "c300x" / "capture.raw.wav"

    assert _capture_result_paths_match(hass, {}, {}) is False
    assert (
        _capture_result_paths_match(
            hass,
            {"wav_path": str(tmp_path / "outside.raw.wav")},
            {"raw_wav_path": str(c300x_wav)},
        )
        is False
    )


def test_capture_stale_handles_missing_and_naive_timestamps() -> None:
    assert _capture_is_stale({}) is True
    assert _capture_is_stale({"created_at": datetime.now().isoformat()}) is False


def test_used_capture_helpers_fall_back_without_hass_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass = SimpleNamespace()
    used = tmp_path / "used_captures.json"
    monkeypatch.setattr(ring_decision_module, "DEFAULT_USED_RING_CAPTURES_PATH", str(used))
    monkeypatch.setattr(
        ring_decision_module,
        "_safe_c300x_path",
        lambda _hass, target, _path_kind: target,
    )

    used.write_text("[]", encoding="utf-8")

    assert _used_captures_path(hass) == used
    assert _last_used_capture_id(hass) == ""


def test_mark_capture_used_uses_thread_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hass = SimpleNamespace(config=_FakeConfig(tmp_path))
    monkeypatch.setattr(ring_decision_module.asyncio, "to_thread", _to_thread_inline)

    asyncio.run(async_mark_ring_capture_used(hass, "capture-thread"))

    used = tmp_path / "c300x" / "analysis" / "used_captures.json"
    assert json.loads(used.read_text(encoding="utf-8"))["capture_id"] == "capture-thread"
