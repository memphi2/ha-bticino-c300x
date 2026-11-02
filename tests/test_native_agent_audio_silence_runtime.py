"""Exercise the production silent RTP sender without device or network access."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.fixture(scope="module")
def audio_silence_binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    binary = tmp_path_factory.mktemp("audio-silence") / "audio-silence-test"
    subprocess.run(
        [
            "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
            str(NATIVE / "test/media_audio_silence_test.c"),
            "-pthread", "-ldl", "-o", str(binary),
        ],
        check=True, capture_output=True, text=True,
    )
    return binary


@pytest.mark.parametrize(
    "case",
    [
        "pcmu", "speex_ondemand", "speex_ring", "unavailable", "null_state",
        "null_session", "invalid_fd", "invalid_port", "protect_failure",
    ],
)
def test_native_audio_silence(audio_silence_binary: Path, case: str) -> None:
    result = subprocess.run(
        [str(audio_silence_binary), case], capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
