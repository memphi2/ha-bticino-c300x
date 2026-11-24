"""/ui/memos lists memos deleted through the agent for the display."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_deleted_memo_ids(tmp_path, sanitize):
    binary = tmp_path / "memo-deleted"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else ["-O2"]
    result = subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-g", "-Wall", "-Wextra", "-Werror", *flags,
         str(NATIVE / "test/memo_deleted_test.c"), str(NATIVE / "src/memo_deleted.c"),
         str(NATIVE / "src/string_util.c"), "-pthread", "-o", str(binary)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_memo_list_and_delete_use_the_ring():
    source = (NATIVE / "src/http.c").read_text(encoding="utf-8")
    # The last occurrence of each name is its definition, after the prototypes.
    entries = source[source.rindex("static int append_memo_entries("):source.rindex("static void handle_memos_get(")]
    listing = source[source.rindex("static void handle_memos_get("):source.rindex("static void handle_memos_delete(")]
    delete = source[source.rindex("static void handle_memos_delete("):source.rindex("static void handle_answering_post(")]
    assert "c300x_memo_deleted_seen(kind, message->id);" in entries
    assert "c300x_memo_deleted_finish_json(body, C300X_MEMOS_RESPONSE_SIZE, &used)" in listing
    # Only after the station confirmed the memo is gone.
    assert delete.index("c300x_memo_deleted_add(kind, entry_name);") > delete.index("memo_delete_timeout")
