"""Stock camera source-control backend with injected Linux syscalls."""

import subprocess
from pathlib import Path


def test_picture_source(tmp_path: Path) -> None:
    native = Path(__file__).resolve().parents[1] / "native_agent"
    binary = tmp_path / "picture-source-test"
    subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-Werror",
         native / "src/picture_source.c", native / "test/picture_source_test.c",
         *(f"-Wl,--wrap={name}" for name in ("open", "close", "readlink", "fstat", "ioctl")),
         "-o", binary],
        check=True,
    )
    subprocess.run([binary], check=True, timeout=5)
