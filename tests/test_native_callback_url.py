"""Exercise HTTP and HTTPS callback parsing without networking."""

import subprocess
from pathlib import Path


def test_native_callback_url_parser(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1] / "native_agent"
    binary = tmp_path / "callback-url-test"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            str(root / "test/callback_url_test.c"),
            str(root / "src/http_util.c"),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
