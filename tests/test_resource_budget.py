from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True,
        check=True,
        text=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def test_native_agent_http_module_stays_within_interim_budget() -> None:
    """Keep pressure on the remaining monolithic native HTTP module."""

    path = ROOT / "native_agent" / "src" / "http.c"

    # Bumped from 433_000 for the maintenance audio-codec endpoints (+ persist
    # of media.audioCodec on apply/restore). Splitting this monolith is a
    # separate backlog refactor; this interim ceiling keeps pressure on
    # unrelated growth.
    assert path.stat().st_size <= 440_000
    assert path.read_text(encoding="utf-8").count("\n") <= 12_720


def test_native_agent_event_payload_module_stays_small() -> None:
    """Keep the event payload extraction from growing into another HTTP module."""

    path = ROOT / "native_agent" / "src" / "event_payload.c"

    assert path.stat().st_size <= 9_000
    assert path.read_text(encoding="utf-8").count("\n") <= 300


def test_native_agent_json_util_module_stays_small() -> None:
    """Keep shared JSON helpers outside the HTTP monolith."""

    source = ROOT / "native_agent" / "src" / "json_util.c"
    header = ROOT / "native_agent" / "src" / "json_util.h"

    assert source.stat().st_size <= 7_500
    assert source.read_text(encoding="utf-8").count("\n") <= 230
    assert header.stat().st_size <= 1_500
    assert header.read_text(encoding="utf-8").count("\n") <= 40


def test_native_agent_media_bridge_stays_within_interim_budget() -> None:
    """Keep pressure on the remaining media bridge monolith."""

    path = ROOT / "native_agent" / "src" / "media_bridge.c"

    # Bumped from 229_000 for the compatible PCMU talkback path (codec-aware
    # payload types + silence), then to 232_500 for the codec-aware ring
    # talkback restamp (speex 97 -> negotiated 96). Splitting this monolith is
    # a separate backlog refactor; this interim ceiling keeps pressure on
    # unrelated growth.
    assert path.stat().st_size <= 232_500
    assert path.read_text(encoding="utf-8").count("\n") <= 6_900


def test_native_agent_media_audio_module_stays_small() -> None:
    """Keep the extracted audio helper from becoming another media bridge."""

    path = ROOT / "native_agent" / "src" / "media_audio.c"

    assert path.stat().st_size <= 5_000
    assert path.read_text(encoding="utf-8").count("\n") <= 180


def test_native_agent_media_sip_module_stays_small() -> None:
    """Keep SIP/SDP parsing outside the media bridge monolith."""

    source = ROOT / "native_agent" / "src" / "media_sip.c"
    header = ROOT / "native_agent" / "src" / "media_sip.h"

    assert source.stat().st_size <= 10_000
    assert source.read_text(encoding="utf-8").count("\n") <= 330
    assert header.stat().st_size <= 2_500
    assert header.read_text(encoding="utf-8").count("\n") <= 80


def test_large_python_modules_stay_within_interim_budget() -> None:
    """Catch accidental HA-side module bloat before it reaches a release."""

    oversized = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "custom_components" / "bticino_c300x").glob("*.py")
        if path.stat().st_size > 74_500
    ]

    assert oversized == []

    # api.py was refactored down from ~76.5k; keep it small so the client class
    # does not grow back into a god-object.
    api_py = ROOT / "custom_components" / "bticino_c300x" / "api.py"
    assert api_py.stat().st_size <= 45_000


def test_tracked_runtime_payload_budget_excludes_generated_archives() -> None:
    """Repository releases must not keep generated archives or device payload blobs."""

    forbidden_suffixes = {
        ".7z",
        ".apk",
        ".bin",
        ".deb",
        ".ext4",
        ".fwz",
        ".gz",
        ".img",
        ".ipk",
        ".o",
        ".rpm",
        ".so",
        ".tar",
        ".tgz",
        ".xz",
        ".zip",
    }
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in _tracked_files()
        if path.suffix.lower() in forbidden_suffixes
    ]

    assert offenders == []
