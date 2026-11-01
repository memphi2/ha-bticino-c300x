"""Execute the production SIP reader on sockets, including its bridge caller."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.fixture(scope="module")
def sip_io_binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    binary = tmp_path_factory.mktemp("sip-io") / "sip-io-test"
    subprocess.run(
        [
            "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
            str(NATIVE / "test/media_sip_io_test.c"),
            str(NATIVE / "src/media_sip_io.c"),
            str(NATIVE / "src/media_sip.c"),
            str(NATIVE / "src/string_util.c"),
            str(NATIVE / "src/time_util.c"),
            "-pthread", "-ldl", "-o", str(binary),
        ],
        check=True, capture_output=True, text=True,
    )
    return binary


@pytest.mark.parametrize(
    "case",
    [
        "coalesced", "fragmented", "keepalive", "deadline", "lengths", "limits",
        "keepalive_response", "poll_keepalive", "poll_fragmented",
        "datagrams", "independent", "tcp", "interrupted", "binary_body",
        "stop_responses", "stop_eof",
        "idle_and_eof", "negative_length",
        "oversize_length", "duplicate_length", "garbage_length", "empty_length",
        "missing_length", "partial_header", "partial_body", "eof_header", "eof_body",
    ],
)
def test_native_sip_message_framing(sip_io_binary: Path, case: str) -> None:
    result = subprocess.run(
        [str(sip_io_binary), case], capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
