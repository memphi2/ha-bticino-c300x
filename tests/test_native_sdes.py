"""SDES crypto selection stays within one media attribute."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("sanitize", [False, True])
def test_sdes_crypto_selection(tmp_path, sanitize):
    native = Path(__file__).resolve().parents[1] / "native_agent"
    binary = tmp_path / "sdes"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    subprocess.run(["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-Werror",
                    *flags, str(native / "test/media_sdes_test.c"),
                    str(native / "src/media_sip.c"), str(native / "src/media_base64.c"),
                    "-o", str(binary)], check=True, capture_output=True, text=True)
    subprocess.run([str(binary)], check=True, timeout=5)
