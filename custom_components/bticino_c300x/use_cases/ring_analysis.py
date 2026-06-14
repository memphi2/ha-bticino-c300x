"""Ring audio analysis service use cases."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant

from ..exceptions import service_validation_error
from ..ring_ai import async_run_wyoming_ring_analysis
from ..ring_decision import async_evaluate_ring_analysis, async_mark_ring_capture_used
from .device_actions import DeviceActionsUseCase


class RingAnalysisUseCase:
    """Run ring transcription and decision commands."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def transcribe(
        self,
        *,
        wyoming_host: str,
        wyoming_port: int = 10300,
        capture_path: str | None = None,
        wav_path: str | None = None,
        result_path: str | None = None,
        language: str | None = None,
        expected_phrase: str | None = None,
    ) -> None:
        """Transcribe the latest C300X ring raw WAV through Wyoming Whisper."""

        await async_run_wyoming_ring_analysis(
            self._hass,
            wyoming_host=wyoming_host,
            wyoming_port=wyoming_port,
            capture_path=capture_path,
            wav_path=wav_path,
            result_path=result_path,
            language=language,
            expected_phrase=expected_phrase,
        )

    async def evaluate(
        self,
        *,
        result_path: str | None = None,
        decision_path: str | None = None,
        capture_path: str | None = None,
        expected_phrase: str | None = None,
        unlock_on_match: bool = False,
        unlock_entry: Any | None = None,
        unlock_entry_provider: Callable[[], Any] | None = None,
        lock_id: str = "default",
    ) -> None:
        """Evaluate a ring-analysis result and optionally unlock."""

        decision = await async_evaluate_ring_analysis(
            self._hass,
            result_path=result_path,
            decision_path=decision_path,
            capture_path=capture_path,
            expected_phrase=expected_phrase,
            require_capture=unlock_on_match,
        )
        if not (decision.matched and unlock_on_match):
            return
        entry = unlock_entry
        if entry is None and unlock_entry_provider is not None:
            entry = unlock_entry_provider()
        if entry is None:
            raise service_validation_error("entry_id_required")
        await DeviceActionsUseCase(self._hass, entry).unlock(lock_id)
        await async_mark_ring_capture_used(
            self._hass,
            getattr(decision, "capture_id", None),
        )
