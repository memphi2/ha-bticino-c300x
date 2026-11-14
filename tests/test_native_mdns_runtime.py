"""Exercise production discovery parsing without multicast/device access."""

import subprocess
from pathlib import Path


def test_mdns_query_filter(tmp_path):
    native = Path(__file__).resolve().parents[1] / "native_agent"
    executable = tmp_path / "mdns-query"
    subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-Werror",
         "-I", str(native / "src"), str(native / "test/mdns_query_test.c"),
         str(native / "src/string_util.c"), "-o", str(executable)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run([str(executable)], check=True, timeout=5)
