"""Finalization failures must not report success or discard recovery files."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "native_agent"


@pytest.fixture(scope="module", params=[False, True], ids=["host", "asan-ubsan"])
def finalize_binary(request, tmp_path_factory):
    binary = tmp_path_factory.mktemp("update-finalize") / "finalize-test"
    flags = (["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"]
             if request.param else ["-O2"])
    sources = ["test/agent_update_finalize_test.c", "src/file_io.c", "src/string_util.c",
               "src/json_util.c", "src/json_parse.c", "src/sha256.c"]
    result = subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         "-Wall", "-Wextra", "-Werror", *flags,
         *(str(ROOT / source) for source in sources), "-o", str(binary)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("scenario", [
    "control", "qml/C300XEnergyDistribution.qml.update-backup",
    "bundle.json.update-backup", "qml/HomeAssistant.qml.update-backup",
    "c300x-agent-native.update-backup",
    "remount-prepare-rw", "remount-prepare-ro", "remount-install-rw", "remount-install-ro",
    "remount-finalize-rw", "remount-finalize-ro", "remount-rollback-rw", "remount-rollback-ro",
    "remount-no-root-change", "remount-link-rw", "remount-link-ro",
])
def test_finalization_cleanup_and_recovery_preserving_retry(finalize_binary, tmp_path, scenario):
    result = subprocess.run([str(finalize_binary), str(tmp_path), scenario],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    if scenario.startswith("remount-"):
        assert "root remount" in result.stderr
    elif scenario != "control":
        assert "backup cleanup" in result.stderr
        assert "recovery files retained" in result.stderr
