"""The agent's own ARM start code: what a command prints reaches a pipe."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

START = Path(__file__).resolve().parents[1] / "native_agent/src/arm_start.S"
SYSROOT = Path("/usr/arm-linux-gnueabihf")


@pytest.mark.skipif(
    not (shutil.which("arm-linux-gnueabihf-gcc") and shutil.which("qemu-arm") and SYSROOT.is_dir()),
    reason="needs the ARM cross compiler and qemu-arm",
)
def test_output_written_to_a_pipe_is_flushed_at_exit(tmp_path: Path) -> None:
    program = tmp_path / "main.c"
    program.write_text(
        '#include <stdio.h>\nint main(int argc, char **argv)\n'
        '{ printf("{\\"argc\\":%d,\\"last\\":\\"%s\\"}\\n", argc, argv[argc - 1]); return 3; }\n'
    )
    binary = tmp_path / "start-test"
    subprocess.run(
        ["arm-linux-gnueabihf-gcc", "-nostartfiles", str(START), str(program), "-o", str(binary)],
        check=True, capture_output=True, text=True,
    )
    result = subprocess.run(
        ["qemu-arm", "-L", str(SYSROOT), str(binary), "status", "apply"],
        capture_output=True, text=True, check=False,
    )
    assert (result.returncode, result.stdout) == (3, '{"argc":3,"last":"apply"}\n')
