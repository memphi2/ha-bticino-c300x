"""Execute the production metrics and HTTP code with controlled CPU counters."""

import subprocess
from pathlib import Path


def test_native_metrics_snapshot_and_delivery(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1] / "native_agent"
    sources = sorted(
        str(path)
        for path in (root / "src").glob("*.c")
        if path.name not in {"http.c", "main.c", "system_metrics.c"}
    )
    binary = tmp_path / "metrics-test"
    subprocess.run(
        [
            "gcc",
            "-std=c11",
            "-O2",
            "-D_DEFAULT_SOURCE",
            "-D_POSIX_C_SOURCE=200809L",
            "-ffunction-sections",
            "-fdata-sections",
            "-Wl,--gc-sections",
            str(root / "test" / "metrics_test.c"),
            *sources,
            "-pthread",
            "-ldl",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
