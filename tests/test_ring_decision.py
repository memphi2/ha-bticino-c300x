from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from custom_components.bticino_c300x.ring_decision import (
    DEFAULT_RING_ANALYSIS_DECISION_PATH,
    DEFAULT_RING_ANALYSIS_RESULT_PATH,
    _phrase_match,
    _ring_decision_path,
    _ring_result_path,
)


class _FakeConfig:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, *parts: str) -> str:
        return str(self.root.joinpath(*parts))


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
