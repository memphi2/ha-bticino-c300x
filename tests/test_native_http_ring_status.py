"""The extracted ring status serializer preserves the complete HTTP contract."""

import json
import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def status_binary(request, tmp_path_factory):
    binary = tmp_path_factory.mktemp("http-ring-status") / "probe"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if request.param else []
    result = subprocess.run([
        "cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
        "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", *flags,
        str(NATIVE / "test/http_ring_status_test.c"),
        str(NATIVE / "src/http_ring_status.c"), str(NATIVE / "src/json_util.c"),
        str(NATIVE / "src/json_parse.c"),
        "-o", str(binary),
    ], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("mode", range(5), ids=["null", "idle", "ring", "answered", "escaped"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("ready", [False, True])
@pytest.mark.parametrize("deferred", [False, True])
def test_complete_status_contract(status_binary, mode, enabled, ready, deferred):
    result = subprocess.run(
        [str(status_binary), str(mode), str(int(enabled)), str(int(ready)), str(int(deferred))],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
    if deferred:
        assert result.stdout == ""
        return
    active = mode >= 2
    answered = mode >= 3
    assert json.loads(result.stdout) == {
        "ok": True, "supported": enabled, "active": active,
        "early_media_active": active, "audio_active": active,
        "answer_requested": active, "answered": answered,
        "hangup_requested": answered, "can_answer": active and not answered,
        "can_hangup": active, "talkback_ready": mode != 0 and ready,
        "media_owner": "\x02" * 31 if mode == 4 else "ring" if active else "idle",
        "ring_receiver_running": active, "ring_registered": active,
        "capture_supported": False, "open_fds": 17 if active else 0,
        "active_threads": 3 if active else 0,
        "last_error": "\x01" * 127 if mode == 4 else None,
    }
