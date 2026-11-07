"""Physical unlocks must use a durable, atomic, bounded one-use reservation."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.bticino_c300x import ring_capture_ledger as ledger
from custom_components.bticino_c300x.ring_decision import async_evaluate_ring_analysis
from custom_components.bticino_c300x.use_cases.ring_analysis import RingAnalysisUseCase


def analysis(root, capture_id):
    base = root / "c300x"
    base.mkdir(exist_ok=True)
    wav = base / f"{capture_id}.wav"
    wav.write_bytes(b"synthetic")
    capture = base / f"{capture_id}.capture.json"
    capture.write_text(
        json.dumps(
            {
                "capture_id": capture_id,
                "created_at": datetime.now(UTC).isoformat(),
                "raw_wav_path": str(wav),
            }
        )
    )
    result = base / f"{capture_id}.json"
    result.write_text(
        json.dumps(
            {
                "capture_id": capture_id,
                "capture_path": str(capture),
                "wav_path": str(wav),
                "transcript": "open",
            }
        )
    )
    return {
        "result_path": str(result),
        "decision_path": str(base / f"{capture_id}.decision.json"),
        "expected_phrase": "open",
    }


def test_capture_a_b_a_is_not_reusable(tmp_path):
    async def run():
        hass = SimpleNamespace(
            config=SimpleNamespace(path=lambda *parts: str(tmp_path.joinpath(*parts)))
        )
        first, second = analysis(tmp_path, "first"), analysis(tmp_path, "second")
        matches = [
            (
                await async_evaluate_ring_analysis(
                    hass, **params, consume_on_match=True
                )
            ).matched
            for params in (first, second, first)
        ]
        assert matches == [True, True, False]

    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
def test_unlock_is_reserved_once_even_if_action_fails(tmp_path, outcome):
    async def run():
        hass = SimpleNamespace(
            config=SimpleNamespace(path=lambda *parts: str(tmp_path.joinpath(*parts)))
        )
        params = analysis(tmp_path, "same")
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def unlock(lock_id):
            calls.append(lock_id)
            started.set()
            await release.wait()
            if outcome == "error":
                raise HomeAssistantError("uncertain device response")

        entry = SimpleNamespace(
            entry_id="test",
            runtime_data=SimpleNamespace(api=SimpleNamespace(async_unlock_door=unlock)),
        )
        first = asyncio.create_task(
            RingAnalysisUseCase(hass).evaluate(
                **params, unlock_on_match=True, unlock_entry=entry
            )
        )
        await asyncio.wait_for(started.wait(), 2)
        await RingAnalysisUseCase(hass).evaluate(
            **params, unlock_on_match=True, unlock_entry=entry
        )
        if outcome == "cancel":
            first.cancel()
        release.set()
        await asyncio.gather(first, return_exceptions=True)
        # A new use-case instance also represents the persisted-state path after reload.
        await RingAnalysisUseCase(hass).evaluate(
            **params, unlock_on_match=True, unlock_entry=entry
        )
        assert calls == ["default"]

    asyncio.run(run())


def test_reservation_read_modify_write_is_atomic_across_workers(tmp_path):
    path = tmp_path / "used.json"
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(
            pool.map(lambda _: ledger.reserve_capture(path, "same"), range(16))
        )
    assert accepted.count(True) == 1
    assert set(ledger.read_used_captures(path, datetime.now(UTC))) == {"same"}
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "payload", ["{", "[]", '{"version":2}', '{"version":1,"captures":[]}']
)
def test_invalid_ledger_fails_closed(tmp_path, payload):
    path = tmp_path / "used.json"
    path.write_text(payload)
    with pytest.raises(HomeAssistantError):
        ledger.reserve_capture(path, "new")
    assert path.read_text() == payload


def test_full_ledger_does_not_evict_live_reservations(tmp_path):
    path = tmp_path / "used.json"
    now = datetime.now(UTC)
    captures = {str(i): now.isoformat() for i in range(ledger.MAX_USED_CAPTURES)}
    path.write_text(json.dumps({"version": 1, "captures": captures}))
    with pytest.raises(HomeAssistantError, match="full"):
        ledger.reserve_capture(path, "new")
    assert not ledger.reserve_capture(path, "0")
    captures["0"] = (now - timedelta(minutes=5)).isoformat()
    path.write_text(json.dumps({"version": 1, "captures": captures}))
    assert ledger.reserve_capture(path, "new")


def test_legacy_reservation_is_preserved_and_atomic_write_failure_denies(
    tmp_path, monkeypatch
):
    path = tmp_path / "used.json"
    path.write_text(
        json.dumps({"capture_id": "legacy", "used_at": datetime.now(UTC).isoformat()})
    )
    assert not ledger.reserve_capture(path, "legacy")
    assert ledger.reserve_capture(path, "new")
    assert set(ledger.read_used_captures(path, datetime.now(UTC))) == {"legacy", "new"}
    before = path.read_bytes()

    def fail(*_args, **_kwargs):
        raise HomeAssistantError("disk full")

    monkeypatch.setattr(ledger, "write_utf8_file_atomic", fail)
    with pytest.raises(HomeAssistantError, match="disk full"):
        ledger.reserve_capture(path, "never-unlock")
    assert path.read_bytes() == before
