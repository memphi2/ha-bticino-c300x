"""The agent's call table and outdoor units against captured frame sequences.

See native_agent/test/call_table_test.c: the owner's one-unit captures and the
frames of a three-unit installation (20#2 behind an apartment interface).
"""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
SOURCES = ("call_table.c", "outdoor_units.c", "station_archive.c", "json_util.c", "json_parse.c", "string_util.c", "file_io.c", "sha256.c")
CASES = (
    "single_unit_capture",
    "unanswered_capture",
    "station_answer",
    "app_answer_end_frame_first",
    "display_guard",
    "unit_behind_interface",
    "two_units_within_one_second",
    "caller_missing",
    "caller_late",
    "stale_call_id",
    "rings_of_one_session",
    "hangup_reason",
    "view_and_media_closed",
    "timeouts_and_json",
    "plain_address_is_the_qualified_unit",
    "seen_units_survive_restart",
    "archive_objects_by_cid",
)


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def call_table_binary(request, tmp_path_factory):
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    binary = tmp_path_factory.mktemp("call-table") / "call-table"
    build = subprocess.run(
        [
            "cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", *flags,
            str(NATIVE / "test/call_table_test.c"), *(str(NATIVE / "src" / name) for name in SOURCES),
            "-o", str(binary),
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert build.returncode == 0, build.stderr
    return binary


@pytest.mark.parametrize("case", CASES)
def test_call_table(call_table_binary, case):
    result = subprocess.run([str(call_table_binary), case], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == f"ok {case}"
