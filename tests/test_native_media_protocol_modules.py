"""Private media protocol modules link and run without bridge/session state."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_rtsp_reader_contract(tmp_path, sanitize):
    binary = tmp_path / "reader"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    result = subprocess.run(
        ["cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", *flags,
         str(NATIVE / "test/media_rtsp_reader_test.c"),
         *(str(NATIVE / f"src/{name}.c") for name in (
             "media_rtsp_reader", "media_rtsp_io", "media_sip", "media_base64",
             "string_util", "time_util",
         )), "-pthread", "-o", str(binary)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_rtsp_reader_has_no_session_or_resource_ownership(tmp_path):
    source = NATIVE / "src/media_rtsp_reader.c"
    obj = tmp_path / "reader.o"
    subprocess.run(["cc", "-std=c11", "-c", str(source), "-o", str(obj)], check=True)
    symbols = subprocess.check_output(["nm", "-g", str(obj)], text=True)
    exports = {line.split()[-1] for line in symbols.splitlines() if " T " in line}
    assert exports == {"c300x_media_rtsp_read"}
    dependencies = {line.split()[-1] for line in symbols.splitlines() if " U " in line}
    assert dependencies <= {
        "c300x_media_sip_content_length", "c300x_rtsp_wait_readable", "memcpy", "memmove", "recv", "strstr",
        "__stack_chk_fail",
    }
    header = (NATIVE / "src/media_rtsp_reader.h").read_text()
    assert "media_bridge" not in header
    assert "c300x_video" not in header
