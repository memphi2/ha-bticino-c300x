"""Private media protocol modules link and run without bridge/session state."""

import subprocess
from pathlib import Path

import pytest

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.mark.parametrize("module", ["rtsp_reader", "sip_dialog"])
@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_media_protocol_contract(tmp_path, sanitize, module):
    binary = tmp_path / module
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    sources = ["media_rtsp_io", "media_sip", "media_base64", "string_util", "time_util", f"media_{module}"]
    if module == "sip_dialog":
        sources.append("media_sip_io")
        flags.append("-Wl,--wrap=time")
    result = subprocess.run(
        ["cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic",
         "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", *flags,
         str(NATIVE / f"test/media_{module}_test.c"),
         *(str(NATIVE / f"src/{name}.c") for name in sources),
         "-pthread", "-o", str(binary)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module,exports,dependencies", [
    ("rtsp_reader", {"c300x_media_rtsp_read"}, {
        "c300x_media_sip_content_length", "c300x_rtsp_wait_readable", "memcpy", "memmove", "recv", "strstr",
    }),
    ("sip_dialog", {"c300x_media_sip_send_ack", "c300x_media_sip_send_ok", "c300x_media_sip_send_ring_bye", "c300x_media_sip_send_bye", "c300x_media_sip_send_cancel"}, {
        "c300x_media_sip_send_all", "c300x_media_sip_header_value", "c300x_media_sip_append_headers",
        "c300x_media_sip_make_tagged_to", "c300x_appendf", "snprintf", "strlen", "time",
    }),
])
def test_protocol_module_has_no_session_or_resource_ownership(tmp_path, module, exports, dependencies):
    source = NATIVE / f"src/media_{module}.c"
    obj = tmp_path / f"{module}.o"
    subprocess.run(["cc", "-std=c11", "-c", str(source), "-o", str(obj)], check=True)
    symbols = subprocess.check_output(["nm", "-g", str(obj)], text=True)
    actual_exports = {line.split()[-1] for line in symbols.splitlines() if " T " in line}
    assert actual_exports == exports
    actual_dependencies = {line.split()[-1] for line in symbols.splitlines() if " U " in line}
    assert actual_dependencies <= dependencies | {"__stack_chk_fail"}
    header = (NATIVE / f"src/media_{module}.h").read_text()
    assert "media_bridge" not in header
    assert "c300x_video" not in header
